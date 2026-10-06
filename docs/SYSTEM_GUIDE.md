# System guide — how the assistant works, in plain words

For teammates: read this once top to bottom, then go deep on the files you own. Judges ask every member about **their
own part and the whole system** (problem statement 9.1 / 9.4), and may ask for a small live change.

---

## 1. The whole system in 60 seconds (everyone must be able to say this)

> "It's one fixed LangGraph workflow with 7 steps. **Code** checks who is asking — identity only from the X-Student-Id
> header — and refuses other students' data before any AI runs. The **AI** only routes the question. We **search**
> ChromaDB for the NSUT clauses, then **code** applies HCL's precedence policy: in force on the as_of_date, right
> programme and batch, explicit supersession by level 1–2 documents, then authority, then recency, else conflict_flagged.
> For personal questions, **code tools** read SQLite and take every threshold from the rule registry, which points to the
> clause it came from. The **AI writes the sentence** only from those sources and tool results. Finally **code** picks the
> answer_type, keeps only citations that were really retrieved, and saves an audit record with a trace_id."

Three things to repeat in every answer: **code decides, AI words** · **every threshold traces to a clause** ·
**the date matters** (as_of_date).

---

## 2. Words you will hear (plain meaning)

| Word | Plain meaning | Where in our project |
|---|---|---|
| RAG | look things up in documents first, then let the AI answer only from what was found | retrieve + compose steps |
| Chunk | one small piece of a document; ours = one numbered clause (e.g. "11.2") | `app/retrieval.py → chunk_pages` |
| Embedding | a list of 384 numbers describing a text's meaning; similar meaning → similar numbers | `all-MiniLM-L6-v2` |
| Vector store | a database that finds chunks with similar meaning | ChromaDB in `storage/chroma` |
| OCR | reading text out of a scanned image | `app/ocr.py` (rapidocr) for the fee notices |
| Precedence | which document wins when two disagree | `app/precedence.py` (Annex A) |
| Supersede | "this document replaces that clause" | `supersedes` column, e.g. `NSUT-BTECH-REG-2019#11.2` |
| Authority level | rank of a document: 1 regulation … 4 FAQ, 5 unofficial | Source Register |
| Rule registry | table of every threshold (75%, 60%, 30%…) with its clause | `data/rules.csv` → SQLite |
| Tool | a plain Python function the flow calls for exact answers | `app/tools.py` |
| answer_type | label of what kind of answer it is | set in `finalize` |
| trace_id / audit | receipt number of an answer / what happened inside, without the AI's private reasoning | `app/audit.py`, `GET /audit/{id}` |
| Header | hidden label sent with a request, like showing an ID card | `X-Student-Id` |
| Mock mode | fake AI so the rest can be tested without a model | `LLM_PROVIDER=mock` |

---

## 3. One request, step by step (S1002 asks "Am I eligible to appear in the end-semester exam for Data Structures?", as of 2026-10-06)

| Step | File / function | What happens here |
|---|---|---|
| 0 | `app/main.py → ask` | FastAPI receives the request; Pydantic checks the body (an empty question → 422) |
| 1 | `app/graph.py → authorise` | code: no other `S####` in the text, no other student's name, header S1002 exists in `students` → allowed |
| 2 | `classify` | LLM returns `{"category": "eligibility", "course_hint": "Data Structures"}` (JSON mode, 1 retry) |
| 3 | `retrieve` → `retrieval.search` | question → embedding → top-5 chunks (Regulations 11.x, circular §1, FAQ Q1) + any document that supersedes a found clause |
| 4 | `apply_policy` → `precedence.resolve` | drops chunks scoring under 0.50; circular supersedes 11.2 (step 2); FAQ 65% overridden by authority (step 3) |
| 5 | `run_tools` → `tools.find_course` + `check_exam_eligibility` | "Data Structures" → CS201; attendance 31/40 = 77.5%; rule in force = ATT-MIN-02 (80%, circular) via `precedence.get_rule_in_force`; floor ATT-FLOOR-01 60% → **ELIGIBLE_ONLY_WITH_RELAXATION** |
| 6 | `compose` | LLM gets the sources (fenced as untrusted data) + the tool result and writes one short answer as JSON |
| 7 | `finalize` | code: tool used → `calculated`; citations = the clauses of the rules the tool used (circular §1, Regulations 11.6); audit saved (no question text, no names) |

---

## 4. Files, what they do, and who owns them

| File | What it does | Owner |
|---|---|---|
| `app/config.py` | all settings from `.env` (provider, model, paths, top-k) | shared |
| `app/schemas.py` | the HCL API shapes (AskRequest, AskResponse, Citation, SourceMeta — lenient so judges' metadata never 422s) | shared |
| `app/db.py` | SQLite tables exactly as Annex C (+ audit_log), with CHECK constraints (attended ≤ held, ID format) | Suryansh (B) |
| `app/tools.py` | attendance %, 3-tier exam eligibility, pass/fail by 12.7 + Table 5, backlogs, course lookup | Suryansh (B) |
| `scripts/generate_data.py` | LLM writes students → Pydantic validates → code plants edge cases → CSVs | Suryansh (B) |
| `scripts/validate_data.py` | checks the CSVs (ranges, totals, result vs marks, references) | Suryansh (B) |
| `scripts/load_students.py` | **the judges' loader**: CSVs → SQLite, prints every rejected row with a reason | Suryansh (B) |
| `app/retrieval.py`, `app/ocr.py` | PDF text / OCR → clause chunks → embeddings → ChromaDB; search; Source Register table | Suryansh (A) |
| `scripts/ingest_all.py` | ingests every document in `data/source_register.csv` once | Suryansh (A) |
| `eval/run_eval.py` | evaluation: 6 metrics, resumable, retrieval-only config comparison | Suryansh (A) |
| `app/graph.py`, `app/prompts.py` | the 7-step LangGraph workflow and the two LLM prompts | Geetarth reviews / extends (v1 built on Suryansh's laptop) |
| `app/precedence.py` | Annex A in code, for chunks and for rule-registry rows | Geetarth reviews / extends (v1 built on Suryansh's laptop) |
| `app/rule_extract.py` | on `/ingest`, LLM proposes rule rows; kept only if the number appears verbatim in the clause | Geetarth reviews / extends |
| `app/main.py`, `app/llm.py`, `app/audit.py` | 5 endpoints (never a 500 on /ask), Ollama/Groq/mock switch with fallback, audit table | Geetarth (C) |
| `ui/streamlit_app.py` | chat, answer-type badges, citations, tools/audit panels, ingest form, Source Register | Geetarth (C) |
| `Dockerfile`, `docker-compose.yml` | packaging | Geetarth (C) — to build |
| `data/rules.csv`, `data/source_register.csv`, `data/docs/SYN-*.md` | rule rows, document catalogue, 2 synthetic docs | Neetu (D) |
| `eval/testset.json`, `README.md`, `docs/AI_USAGE.md`, `docs/TEAM_CONTRIBUTION.md` | evaluation questions, documentation | Neetu (D) |
| `tests/` | 33 tests: precedence (incl. HCL's worked example), graph/API, tools | each owner |

---

## 5. Likely judge questions (short answers)

**Everyone**
- *Why not multiple agents?* Every step except routing and wording is deterministic code; agents would add failure points and latency without a requirement needing them. The brief says the simplest design that meets the requirements scores highest.
- *How do you stop hallucination?* Answers only from retrieved, fenced sources; code removes any citation that wasn't retrieved; no evidence above the score floor → not_found without asking the LLM; numbers only from tools.
- *Where is the API key?* In `.env`, which is git-ignored; never in code.
- *What if Ollama is down?* `llm.chat` falls back to Groq automatically; `/health` shows which provider is active.

**Suryansh (data + search)**
- *Why chunk by clause?* So a citation can say "section 11.2, page 18" and a circular can supersede exactly one clause.
- *How did you use AI for the data?* Prompt saved verbatim; Pydantic validates every response (retry on failure); code, not the LLM, derives totals, results and backlogs and plants the edge cases.
- *What did the LLM get wrong?* It clustered weak students — 5 students fail all 6 courses; we disclosed it in the data card.
- *A bug you found?* Exam sessions were sorted as text, so "2026-JUL" came before "2026-MAY" and a re-registration pass didn't clear the backlog — a test caught it; fixed with a (year, month) sort.
- *Why MiniLM?* Tied with bge-small on hit@3 (11/12 on our dev set); smaller and faster; both separate unanswerable questions poorly, so not_found also uses the LLM's signal.

**Geetarth (flow + precedence + API)**
- *Walk through Annex A on the worked example:* regulation 75% (L1), circular 80% supersedes the clause (L2), FAQ 65% (L4); on 2026-10-06 → 80% by step 2, FAQ overridden by step 3; on 2026-07-15 → 75%, circular reported as upcoming.
- *Why can't a department notice supersede the regulation?* Step 2 only accepts explicit supersession from level 1–2 documents.
- *How does a judge's new circular change eligibility without a code change?* `/ingest` indexes it and extracts rule rows (value must appear verbatim); `get_rule_in_force` picks the winning row by Annex A, so the tool's threshold changes.
- *Who decides answer_type?* Code in `finalize`, never the LLM.

**Neetu (content + evaluation)**
- *How is the test set built?* ≥ 20 questions with the brief's mix (unanswerable, conflicts, personal via tools, other-student attempts, multi-step), each with expected answer, answer_type and source checked against the PDF page.
- *How are answers scored?* Exact match on answer_type and on every number/date; citation accuracy = expected document + section cited; no LLM judge.

---

## 6. A small live change to rehearse (one each)

- **Suryansh:** add a check in `scripts/validate_data.py` that `cgpa` has at most 2 decimals; run it → 0 violations.
- **Geetarth:** change `MIN_SCORE` in `app/graph.py` from 0.50 to 0.55 and show the Antarctica question still returns not_found and the attendance question still answers.
- **Neetu:** add a rule row (e.g. a placement CGPA cut-off) to `data/rules.csv`, run `python -m scripts.load_rules`, and show it in the registry.
