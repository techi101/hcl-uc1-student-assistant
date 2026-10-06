# TASK A — Suryansh — documents → OCR → clause chunks → ChromaDB, /ingest, precedence (Annex A), evaluation runner

## Owns
`app/retrieval.py`, `app/precedence.py`, `app/ocr.py`, `scripts/ingest_all.py`, `eval/run_eval.py`, `eval/report.md`,
`tests/test_precedence.py`, `tests/test_retrieval.py`, `data/docs/` (real PDFs).

## Steps
1. `ingest_file(path, meta)`: PDF text per page (pypdf); page with < 50 chars → OCR (rapidocr-onnxruntime); drop garbled Hindi legacy-font lines; also accept .md/.txt/.docx.
   Chunk by clause headings (`^\d+(\.\d+)*\s`), fallback ~800 chars with overlap; metadata = Source Register fields + section + page + filename.
   Upsert into Chroma (persistent at storage/chroma, collection `nsut_docs`, cosine); append/replace row in data/source_register.csv. Return {doc_id, chunks_indexed, status}.
2. `scripts/ingest_all.py`: ingest every row of data/source_register.csv once (skip if doc_id already indexed — no re-ingest on restart).
3. `search(query, k)`: embedding search (MiniLM / bge via config), returns chunks with metadata + score (1 - distance).
4. `precedence.py`: `in_scope`, `resolve` (Annex A steps 1–5 on chunks), `pick_rule` (same steps on rule_registry rows joined with register authority + supersedes). Unit tests on the Annex A.3 worked example and our ATT-MIN-01/02/03 rows at as_of 2026-07-15 and 2026-10-06.
5. `extract_rules(doc_id, chunks)` on /ingest: LLM proposes rows for known parameters; accept only if the value appears verbatim in the chunk; insert with source section.
6. `eval/run_eval.py`: runs eval/testset.json through the API, computes the 6 metrics (answer correctness, citation accuracy, abstention accuracy, tool-result correctness, retrieval hit rate@k, p50/p95 latency + LLM calls + tokens), two configs (MiniLM vs bge, or top-k 3 vs 5) → eval/report.md. Resumable, slow-paced for rate limits.
