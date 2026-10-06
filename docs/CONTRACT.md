# CONTRACT — the shapes everyone codes against

Agree these first; then 3 people can build in parallel (use fakes until the real piece lands).

## 1. Flow (one fixed LangGraph workflow, `app/graph.py`)
```
POST /ask (question, as_of_date, X-Student-Id)
  → classify        LLM → {category: policy|procedure|personal|eligibility|multi_step|other,
                           course_hint, target_student_id_in_text}
  → authorise       code: personal/eligibility w/o header → refused; asks about other student → refused
  → retrieve        Chroma top-k chunks (metadata = Source Register fields + section + page)
  → precedence      code (Annex A): filter applicable on as_of_date + scope → supersession → authority → recency → conflict
  → tools           code: get_student / get_attendance / get_results / check_exam_eligibility / ... (thresholds from rule_registry)
  → compose         LLM writes answer+explanation ONLY from given chunks + tool outputs (untrusted-data fenced)
  → finalize        code: answer_type, citations (only retrieved chunks), audit record, trace_id
```

## 2. Python interfaces (owner in brackets)

`app/retrieval.py` [A]
- `ingest_file(path: str, meta: dict) -> dict` → `{"doc_id", "chunks_indexed", "status"}`; also appends row to Source Register
- `search(query: str, k: int) -> list[Chunk]` where Chunk =
  `{"text", "doc_id", "title", "section", "page", "version", "effective_from", "effective_to", "authority_level", "doc_type", "supersedes", "scope_programmes", "scope_batches", "score"}`

`app/precedence.py` [A]
- `resolve(chunks: list[Chunk], as_of_date: str, student: dict | None) -> dict` →
  `{"applicable": [Chunk], "excluded_future": [Chunk], "superseded": [Chunk], "conflicts": [str], "decision": str, "unresolved": bool}`

`app/tools.py` [B]  (all read SQLite; thresholds from rule_registry)
- `get_student(student_id) -> dict | None`
- `get_attendance(student_id, course_code) -> {"classes_held", "classes_attended", "attendance_pct"}`
- `get_results(student_id, course_code=None) -> list[dict]`
- `get_rule(parameter, as_of_date, programme, batch_year) -> dict | None`  (rule_registry row in force)
- `check_exam_eligibility(student_id, course_code, as_of_date) -> {"result": "ELIGIBLE"|"NOT_ELIGIBLE", "rule_id", "value", "actual", "source_doc_id", "source_section"}`
- (add) `check_supplementary_eligibility`, `check_placement_eligibility` — same output shape
- `find_course(text, programme) -> list[course]`  (for "Data Structures" → CS201; several → clarification_needed)

`app/llm.py` [C]
- `chat(system: str, user: str, json_mode: bool=False) -> {"text", "model", "tokens", "ms"}` — provider from `.env` (ollama | groq | mock)

`app/audit.py` [C]
- `save(record: dict) -> None`, `get(trace_id) -> dict | None`  (SQLite table `audit_log`, no personal data beyond student_id)

## 3. HTTP API (fixed by HCL — do not change names) — `app/main.py` [C]
| Endpoint | In | Out |
|---|---|---|
| POST /ask | header `X-Student-Id` (optional), JSON `{question, as_of_date?}` | AskResponse (`app/schemas.py`) |
| POST /ingest | multipart: `file` + `metadata` (JSON string, Annex B fields) | `{doc_id, chunks_indexed, status}` |
| GET /health | – | `{api, vector_store, sqlite, llm}` |
| GET /audit/{trace_id} | – | audit record |
| GET /sources | – | list of Source Register rows |
| CLI loader | `python scripts/load_students.py --dir test_students/` | prints rows loaded / rejected |

answer_type ∈ retrieved_fact | calculated | not_found | clarification_needed | refused | conflict_flagged
not_found message (exact): `I could not find this information in the authorised university sources.`

## 4. Files
| Path | What | Owner |
|---|---|---|
| app/retrieval.py, app/precedence.py | ingest, Chroma search, Annex A policy | A |
| app/db.py, app/tools.py, scripts/generate_data.py, scripts/validate_data.py, scripts/load_students.py, prompts/ | SQLite schema, tools, synthetic data kit | B |
| app/main.py, app/graph.py, app/llm.py, app/audit.py, app/schemas.py, ui/, Dockerfile, docker-compose.yml | API, workflow, UI, packaging | C |
| data/docs/, data/source_register.csv, data/rules.csv, eval/testset.json, README.md, docs/ | documents, register, rule rows, eval set, docs | D |
| tests/ | each owner tests their own module | all |
| app/config.py | settings | shared — announce changes |
