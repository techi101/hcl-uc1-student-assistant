# AI-usage disclosure

HCL's rules allow and encourage AI coding assistants, provided we disclose how we used them and can explain every line. This file lists what was generated with AI, and how each part was checked.

## Tools used

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic, Claude Opus) | Writing most of the Python code, tests, docs and task files, from our design decisions. Several Claude Code sessions ran in parallel on Suryansh's laptop (build, review, evaluation, documentation). |
| **Groq** `openai/gpt-oss-120b` (temperature 0.7, JSON mode) | Generating the synthetic student data (4 calls, 32 students). Prompt verbatim in `prompts/generate_students.txt`; details in `docs/DATA_CARD.md`. |
| **qwen2.5:7b-instruct via Ollama** (local) | Runtime only: classifying the question and writing the final sentence. It never decides eligibility, numbers, citations or answer_type. |
| **Groq** (same model, behind `LLM_PROVIDER=groq`) | Configured fallback when the local model is too slow. `/health` reports which provider is actually in use. |

## What was generated, and where it was built

Most of the code was generated with Claude Code **on Suryansh's laptop**, which is why most commits come from one account. Omkar left the team mid-day, so part B moved to Suryansh.

| Part | Files | Built with AI on | Owner who reviewed / must explain it |
|---|---|---|---|
| A: ingestion, OCR, search, precedence, live rule extraction | `app/retrieval.py`, `app/ocr.py`, `app/precedence.py`, `scripts/ingest_all.py`, `scripts/live_ingest_check.py` | Suryansh's laptop | Suryansh |
| B: synthetic data kit, validator, judges' loader, tools | `scripts/generate_data.py`, `scripts/validate_data.py`, `scripts/load_students.py`, `app/tools.py`, `docs/DATA_CARD.md` | Suryansh's laptop | Suryansh |
| Core workflow, API, audit, UI | `app/graph.py`, `app/main.py`, `app/audit.py`, `ui/streamlit_app.py` | Suryansh's laptop | Geetarth (C) |
| Rules, synthetic docs, source register, eval set + report | `data/rules.csv`, `data/docs/SYN-*.md`, `data/source_register.csv`, `eval/` | Suryansh's laptop | Neetu (D) |
| Docker, demo runbook | `Dockerfile`, `docker-compose.yml`, `docs/DEMO_RUNBOOK.md` | see git history | Geetarth (C) |

## How we verified AI-generated work

- **Tests:** `pytest` (33+ tests), covering HCL's own Annex A worked example, the 3-tier attendance rule (exactly 80%, 77.5%, 55%), the rule-change-without-code test (changing a `rule_registry` row changes eligibility), and loader rejects.
- **Data validator:** `scripts/validate_data.py` enforces the schema and logic (attended ≤ held, total = internal + external, result consistent with the pass rules) and was shown to catch deliberately planted bad rows. Output: `data/validation_report.txt`.
- **Facts checked by hand against the source PDFs:** every threshold in `data/rules.csv`, and every expected answer in `eval/testset.json` (Regulations 7.2, 7.9, Table 5, 11.2–11.7, 12.3, 12.7, 15.1; DHTESS income limit in the OCR text).
- **Model choice measured, not assumed:** `scripts/bench_llm.py` gave 5/5 routing for qwen2.5:7b vs 2/5 for 3B (`docs/MODEL_CHOICE.md`).
- **Retrieval measured:** MiniLM 80% vs bge-small 50–55% hit rate (`eval/retrieval_comparison.md`).
- **Personal-data scan:** all 9 NSUT PDFs and the OCR text scanned for roll numbers, emails, phone numbers and student-list headers: 0 hits. A secret scan of the full git history was clean before the repo was made public.
- **Review fixes we made to AI output:** a false conflict between a superseding circular and other clauses of the regulation; exam-session ordering in the tools; a "supplementary exam" edge case removed because Regulations 12.3 says NSUT has none.

## What the AI got wrong (caught)

- It first proposed a "supplementary exam" data row, which contradicts Regulations 12.3.
- Its first precedence version flagged a false conflict between the 80% circular and unrelated clauses of the Regulations (fixed, with a regression test).
- A draft test question expected the DHTESS scholarship to be in force on 2026-10-06; the register shows both notices expired in 2025 (question re-dated to 2025-11-15).
