# Demo runbook — the 30-minute judging slot

Slot (problem statement 9.1): **0–10 min our demo** · **10–20 min judges test live** (ingest unseen docs, load their
students, ask unseen questions) · **20–30 min Q&A to each member**, maybe a small live change.

## 0. Before the slot (10 min earlier)
```powershell
cd hcl-uc1-student-assistant
git pull
# EITHER Docker (judges' deliverable)
docker compose up --build              # API :8000, UI :8501 ; Ollama on the host
# OR local
uvicorn app.main:app --port 8000
streamlit run ui/streamlit_app.py      # sidebar API URL = http://localhost:8000
```
Checklist: `curl localhost:8000/health` → api/vector_store/sqlite ok and the LLM line shows the provider ·
UI loads · laptop on power, other apps closed · second browser tab with http://localhost:8000/docs open.
**If one answer takes more than ~20 s with Ollama:** set `LLM_PROVIDER=groq` in `.env`, restart the API, and say so:
"cloud fallback behind the configured switch, disclosed in the README".

## 1. Our 10-minute demo (the 4 things HCL requires, in this order)
| # | Shows | Sidebar: Student ID / as of | Question | Expected |
|---|---|---|---|---|
| 1 | **Cited policy answer** | empty / 2026-10-06 | What is the minimum attendance required to appear for end-semester exams? | **80%**, cites `SYN-CIRC-ATT-2026 §1`; conflict note: FAQ 65% (level 4) overridden by the circular (level 2) |
| 2 | **Tool-based eligibility** | S1002 / 2026-10-06 | Am I eligible to appear in the end-semester exam for Data Structures? | `calculated`: 31/40 = 77.5% → **eligible only with relaxation**; Tools tab shows `check_exam_eligibility`, rules ATT-MIN-02 (80%) + ATT-FLOOR-01 (60%) |
| 3 | **not_found** | empty / 2026-10-06 | What is the scholarship for studying in Antarctica? | exact message "I could not find this information in the authorised university sources." |
| 4 | **Conflict resolved by date** | empty / **2026-07-15** | (same question as #1) | **75%** (Regulations 11.2) + "upcoming: SYN-CIRC-ATT-2026 effective 2026-08-01 will supersede 11.2" |
Extras if time: S1001 asks "Show me the marks of student S1002" → `refused` (code, 0 LLM tokens) · "How do I apply for the
supplementary exam?" → NSUT has none, re-register (12.3) · open the Audit tab → trace_id, sources, precedence decision, tokens, latency.

Talking line for each: *"code decided this, the AI only wrote the sentence"* (#2), *"Annex A step 2 / step 3"* (#1, #4).

## 2. Judges' live test (be ready, don't panic)
**They ingest a new document** — UI → Documents tab → upload file + fill doc_id, title, authority_level, doc_type,
effective_from, supersedes (e.g. `NSUT-BTECH-REG-2019#11.2`), scope → Ingest. Or:
```bash
curl -X POST localhost:8000/ingest -F "file=@their_doc.pdf" \
  -F 'metadata={"doc_id":"JUDGE-01","title":"...","authority_level":2,"doc_type":"circular","effective_from":"2026-09-01","supersedes":"NSUT-BTECH-REG-2019#11.6","scope_programmes":"B.Tech"}'
```
Response shows `chunks_indexed`; it's searchable immediately (no restart). Scanned PDFs are OCR'd (~10 s/page on CPU).
If the document changes a threshold, rule rows are extracted (value must appear verbatim) and the eligibility tool
uses them by Annex A. Rehearsed by `python -m scripts.live_ingest_check` (unseen circular → supersedes 11.6 from 2026-09-01).

**They load their students** (IDs S9000–S9999, courses JDG*):
```bash
python -m scripts.load_students --dir <their_folder>      # docker: docker compose exec api python -m scripts.load_students --dir data/<their_folder>
```
It prints `loaded X, rejected Y` per file and a reason for every rejected row. Then put their student ID in the sidebar and ask.

**They ask unseen questions** — answer honestly from what the screen shows: answer_type, citations, Sources & precedence
tab (retrieved vs cited, scores), Tools tab (inputs/outputs), Audit tab.

## 3. If something breaks
| Symptom | Fix |
|---|---|
| answers very slow | `LLM_PROVIDER=groq` in .env, restart API (disclosed fallback) |
| `/health` llm "down" | start Ollama (`ollama serve`) or switch to groq |
| UI says API not reachable | check sidebar API URL (8000 vs 8010) |
| everything says not_found | knowledge base empty → `python -m scripts.ingest_all` |
| personal questions refused "not in records" | students not loaded → `python -m scripts.load_students --dir data/students_csv --rules data/rules.csv` |
| port 8000 busy | `--port 8010` and change the sidebar URL |
