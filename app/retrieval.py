"""Ingest documents into ChromaDB + search them. Owner: A. Shapes: docs/CONTRACT.md section 2.

ingest_file: file -> text per page (OCR if scanned) -> clause chunks -> embeddings -> Chroma (+ metadata)
             -> row in SQLite table `sources` (the live Source Register served by GET /sources)
search:      question -> embedding -> top-k chunks -> add chunks of documents that SUPERSEDE what was found
"""
# WHAT THIS FILE IS: the "librarian" of the chatbot. It reads NSUT documents (PDF, DOCX, TXT, MD), cuts them
# into small pieces (one piece = one numbered clause), and later finds the pieces that best match a question.
# Real example: the B.Tech Regulations PDF (NSUT-BTECH-REG-2019) becomes chunks like "11.2 ... 75% attendance ...".
# When a student asks "What is the minimum attendance?", search() returns clause 11.2 AND the circular
# SYN-CIRC-ATT-2026 (which supersedes NSUT-BTECH-REG-2019#11.2), so app/precedence.py can decide which one wins.
# It keeps two stores:
#   ChromaDB = a database for embeddings. An embedding is a list of 384 numbers that captures the MEANING of a text,
#   so texts with similar meaning get similar numbers. Each chunk is saved with its metadata (extra labels about it:
#   doc_id, section, page, authority_level 1-5, effective_from/to, scope, supersedes).
#   SQLite table `sources` = the Source Register: one row per document (its metadata, file fingerprint, chunk count).
# Overall flow: file -> text per page (OCR if scanned) -> cleaned lines -> clause chunks -> embeddings -> ChromaDB + sources row
#
# Standard library imports (they come with Python, nothing to install):
# hashlib: sha256 fingerprint of a file (spots an unchanged re-upload)
import hashlib
# json: dict <-> text; metadata is saved as JSON text in SQLite
import json
# logging: log messages for the server log (instead of print)
import logging
# math.log: rare keywords count more in the hybrid re-rank (idf)
import math
# re = regular expressions: patterns that find text like "11.2" or "2019-20"
import re
# datetime: timestamp for "ingested_at", in UTC (world time, no time zone confusion)
from datetime import datetime, timezone
# lru_cache: remembers a function's result, so slow setup runs only once
from functools import lru_cache
# Path = easy file paths: file name, suffix (.pdf), read bytes
from pathlib import Path

# Our own modules:
# config = our settings: EMBED_MODEL (model name), CHROMA_DIR (folder for ChromaDB)
from app import config
# connect() opens the SQLite database file (app/db.py)
from app.db import connect

# log = a logger named "app.retrieval"
log = logging.getLogger(__name__)

# Name of the ChromaDB collection. A collection = one named "table" that holds chunk texts + embeddings + metadata.
COLLECTION = "nsut_docs"
# The columns of the Source Register. Every document's metadata is cut down to exactly these fields.
# authority_level: 1 = Regulations (strongest) ... 5 = unofficial (weakest). supersedes = which doc/clause it replaces.
REGISTER_FIELDS = ["doc_id", "title", "issuer", "authority_level", "doc_type", "version", "effective_from",
                   "effective_to", "supersedes", "scope_programmes", "scope_batches", "provenance",
                   "retrieved_on", "synthetic"]
# Size limits, in characters:
MAX_CHUNK = 1500          # chars; a long clause is split into parts that keep the same section label
MIN_PAGE_TEXT = 50        # fewer chars than this on a PDF page -> treat as scanned -> OCR

# ---------- metadata normalisation (register values are often free text like "2019-20") ----------
# _DATE finds a full ISO date: 4 digits, "-", 2 digits, "-", 2 digits. Matches "2024-07-01" inside "w.e.f. 2024-07-01".
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# _SESSION finds an academic session: "20" + 2 digits, optional spaces, "-", optional spaces, then 2 to 4 digits.
# Matches "2019-20", "2019 - 20" and "2019-2020". \b = word edge, so it does not match in the middle of a longer number.
_SESSION = re.compile(r"\b(20\d{2})\s*-\s*(\d{2,4})\b")


# IN: a free-text date like "2024-07-01", "2019-20" or "Session 2019"  ->  OUT: ISO date "YYYY-MM-DD" (or "" if none).
# WHY: every date must look like "YYYY-MM-DD" so precedence.py can compare dates as plain strings.
# Example: "2019-20" -> "2019-07-01" (as a start date) or "2020-06-30" (as an end date, session_start=False).
def norm_date(value: str, session_start: bool = True) -> str:
    """'2024-07-01' stays; session '2019-20' -> '2019-07-01' (assumption: academic session starts 1 July)."""
    # Treat None as "" and trim spaces.
    value = (value or "").strip()
    # Case 1: already a full date like "2024-07-01" -> return it as it is.
    m = _DATE.search(value)
    if m:
        return m.group(0)
    # Case 2: a session like "2019-20" -> start = 1 July of the first year, end = 30 June of the next year.
    m = _SESSION.search(value)
    if m:
        return f"{m.group(1)}-07-01" if session_start else f"{int(m.group(1)) + 1}-06-30"
    # Case 3: only a year like "2019" (regex: "20" + 2 digits as a whole word) -> 1 July of that year.
    # Nothing found at all -> "" (the caller picks a default).
    m = re.search(r"\b(20\d{2})\b", value)
    return f"{m.group(1)}-07-01" if m else ""


# IN: raw metadata dict for one document (from the register file or the /ingest form)  ->  OUT: clean metadata dict.
# WHY: register values are messy free text ("Level 2 (circular)", "2019-20", "Circular No. 12"). Later code needs clean
# values: an int level, ISO dates, a one-word doc_type, "ALL" for an empty scope, and only real doc ids in supersedes.
# Example: {"authority_level": "2 - Circular", "supersedes": "NSUT-BTECH-REG-2019#11.2 (attendance)"}
#   -> authority_level 2, supersedes "NSUT-BTECH-REG-2019#11.2".
def normalise_meta(meta: dict) -> dict:
    # Keep only the register fields. None -> "", everything else -> text with spaces trimmed.
    m = {k: ("" if meta.get(k) is None else str(meta.get(k)).strip()) for k in REGISTER_FIELDS}
    # authority_level: take the first digit 1-5 found in the text (regex [1-5]: "Level 2" -> 2). Empty -> default 3.
    m["authority_level"] = int(re.search(r"[1-5]", m["authority_level"] or "3").group(0))
    # Keep the original start-date text too (for display), then turn both dates into ISO dates.
    # No start date -> "1900-01-01" (means "in force since forever"). No end date -> "" (still in force).
    m["effective_from_raw"] = m["effective_from"]
    m["effective_from"] = norm_date(m["effective_from"]) or "1900-01-01"
    m["effective_to"] = norm_date(m["effective_to"], session_start=False) if m["effective_to"] else ""
    # doc_type: first word only, lowercase ("Circular No. 12" -> "circular"). Empty -> "unknown".
    m["doc_type"] = (m["doc_type"].split()[0].lower() if m["doc_type"] else "unknown")
    # Empty scope means "applies to everyone" -> store "ALL".
    m["scope_programmes"] = m["scope_programmes"] or "ALL"
    m["scope_batches"] = m["scope_batches"] or "ALL"
    # supersedes: keep only tokens that look like doc ids (DOC-ID or DOC-ID#7.2)
    # Regex: a capital letter, then 3 or more capitals/digits/hyphens (the doc id), then optionally "#" + digits and
    # dots (the clause). Matches "NSUT-BTECH-REG-2019#11.2" and "SYN-CIRC-ATT-2026". Several ids are joined with ";".
    # A doc id always contains a hyphen (NSUT-BTECH-REG-2019), so plain words like "UNSURE" are not taken as ids.
    # A note that only describes a possible partial supersession ("... UNSURE; ... do not supersede") is NOT
    # applied: a wrong supersession silently deletes a whole document from every answer (found: the 2026-27 fee
    # notice was wiping out the 2025-26 fee tables).
    sup = m["supersedes"]
    m["supersedes"] = "" if re.search(r"unsure|do not supersede|only for", sup, re.I) else \
        ";".join(re.findall(r"[A-Z][A-Z0-9]*-[A-Z0-9-]{2,}(?:#[\d.]+)?", sup))
    return m


# ---------- text extraction ----------
# _GARBLED matches one "accented Latin" character: the range A-grave to y-umlaut (Latin-1 accents) or the range
# from OE onwards (more Latin letters and marks). Old Hindi PDF fonts come out as junk like "ÁÆÀÖ" instead of
# real Hindi letters, so a line full of these characters is garbled Hindi.
_GARBLED = re.compile(r"[À-ÿŒ-˿]")   # legacy Hindi fonts extract as Latin-1 accents


# IN: one raw line of page text  ->  OUT: the trimmed line, or None if the line is junk and should be dropped.
# Example: "7. PROGRAMME DURATION ....... 11" -> None (table-of-contents line); "11.2 A student must ..." -> kept.
def _clean_line(line: str) -> str | None:
    s = line.strip()
    # Empty line -> drop.
    if not s:
        return None
    # More than 15% of the characters are junk accents -> garbled Hindi -> drop.
    if len(_GARBLED.findall(s)) > 0.15 * len(s):
        return None                     # drop garbled Hindi legacy-font text
    # Regex: 5 or more dots in a row, OR 2 or more "…" characters. These dot leaders appear only in a table of contents.
    if re.search(r"\.{5,}|…{2,}", s):
        return None                     # table-of-contents dot leaders ("7. PROGRAMME ....... 11")
    # Normal line -> keep it.
    return s


# IN: path of one file  ->  OUT: list of (page number, page text, was OCR used?) tuples.
# Example: a 40-page PDF -> [(1, "NETAJI SUBHAS ...", False), (2, "...", False), ...]; a DOCX or TXT -> one "page" 1.
# flow: PDF page -> text (or OCR if almost no text) -> cleaned lines
def extract_pages(path: str) -> list[tuple[int, str, bool]]:
    """[(page_no, text, was_ocr)] for PDF / TXT / MD / DOCX."""
    # Look at the file extension (".pdf", ".docx", ...) in lowercase to decide how to read the file.
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        # PDF: read page by page with pypdf (imported here, only when needed, so the app starts faster).
        from pypdf import PdfReader
        out = []
        for i, page in enumerate(PdfReader(path).pages):
            # Read the text layer of this page. None -> "".
            text = page.extract_text() or ""
            ocr = False
            # Almost no text (fewer than MIN_PAGE_TEXT = 50 chars) means the page is probably a scanned picture.
            # Then run OCR (Optical Character Recognition = reading letters from an image) via app/ocr.py and mark ocr=True.
            if len(text.strip()) < MIN_PAGE_TEXT:
                from app.ocr import ocr_pdf_page
                text, ocr = ocr_pdf_page(path, i), True
            # Clean every line with _clean_line and drop the lines that came back None (junk).
            lines = [c for c in (_clean_line(x) for x in text.splitlines()) if c]
            # Save (page number starting at 1, cleaned text, OCR flag). Humans count pages from 1, so citations match.
            out.append((i + 1, "\n".join(lines), ocr))
        return out
    # DOCX (Word file): python-docx gives paragraphs. Join the non-empty ones; the whole file counts as page 1.
    if suffix == ".docx":
        import docx
        return [(1, "\n".join(par.text for par in docx.Document(path).paragraphs if par.text.strip()), False)]
    # Anything else (TXT, MD): read as UTF-8 text. errors="replace" puts a replacement mark for bad bytes instead of crashing.
    return [(1, p.read_text(encoding="utf-8", errors="replace"), False)]


# ---------- chunking by clause ----------
# These patterns spot the START of a numbered clause. ^ = the match must begin at the start of the line.
# _CLAUSE: 1-2 digits, then one or more ".digits" groups, an optional dot, a space, then any non-space character.
#   Matches "11.2 A student...", "11.2. A student...", "7.3.1 The..."; group(1) = "11.2" (the section label).
_CLAUSE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+)\.?\s+\S")          # 11.2. / 11.2 / 7.3.1
# _TOP: a top-level number like "7." then a space and text. Matches "7. PROGRAMME DURATION"; group(1) = "7".
_TOP = re.compile(r"^(\d{1,2})\.\s+\S")                            # 7. PROGRAMME DURATION / 1. In supersession
# _FAQ: "Q" + 1-3 digits, then ".", ":" or ")". re.I = ignore upper/lower case.
#   Matches "Q1. How much..." and "q12) Can I..."; group(1) = "Q1".
_FAQ = re.compile(r"^(Q\d{1,3})[.:)]\s*\S", re.I)                 # Q1. How much ...
# _PAGE_NUM: a line that is ONLY 1-3 digits, like "12". That is a page number, not content, so we skip it.
_PAGE_NUM = re.compile(r"^\d{1,3}$")                               # bare page numbers at top of page


# IN: pages from extract_pages  ->  OUT: list of chunks, each {"section", "page", "text"}.
# WHY: one clause per chunk means a search hit is one whole rule with a clean citation (doc + section + page).
# Example: lines "11.2 Attendance ... 75% ..." up to "11.3 ..." -> one chunk {"section": "11.2", "page": <start page>, "text": "11.2 ..."}.
OCR_WINDOW = 2000         # chars per piece of a scanned page: one fee-table page (~1,900 chars) stays ONE chunk
OCR_OVERLAP = 200         # longer pages: pieces overlap so a table row cut at a boundary appears whole in one of them
OCR_HEAD_LINES = 4        # top lines of a scanned page = programme name + column headers (e.g. "2025-26 2026-27 ...")


# IN: page number + OCR text of one scanned page  ->  OUT: chunks labelled "page N", each starting with the page header.
# flow: lines -> header = first 4 lines -> 2000-char windows with 200 overlap -> later windows get "[header]" in front
def _ocr_page_chunks(page_no: int, text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not _PAGE_NUM.match(ln)]
    body = "\n".join(lines)
    if len(body) < 20:
        return []
    head = " / ".join(lines[:OCR_HEAD_LINES])[:300]
    out, start = [], 0
    while True:
        piece = body[start:start + OCR_WINDOW]
        # the first window already starts with the header; later ones get it in front so "Tuition Fee 97,000"
        # still says "Bachelor of Technology ... 2025-26 2026-27 2027-28 2028-29"
        out.append({"section": f"page {page_no}", "page": page_no, "ocr": True,
                    "text": piece if start == 0 else f"[{head}]\n{piece}"})
        if start + OCR_WINDOW >= len(body):
            return out
        start += OCR_WINDOW - OCR_OVERLAP


def chunk_pages(pages: list[tuple[int, str, bool]]) -> list[dict]:
    """One chunk per numbered clause (keeps section + start page). Text before the first numbered
    clause (cover pages, fee tables, OCR pages without numbering) becomes one chunk per page."""
    # chunks = the result list. heading = the latest ALL-CAPS top heading (like "7. PROGRAMME DURATION"),
    # put in front of chunk text for context. cur = the clause being collected right now: section label, start page, lines.
    chunks: list[dict] = []
    heading = ""
    cur = {"section": "", "page": pages[0][0] if pages else 1, "lines": []}

    # IN: nothing (it reads cur, heading and chunks from chunk_pages)  ->  OUT: nothing; appends cur as one or more chunks.
    # WHY: called every time a new clause starts, so the clause we just finished gets saved.
    def flush() -> None:
        # Join the collected lines into one text.
        text = "\n".join(cur["lines"]).strip()
        # Under 20 characters is too small to be useful (stray titles, empty bits) -> skip it.
        if len(text) < 20:
            return
        # Put the heading in front, like "[7. PROGRAMME DURATION] 7.3 ...", unless the text already contains it.
        # This helps search: the heading words become part of the chunk's meaning.
        prefix = f"[{heading}] " if heading and heading not in text else ""
        # Long clause (more than MAX_CHUNK = 1500 chars) -> cut into 1500-char parts. Every part keeps the same section and page.
        # No section yet (text before the first numbered clause) -> label it "page N".
        for i in range(0, len(text), MAX_CHUNK):
            chunks.append({"section": cur["section"] or f"page {cur['page']}", "page": cur["page"],
                           "text": prefix + text[i:i + MAX_CHUNK]})

    # Main loop: go through every line of every page.
    # flow: line -> page number? skip -> starts a new clause? (save old clause, start new one) : add line to current clause
    for page_no, text, was_ocr in pages:
        # Scanned page (OCR): it is usually a TABLE (fee structure, scholarship list), and its row numbers
        # ("1.1 Tuition Fee", "2.1 Student Fund") look like clause numbers. Cutting there gave chunks like
        # "1.1 Tuition Fee 97,000 108,000" that no longer say WHICH programme or WHICH year each column is.
        # So a scanned page is chunked by page instead, and every piece repeats the page's header lines.
        if was_ocr:
            flush()
            chunks.extend(_ocr_page_chunks(page_no, text))
            cur = {"section": "", "page": page_no + 1, "lines": []}
            continue
        for line in text.splitlines():
            # Bare page-number line like "12" -> skip it.
            if _PAGE_NUM.match(line):
                continue
            # Does this line start a new clause? Try the 3 patterns in order: "11.2" style, "Q1" style, then "7." style.
            m = _CLAUSE.match(line) or _FAQ.match(line) or _TOP.match(line)
            if m:
                # Yes: save the clause we were collecting, then start a new one beginning with this line.
                flush()
                # Section label from the pattern, uppercased ("q1" -> "Q1").
                sec = m.group(1).upper()
                # A "7." line written fully in CAPITALS is a heading. Remember it so later chunks get it as a prefix.
                if m.re is _TOP and line.upper() == line:      # "7. PROGRAMME DURATION AND STRUCTURE"
                    heading = line.strip()
                cur = {"section": sec, "page": page_no, "lines": [line]}
            # Not a new clause -> this line belongs to the current clause.
            else:
                cur["lines"].append(line)
        # End of a page, and still no numbered clause seen (cover page, fee table, unnumbered OCR page):
        # save this page as its own chunk, then start fresh for the next page.
        if not cur["section"]:                                 # still before any numbered clause
            flush()
            cur = {"section": "", "page": page_no + 1, "lines": []}
    # After the last page, save the final clause too.
    flush()
    return chunks


# ---------- embeddings + Chroma ----------
# IN: nothing  ->  OUT: the loaded embedding model (all-MiniLM-L6-v2 by default, name from config.EMBED_MODEL).
# WHY @lru_cache(maxsize=1): loading the model takes seconds. lru_cache remembers the result of the first call,
# so every later call gets the same model back instantly instead of loading it again.
@lru_cache(maxsize=1)
def _embedder():
    # Imported inside the function so the heavy library loads only when it is first needed.
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.EMBED_MODEL)


# IN: list of texts  ->  OUT: one embedding per text (all-MiniLM-L6-v2 gives 384 numbers per text).
# Example: "minimum attendance?" and "75% attendance is required" get embeddings that are close together.
# normalize_embeddings=True scales every embedding to length 1, which makes cosine comparison simple.
# .tolist() turns the numpy array into plain Python lists, which ChromaDB accepts.
def embed(texts: list[str]) -> list[list[float]]:
    return _embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


# IN: nothing  ->  OUT: the ChromaDB collection where all chunks live (opened once, then cached by lru_cache).
# WHY: ChromaDB is a vector database. It saves each chunk's text + embedding + metadata on disk (storage/chroma)
# and can quickly find the chunks whose embeddings are closest to a question's embedding.
@lru_cache(maxsize=1)
def _collection():
    import chromadb
    # Make sure the storage folder exists.
    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    # PersistentClient = ChromaDB that saves to disk, so the index survives a server restart.
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    # one collection per embedding model, so configs can be compared side by side (eval) without clobbering
    # Default MiniLM model -> "nsut_docs". Other model -> "nsut_docs__" + model name where every run of characters that
    # are not a-z or 0-9 (regex [^a-z0-9]+) becomes "_", last 40 chars only. "BAAI/bge-small-en" -> "nsut_docs__baai_bge_small_en".
    name = COLLECTION if "MiniLM-L6" in config.EMBED_MODEL else COLLECTION + "__" + re.sub(r"[^a-z0-9]+", "_", config.EMBED_MODEL.lower())[-40:]
    # Open the collection (create it the first time). "hnsw:space": "cosine" = measure closeness by cosine distance:
    # 0 = same direction (same meaning), bigger = less similar. HNSW is the fast nearest-neighbour index ChromaDB uses.
    return client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})


# IN: nothing  ->  OUT: nothing; makes sure the SQLite `sources` table (the Source Register) exists.
# WHY: called at the start of every function that uses `sources`, so a brand-new database never crashes.
# Columns: doc_id (unique key), meta_json (all clean metadata as JSON text), file_name, file_sha256 (fingerprint),
# chunks_indexed (how many chunks), ocr_pages (how many pages needed OCR), ingested_at (UTC time).
def _init_sources_table() -> None:
    # "with connect() as con" = open the database; at the end of the block the change is saved (committed),
    # or undone (rolled back) if an error happened.
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS sources (
            doc_id TEXT PRIMARY KEY, meta_json TEXT NOT NULL, file_name TEXT, file_sha256 TEXT,
            chunks_indexed INTEGER, ocr_pages INTEGER, ingested_at TEXT)""")


# IN: a doc_id like "SYN-CIRC-ATT-2026"  ->  OUT: its clean metadata dict, or None if it is not registered.
# Example: get_source("SYN-CIRC-ATT-2026") -> {"doc_id": "SYN-CIRC-ATT-2026", "supersedes": "NSUT-BTECH-REG-2019#11.2", ...}
def get_source(doc_id: str) -> dict | None:
    _init_sources_table()
    with connect() as con:
        # "?" is a placeholder: SQLite puts doc_id in safely (no SQL injection from odd text).
        row = con.execute("SELECT meta_json FROM sources WHERE doc_id = ?", (doc_id,)).fetchone()
    # meta_json is stored as text -> json.loads turns it back into a dict.
    return json.loads(row[0]) if row else None


# IN: nothing  ->  OUT: every registered document (metadata + file name, chunk count, OCR pages, ingest time), sorted by doc_id.
# WHY: this is what GET /sources shows, and search() uses it to find documents that supersede a found document.
def list_sources() -> list[dict]:
    _init_sources_table()
    with connect() as con:
        rows = con.execute("SELECT meta_json, file_name, chunks_indexed, ocr_pages, ingested_at "
                           "FROM sources ORDER BY doc_id").fetchall()
    # Merge each row's metadata dict with the extra columns into one dict per document.
    return [{**json.loads(r[0]), "file_name": r[1], "chunks_indexed": r[2], "ocr_pages": r[3],
             "ingested_at": r[4]} for r in rows]


# IN: file path + raw metadata (+ extract_rules flag)  ->  OUT: status dict like
#   {"doc_id": "SYN-CIRC-ATT-2026", "chunks_indexed": 3, "status": "indexed", "rules_extracted": [...]}.
# WHY: one function for both startup ingest (scripts/ingest_all.py) and live POST /ingest, so both behave the same.
# flow: clean metadata -> same file already indexed? stop -> pages -> chunks -> delete old chunks -> embed + add
#       -> Source Register row -> (optional) rule extraction
def ingest_file(path: str, meta: dict, extract_rules: bool = True) -> dict:
    """Index one document. Re-ingesting the same doc_id replaces its old chunks (new version of the file).
    extract_rules=True (live /ingest): also propose validated rule_registry rows from the new document.
    Our own documents use the human-checked data/rules.csv instead (scripts/ingest_all passes False)."""
    _init_sources_table()
    # Clean the metadata first (int level, ISO dates, clean supersedes).
    m = normalise_meta(meta)
    doc_id = m["doc_id"]
    # sha256 = a fingerprint of the file's bytes (64 hex characters). Same file -> same fingerprint;
    # change even one byte -> a totally different fingerprint.
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    # Look up what we saved last time for this doc_id (fingerprint + chunk count). None = never ingested.
    old = None
    with connect() as con:
        old = con.execute("SELECT file_sha256, chunks_indexed FROM sources WHERE doc_id = ?", (doc_id,)).fetchone()
    # Skip the work if: this doc_id was ingested before, with the SAME fingerprint, it had chunks, and those chunks
    # are still in ChromaDB (where = filter on metadata; limit=1 because we only need to know one exists).
    if old and old[0] == sha and old[1] and _collection().get(where={"doc_id": doc_id}, limit=1)["ids"]:
        return {"doc_id": doc_id, "chunks_indexed": old[1], "status": "already_indexed"}

    # Read the pages and cut them into clause chunks. No chunks -> nothing readable -> report an error.
    pages = extract_pages(path)
    chunks = chunk_pages(pages)
    if not chunks:
        return {"doc_id": doc_id, "chunks_indexed": 0, "status": "error: no text found"}

    # Get the collection and delete every old chunk of this doc_id, so a new version fully replaces the old one
    # and no outdated clauses stay behind.
    col = _collection()
    col.delete(where={"doc_id": doc_id})                      # replace previous version's chunks
    # base = the document-level metadata that all its chunks share.
    base = {k: m[k] for k in REGISTER_FIELDS}
    # Build 3 lists that line up for ChromaDB: ids ("NSUT-BTECH-REG-2019::0", "::1", ...), texts, and metadata.
    # Each chunk's metadata = document metadata + its own section, page and file name.
    ids, docs, metas, to_embed = [], [], [], []
    for i, ch in enumerate(chunks):
        ids.append(f"{doc_id}::{i}")
        docs.append(ch["text"])
        # scanned pages are EMBEDDED with the document title in front ("Annual Fee ... Academic Session 2025-26"), so
        # search can tell the 2025-26 fee table from the 2026-27 one; the stored text stays short (the LLM sees 900 chars)
        to_embed.append(f"[{m['title'][:160]}]\n{ch['text']}" if ch.get("ocr") else ch["text"])
        metas.append({**base, "section": ch["section"], "page": int(ch["page"]), "file_name": Path(path).name,
                      "ocr": bool(ch.get("ocr"))})   # compose shows scanned pages in full (app/graph.py)
    # Save everything in one call. embed(docs) computes the 384-number embedding of every chunk text.
    col.add(ids=ids, documents=docs, metadatas=metas, embeddings=embed(to_embed))

    # Count how many pages needed OCR (shown in the register).
    ocr_pages = sum(1 for _, _, was_ocr in pages if was_ocr)
    # Write this document's row in the Source Register. INSERT OR REPLACE = overwrite the row if doc_id already exists.
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)",
                    (doc_id, json.dumps(m), Path(path).name, sha, len(chunks), ocr_pages,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")))
    # One-line summary in the server log.
    log.info("ingested %s: %d chunks (%d OCR pages)", doc_id, len(chunks), ocr_pages)
    # Live /ingest only: app/rule_extract.py proposes rule_registry rows (like an attendance % threshold) from the
    # new chunks. Our own documents skip this and use the human-checked data/rules.csv instead.
    rules = []
    if extract_rules:
        from app.rule_extract import extract_rules as _extract
        rules = _extract(m, chunks)
    # Report back: "replaced" if this doc_id existed before, else "indexed". Rules are listed as "RULE_ID = value".
    return {"doc_id": doc_id, "chunks_indexed": len(chunks), "status": "replaced" if old else "indexed",
            "rules_extracted": [r["rule_id"] + " = " + r["value"] for r in rules]}


# IN: chunk text + its metadata + ChromaDB distance  ->  OUT: one result dict with a "score".
# WHY: ChromaDB returns cosine DISTANCE (0 = identical). A SIMILARITY score (1 = identical) is easier to read,
# so score = 1 - distance, rounded to 4 decimals. Example: distance 0.31 -> score 0.69.
def _to_chunk(doc: str, meta: dict, distance: float) -> dict:
    return {**meta, "text": doc, "score": round(1 - distance, 4)}


# IN: question text, k (how many chunks), optional metadata filter  ->  OUT: list of chunk dicts with score.
# Example: "minimum attendance?" -> NSUT-BTECH-REG-2019 clause 11.2 among the top-k, plus the best chunk of circular
# SYN-CIRC-ATT-2026 marked "added_by": "supersession", because it supersedes NSUT-BTECH-REG-2019#11.2.
# flow: question -> embedding -> top-k nearest chunks -> add best chunk of each document that supersedes a found one
# ---------- hybrid search: meaning (embeddings) + rare keywords ----------
# Why: scanned fee notices have 13 programmes whose pages look the same to the embedding ("Tuition Fee ... University
# Fee ..."); the word that tells them apart ("B.Tech", "M.Tech", "2025-26") is a keyword. Measured on our 20 eval
# questions + 8 scanned-PDF questions: weight 0 -> 15/20 + 5/8 in top 5; weight 0.2 -> 16/20 + 8/8.
HYBRID_POOL = 25          # embedding candidates looked at before re-ranking
KW_WEIGHT = 0.2           # final order = cosine score + 0.2 x keyword match (0..1); "score" itself stays the cosine
_KW_STOP = set("what which when where with that this from have shall will your there their about would could should "
               "does the and for are is in of to a an my me i do how can per".split())


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())        # OCR glues words ("Bachelorof"), so match without spaces


# IN: question + candidate chunks  ->  OUT: same chunks, best first by (cosine + KW_WEIGHT x keyword match).
# keyword match = share of the question's words found in the chunk, each word weighted by how RARE it is among the
# candidates (idf): "B.Tech" on 2 of 25 pages counts a lot, "fee" on all 25 counts almost nothing.
def _keyword_rerank(query: str, cands: list[dict]) -> list[dict]:
    words = {w for w in re.findall(r"[a-z0-9][a-z0-9.\-]*[a-z0-9]", query.lower())
             if w not in _KW_STOP and (len(w) > 2 or any(ch.isdigit() for ch in w))}
    if not words or not cands:
        return cands
    texts = [_squash(c["text"] + " " + str(c.get("title", ""))) for c in cands]   # title says "Session 2025-26"
    idf = {w: math.log(1 + len(cands) / (1 + sum(_squash(w) in t for t in texts))) for w in words}
    total = sum(idf.values()) or 1.0
    for c, t in zip(cands, texts):
        c["kw"] = round(sum(idf[w] for w in words if _squash(w) in t) / total, 3)
    return sorted(cands, key=lambda c: -(c["score"] + KW_WEIGHT * c["kw"]))


def search(query: str, k: int, where: dict | None = None) -> list[dict]:
    """Top-k chunks with metadata + cosine similarity score, plus chunks of any document that
    explicitly supersedes a found document/clause (so precedence can see both sides)."""
    col = _collection()
    # Empty index (nothing ingested yet) -> no results.
    if col.count() == 0:
        return []
    # Turn the question into an embedding (same model as the chunks, so the numbers are comparable).
    q = embed([query])
    # Ask ChromaDB for the HYBRID_POOL nearest chunks (never more than it holds), then keep the best k after the
    # keyword re-rank below. where = optional filter like {"doc_id": "..."}.
    res = col.query(query_embeddings=q, n_results=min(max(k, HYBRID_POOL), col.count()), where=where)
    # ChromaDB answers with lists of lists (one inner list per question; we sent 1 question, so take [0]).
    # zip pairs each text with its metadata and distance; _to_chunk turns each triple into a result dict.
    found = [_to_chunk(d, m, dist) for d, m, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])]
    found = _keyword_rerank(query, found)[:k]

    # pull in superseding documents (e.g. a circular that replaces clause 11.2) even if they ranked lower
    # seen = (doc, section) pairs already in the results (to avoid duplicates). found_docs = doc ids already found.
    seen = {(c["doc_id"], c["section"]) for c in found}
    found_docs = {c["doc_id"] for c in found}
    # Check every registered document: does it supersede something we found?
    for src in list_sources():
        # Its targets: "NSUT-BTECH-REG-2019#11.2;X-DOC" -> ["NSUT-BTECH-REG-2019#11.2", "X-DOC"] (empty pieces dropped).
        targets = [t for t in src.get("supersedes", "").split(";") if t]
        # Skip it if it is already in the results, or if none of its targets (doc id part before "#") was found.
        if src["doc_id"] in found_docs or not any(t.split("#")[0] in found_docs for t in targets):
            continue
        # Fetch its single best-matching chunk for this question (filter: only that document).
        extra = col.query(query_embeddings=q, n_results=1, where={"doc_id": src["doc_id"]})
        for d, m, dist in zip(extra["documents"][0], extra["metadatas"][0], extra["distances"][0]):
            # Add it unless that exact (doc, section) is already there, and mark why it was added.
            if (m["doc_id"], m["section"]) not in seen:
                found.append({**_to_chunk(d, m, dist), "added_by": "supersession"})
    # Main hits + supersession extras. app/precedence.py then decides which rule wins.
    return found


# IN: nothing  ->  OUT: number of chunks stored in ChromaDB, or -1 if ChromaDB cannot be opened.
# WHY: scripts/ingest_all.py prints it as a check; -1 instead of a crash makes a broken index easy to spot.
def vector_count() -> int:
    try:
        return _collection().count()
    except Exception:
        return -1


# IN: doc_id + section (like "11.2" or "9.5 Table 5")  ->  OUT: page number where that clause starts, or None.
# Example: section_page("NSUT-BTECH-REG-2019", "11.2") -> the page saved in clause 11.2's chunk metadata.
def section_page(doc_id: str, section: str) -> int | None:
    """Page number where a clause starts (for citations of rule clauses that were not in the retrieved chunks)."""
    try:
        sec = str(section).split()[0]                       # "9.5 Table 5" -> "9.5"
        # Find one chunk whose metadata has BOTH this doc_id AND this section ($and = all conditions must match).
        got = _collection().get(where={"$and": [{"doc_id": doc_id}, {"section": sec}]}, limit=1)
        # Found -> its page number. Not found -> None.
        return int(got["metadatas"][0]["page"]) if got["ids"] else None
    # Any error (e.g. ChromaDB not ready) -> None, so the citation just has no page instead of crashing the answer.
    except Exception:
        return None
