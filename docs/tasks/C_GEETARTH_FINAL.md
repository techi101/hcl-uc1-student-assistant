# Geetarth — FINAL task list (from ~14:30 to freeze)

You own: **the flow + precedence** (review, test, extend), **API/UI**, **Docker**, and **the demo laptop**.
Commit everything from YOUR GitHub account. Priority order — if short on time, drop from the bottom.

Paste this into your Claude Code inside the repo folder:

> Read CLAUDE.md, README.md, docs/SYSTEM_GUIDE.md, docs/PROBLEM_STATEMENT.md (sections 3, 5, 6, 8, 9, Annex A) and docs/tasks/C_GEETARTH_FINAL.md. Then do the steps in order. After each step run it, show me the REAL output, and commit + push only the files the step names. Never say "done" without real output. Never commit .env, storage/ or test_students/.
>
> **Step 1, run it locally (15 min).** `git pull`; `pip install -r requirements.txt rapidocr-onnxruntime python-docx`; `copy .env.example .env` and add my own GROQ_API_KEY; then:
> `python -m scripts.ingest_all` (the first run does OCR on the scanned PDFs, a few minutes),
> `python -m scripts.load_students --dir data/students_csv --rules data/rules.csv`,
> `python -m pytest -q` (expect 33 passed). Nothing to commit.
>
> **Step 2, local LLM speed = demo decision (10 min).** `winget install Ollama.Ollama`; `ollama pull qwen2.5:7b-instruct`; `ollama ps` (GPU or CPU?); `python -m scripts.bench_llm qwen2.5:7b-instruct`. Start `uvicorn app.main:app --port 8000` and time:
> `curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" -H "X-Student-Id: S1002" -d "{\"question\":\"Am I eligible to appear in the end-semester exam for Data Structures?\",\"as_of_date\":\"2026-10-06\"}"`
> Expected: answer_type `calculated`, result ELIGIBLE_ONLY_WITH_RELAXATION. Add ONE row to docs/MODEL_CHOICE.md (laptop + GPU, bench median, full /ask seconds). Rule: 20 s or less → demo with LLM_PROVIDER=ollama; slower → LLM_PROVIDER=groq, disclosed in the README. Commit: docs/MODEL_CHOICE.md.
>
> **Step 3, Docker (required deliverable) (30 min).**
> - `Dockerfile`: python:3.12-slim; `pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt rapidocr-onnxruntime python-docx`; pre-download `sentence-transformers/all-MiniLM-L6-v2` at build time; copy the repo.
> - `.dockerignore`: .env, storage/, .git, __pycache__.
> - `docker-compose.yml`:
>   - `api`: `sh -c "python -m scripts.ingest_all; python -m scripts.load_students --dir data/students_csv --rules data/rules.csv; uvicorn app.main:app --host 0.0.0.0 --port 8000"`, port 8000, healthcheck on /health.
>   - `ui`: `streamlit run ui/streamlit_app.py --server.port 8501 --server.address 0.0.0.0`, env API_URL=http://api:8000, port 8501.
>   - Both services: env_file .env; OLLAMA_URL=http://host.docker.internal:11434; extra_hosts host.docker.internal:host-gateway; volumes ./storage:/app/storage and ./data:/app/data.
> - Verify: `docker compose up --build` → `curl localhost:8000/health` → the Step 2 curl works → http://localhost:8501 opens.
> - Commit: Dockerfile, .dockerignore, docker-compose.yml.
>
> **Step 4, own the flow and precedence (30 min).** Explain to me, block by block, `app/graph.py` (the 7 nodes and the conditional edges) and `app/precedence.py` (resolve, pick_rule, in_scope). Then add tests in a NEW file `tests/test_flow_extra.py` (LLM_PROVIDER=mock where the LLM isn't needed):
> - (a) a level-3 notice cannot supersede a regulation;
> - (b) the 2026-07-15 vs 2026-10-06 minimum-attendance rule via `precedence.get_rule_in_force` gives 75 vs 80;
> - (c) an ECE student never gets the CSE FAQ's 65%;
> - (d) "How do I apply for re-registration?" is not refused;
> - (e) a personal question for a header that isn't in the DB is refused.
> Run `pytest -q`. Commit: tests/test_flow_extra.py.
>
> **Step 5, judge rehearsal + runbook (20 min).**
> - (a) `python -m scripts.live_ingest_check` (unseen circular → /ingest → supersedes 11.6 from 2026-09-01 → rule row extracted; it cleans up).
> - (b) Make `test_students/` with 2 students S9001 and S9002 (Annex C columns) plus attendance and courses for course JDG101; `python -m scripts.load_students --dir test_students`; ask /ask as S9001. Do NOT commit test_students/.
> - (c) Write `docs/DEMO_RUNBOOK.md`:
>   - how to start (local and Docker);
>   - the 4 demo questions in order, each with its header and as_of_date: cited policy "What is the minimum attendance required to appear for end-semester exams?" on 2026-10-06 → 80% (circular); eligibility S1002 Data Structures → relaxation; not_found "What is the scholarship for studying in Antarctica?"; conflict = the same attendance question on 2026-07-15 → 75% + upcoming notice;
>   - how to ingest a judge document (UI Documents tab + curl);
>   - how to load judge students;
>   - what to do if Ollama is slow (LLM_PROVIDER=groq in .env, restart).
> - Commit: docs/DEMO_RUNBOOK.md.
>
> **Step 6 (only if time), `POST /admin/rules`** in app/main.py: JSON body with the rule_registry columns, validated with Pydantic; source_doc_id must exist in GET /sources; insert or replace; return the row. Add one test. Commit: app/main.py, tests.
>
> Done when: Steps 1–5 are pushed from MY account, and the demo runs on this laptop.

## You will be asked (prepare short answers — see docs/SYSTEM_GUIDE.md section 5)
Walk a request through the 7 steps · why one fixed graph, not agents · Annex A on HCL's worked example · why a level-3 notice can't supersede · how a judge's new circular changes eligibility with no code change · who decides answer_type (code) · what happens if Ollama is down (Groq fallback, /health shows it).

## Live change to rehearse
Change `MIN_SCORE` in app/graph.py 0.50 → 0.55; show Antarctica still `not_found` and the attendance question still answers; change back.
