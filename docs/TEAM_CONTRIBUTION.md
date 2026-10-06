# Team contribution statement

Team of 3. Omkar Mahabole started with us and left mid-day.
We built with AI coding assistants (see `docs/AI_USAGE.md`). Most code was generated with Claude Code on Suryansh's laptop, so the git history is uneven. Ownership below is split **equally**: one hard file each. It means who **reviews, tests, explains and changes it live** in the Q&A.

| Member | GitHub | Owns (hard · medium · easy) | Live change they can make | Also covers |
|---|---|---|---|---|
| **Suryansh Kumar** | techi101 | **Documents in + evaluation.** Hard: `app/retrieval.py` (ingestion, clause chunking, Chroma search). Medium: `app/rule_extract.py` (live rule extraction on `/ingest`), `eval/testset.json`, `eval/run_eval.py`. Easy: `app/ocr.py`, `scripts/ingest_all.py`, `data/source_register.csv`, the 2 synthetic documents, `eval/retrieval_comparison.md`. | Retrieval-only eval at k=3 vs k=5 | `precedence.resolve` |
| **Geetarth Jain** | Geetarthjain15 | **Workflow + safety + serving + demo laptop.** Hard: `app/graph.py` (the 7-step workflow, code-first authorisation, finalize). Medium: `ui/streamlit_app.py`, `Dockerfile` + `docker-compose.yml`. Easy: `app/main.py`, `app/llm.py`, `app/audit.py`, `app/prompts.py`, `docs/MODEL_CHOICE.md`. | Retrieval threshold `MIN_SCORE` 0.50 → 0.55 | `tools.check_exam_eligibility` |
| **Neetu** | neetu54 | **Rules + students + paperwork.** Hard: `app/precedence.py` (Annex A on chunks and rule_registry). Medium: `app/tools.py` (3-tier attendance, pass/fail, backlogs), `scripts/generate_data.py`. Easy: `data/rules.csv`, `app/db.py`, `scripts/validate_data.py`, `scripts/load_students.py`, `scripts/load_rules.py`, `samples/`, `docs/AI_USAGE.md`, this file, `docs/DATA_CARD.md`. | Add a `rules.csv` row + `scripts.load_rules` and show eligibility change | `graph.authorise` |

Shared by all: `README.md`, `app/config.py`, `app/schemas.py`, `tests/` (each owner keeps the tests for their files).
All three of us studied the whole system (7 steps, code decides / AI explains, precedence, 3-tier attendance) for the Q&A.

## Declaration of original work

We declare that this submission is our own team's work for the HCLTech Future Ready AI Engineer Hackathon (6 October 2026). We used open-source libraries and AI coding assistants as disclosed in `docs/AI_USAGE.md`. We did not share code with, or copy code from, any other team. No real personal data is used: the student data is synthetic, and the university documents are public NSUT documents.

| Member | Signature | Date |
|---|---|---|
| Suryansh Kumar | ____________ | 06-10-2026 |
| Geetarth Jain | ____________ | 06-10-2026 |
| Neetu | ____________ | 06-10-2026 |
