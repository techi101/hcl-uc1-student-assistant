"""Ingest documents into ChromaDB + search them. Owner: A. Shapes: docs/CONTRACT.md section 2.

ingest_file: file -> text per page (OCR if scanned) -> clause chunks -> embeddings -> Chroma (+ metadata)
             -> row in SQLite table `sources` (the live Source Register served by GET /sources)
search:      question -> embedding -> top-k chunks -> add chunks of documents that SUPERSEDE what was found
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app import config
from app.db import connect

log = logging.getLogger(__name__)

COLLECTION = "nsut_docs"
REGISTER_FIELDS = ["doc_id", "title", "issuer", "authority_level", "doc_type", "version", "effective_from",
                   "effective_to", "supersedes", "scope_programmes", "scope_batches", "provenance",
                   "retrieved_on", "synthetic"]
MAX_CHUNK = 1500          # chars; a long clause is split into parts that keep the same section label
MIN_PAGE_TEXT = 50        # fewer chars than this on a PDF page -> treat as scanned -> OCR

# ---------- metadata normalisation (register values are often free text like "2019-20") ----------
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_SESSION = re.compile(r"\b(20\d{2})\s*-\s*(\d{2,4})\b")


def norm_date(value: str, session_start: bool = True) -> str:
    """'2024-07-01' stays; session '2019-20' -> '2019-07-01' (assumption: academic session starts 1 July)."""
    value = (value or "").strip()
    m = _DATE.search(value)
    if m:
        return m.group(0)
    m = _SESSION.search(value)
    if m:
        return f"{m.group(1)}-07-01" if session_start else f"{int(m.group(1)) + 1}-06-30"
    m = re.search(r"\b(20\d{2})\b", value)
    return f"{m.group(1)}-07-01" if m else ""


def normalise_meta(meta: dict) -> dict:
    m = {k: ("" if meta.get(k) is None else str(meta.get(k)).strip()) for k in REGISTER_FIELDS}
    m["authority_level"] = int(re.search(r"[1-5]", m["authority_level"] or "3").group(0))
    m["effective_from_raw"] = m["effective_from"]
    m["effective_from"] = norm_date(m["effective_from"]) or "1900-01-01"
    m["effective_to"] = norm_date(m["effective_to"], session_start=False) if m["effective_to"] else ""
    m["doc_type"] = (m["doc_type"].split()[0].lower() if m["doc_type"] else "unknown")
    m["scope_programmes"] = m["scope_programmes"] or "ALL"
    m["scope_batches"] = m["scope_batches"] or "ALL"
    # supersedes: keep only tokens that look like doc ids (DOC-ID or DOC-ID#7.2)
    m["supersedes"] = ";".join(re.findall(r"[A-Z][A-Z0-9-]{3,}(?:#[\d.]+)?", m["supersedes"]))
    return m


# ---------- text extraction ----------
_GARBLED = re.compile(r"[À-ÿŒ-˿]")   # legacy Hindi fonts extract as Latin-1 accents


def _clean_line(line: str) -> str | None:
    s = line.strip()
    if not s:
        return None
    if len(_GARBLED.findall(s)) > 0.15 * len(s):
        return None                     # drop garbled Hindi legacy-font text
    if re.search(r"\.{5,}|…{2,}", s):
        return None                     # table-of-contents dot leaders ("7. PROGRAMME ....... 11")
    return s


def extract_pages(path: str) -> list[tuple[int, str, bool]]:
    """[(page_no, text, was_ocr)] for PDF / TXT / MD / DOCX."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        out = []
        for i, page in enumerate(PdfReader(path).pages):
            text = page.extract_text() or ""
            ocr = False
            if len(text.strip()) < MIN_PAGE_TEXT:
                from app.ocr import ocr_pdf_page
                text, ocr = ocr_pdf_page(path, i), True
            lines = [c for c in (_clean_line(x) for x in text.splitlines()) if c]
            out.append((i + 1, "\n".join(lines), ocr))
        return out
    if suffix == ".docx":
        import docx
        return [(1, "\n".join(par.text for par in docx.Document(path).paragraphs if par.text.strip()), False)]
    return [(1, p.read_text(encoding="utf-8", errors="replace"), False)]


# ---------- chunking by clause ----------
_CLAUSE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+)\.?\s+\S")          # 11.2. / 11.2 / 7.3.1
_TOP = re.compile(r"^(\d{1,2})\.\s+\S")                            # 7. PROGRAMME DURATION / 1. In supersession
_FAQ = re.compile(r"^(Q\d{1,3})[.:)]\s*\S", re.I)                 # Q1. How much ...
_PAGE_NUM = re.compile(r"^\d{1,3}$")                               # bare page numbers at top of page


def chunk_pages(pages: list[tuple[int, str, bool]]) -> list[dict]:
    """One chunk per numbered clause (keeps section + start page). Text before the first numbered
    clause (cover pages, fee tables, OCR pages without numbering) becomes one chunk per page."""
    chunks: list[dict] = []
    heading = ""
    cur = {"section": "", "page": pages[0][0] if pages else 1, "lines": []}

    def flush() -> None:
        text = "\n".join(cur["lines"]).strip()
        if len(text) < 20:
            return
        prefix = f"[{heading}] " if heading and heading not in text else ""
        for i in range(0, len(text), MAX_CHUNK):
            chunks.append({"section": cur["section"] or f"page {cur['page']}", "page": cur["page"],
                           "text": prefix + text[i:i + MAX_CHUNK]})

    for page_no, text, _ in pages:
        for line in text.splitlines():
            if _PAGE_NUM.match(line):
                continue
            m = _CLAUSE.match(line) or _FAQ.match(line) or _TOP.match(line)
            if m:
                flush()
                sec = m.group(1).upper()
                if m.re is _TOP and line.upper() == line:      # "7. PROGRAMME DURATION AND STRUCTURE"
                    heading = line.strip()
                cur = {"section": sec, "page": page_no, "lines": [line]}
            else:
                cur["lines"].append(line)
        if not cur["section"]:                                 # still before any numbered clause
            flush()
            cur = {"section": "", "page": page_no + 1, "lines": []}
    flush()
    return chunks


# ---------- embeddings + Chroma ----------
@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.EMBED_MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    return _embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


@lru_cache(maxsize=1)
def _collection():
    import chromadb
    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    # one collection per embedding model, so configs can be compared side by side (eval) without clobbering
    name = COLLECTION if "MiniLM-L6" in config.EMBED_MODEL else COLLECTION + "__" + re.sub(r"[^a-z0-9]+", "_", config.EMBED_MODEL.lower())[-40:]
    return client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})


def _init_sources_table() -> None:
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS sources (
            doc_id TEXT PRIMARY KEY, meta_json TEXT NOT NULL, file_name TEXT, file_sha256 TEXT,
            chunks_indexed INTEGER, ocr_pages INTEGER, ingested_at TEXT)""")


def get_source(doc_id: str) -> dict | None:
    _init_sources_table()
    with connect() as con:
        row = con.execute("SELECT meta_json FROM sources WHERE doc_id = ?", (doc_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_sources() -> list[dict]:
    _init_sources_table()
    with connect() as con:
        rows = con.execute("SELECT meta_json, file_name, chunks_indexed, ocr_pages, ingested_at "
                           "FROM sources ORDER BY doc_id").fetchall()
    return [{**json.loads(r[0]), "file_name": r[1], "chunks_indexed": r[2], "ocr_pages": r[3],
             "ingested_at": r[4]} for r in rows]


def ingest_file(path: str, meta: dict, extract_rules: bool = True) -> dict:
    """Index one document. Re-ingesting the same doc_id replaces its old chunks (new version of the file).
    extract_rules=True (live /ingest): also propose validated rule_registry rows from the new document.
    Our own documents use the human-checked data/rules.csv instead (scripts/ingest_all passes False)."""
    _init_sources_table()
    m = normalise_meta(meta)
    doc_id = m["doc_id"]
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    old = None
    with connect() as con:
        old = con.execute("SELECT file_sha256, chunks_indexed FROM sources WHERE doc_id = ?", (doc_id,)).fetchone()
    if old and old[0] == sha and old[1] and _collection().get(where={"doc_id": doc_id}, limit=1)["ids"]:
        return {"doc_id": doc_id, "chunks_indexed": old[1], "status": "already_indexed"}

    pages = extract_pages(path)
    chunks = chunk_pages(pages)
    if not chunks:
        return {"doc_id": doc_id, "chunks_indexed": 0, "status": "error: no text found"}

    col = _collection()
    col.delete(where={"doc_id": doc_id})                      # replace previous version's chunks
    base = {k: m[k] for k in REGISTER_FIELDS}
    ids, docs, metas = [], [], []
    for i, ch in enumerate(chunks):
        ids.append(f"{doc_id}::{i}")
        docs.append(ch["text"])
        metas.append({**base, "section": ch["section"], "page": int(ch["page"]), "file_name": Path(path).name})
    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=embed(docs))

    ocr_pages = sum(1 for _, _, was_ocr in pages if was_ocr)
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)",
                    (doc_id, json.dumps(m), Path(path).name, sha, len(chunks), ocr_pages,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")))
    log.info("ingested %s: %d chunks (%d OCR pages)", doc_id, len(chunks), ocr_pages)
    rules = []
    if extract_rules:
        from app.rule_extract import extract_rules as _extract
        rules = _extract(m, chunks)
    return {"doc_id": doc_id, "chunks_indexed": len(chunks), "status": "replaced" if old else "indexed",
            "rules_extracted": [r["rule_id"] + " = " + r["value"] for r in rules]}


def _to_chunk(doc: str, meta: dict, distance: float) -> dict:
    return {**meta, "text": doc, "score": round(1 - distance, 4)}


def search(query: str, k: int, where: dict | None = None) -> list[dict]:
    """Top-k chunks with metadata + cosine similarity score, plus chunks of any document that
    explicitly supersedes a found document/clause (so precedence can see both sides)."""
    col = _collection()
    if col.count() == 0:
        return []
    q = embed([query])
    res = col.query(query_embeddings=q, n_results=min(k, col.count()), where=where)
    found = [_to_chunk(d, m, dist) for d, m, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])]

    # pull in superseding documents (e.g. a circular that replaces clause 11.2) even if they ranked lower
    seen = {(c["doc_id"], c["section"]) for c in found}
    found_docs = {c["doc_id"] for c in found}
    for src in list_sources():
        targets = [t for t in src.get("supersedes", "").split(";") if t]
        if src["doc_id"] in found_docs or not any(t.split("#")[0] in found_docs for t in targets):
            continue
        extra = col.query(query_embeddings=q, n_results=1, where={"doc_id": src["doc_id"]})
        for d, m, dist in zip(extra["documents"][0], extra["metadatas"][0], extra["distances"][0]):
            if (m["doc_id"], m["section"]) not in seen:
                found.append({**_to_chunk(d, m, dist), "added_by": "supersession"})
    return found


def vector_count() -> int:
    try:
        return _collection().count()
    except Exception:
        return -1


def section_page(doc_id: str, section: str) -> int | None:
    """Page number where a clause starts (for citations of rule clauses that were not in the retrieved chunks)."""
    try:
        sec = str(section).split()[0]                       # "9.5 Table 5" -> "9.5"
        got = _collection().get(where={"$and": [{"doc_id": doc_id}, {"section": sec}]}, limit=1)
        return int(got["metadatas"][0]["page"]) if got["ids"] else None
    except Exception:
        return None
