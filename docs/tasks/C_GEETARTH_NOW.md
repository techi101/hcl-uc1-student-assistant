# Geetarth — NOW (from 14:05): run the system on your laptop, Docker, local-LLM speed, judge rehearsal

The flow, API, UI, tools, data and precedence are already built and pushed (33 tests pass). Your job: make it run
**on your laptop and in Docker**, measure the local model there, and rehearse exactly what the judges will do.

Paste this into your Claude Code inside the repo folder:

> Read CLAUDE.md, docs/CONTRACT.md, docs/PROBLEM_STATEMENT.md (sections 5, 6, 8, 9.1) and docs/tasks/C_GEETARTH_NOW.md, then do the steps below in order. After each step run it, show me the REAL output, and commit + push only the files I own: Dockerfile, docker-compose.yml, .dockerignore, docs/DEMO_RUNBOOK.md, and one new row in docs/MODEL_CHOICE.md. Do not edit app/, scripts/, tests/ or ui/; if something there is broken, tell me the exact error and I'll pass it to Suryansh.
>
> **Step 1, local setup (15 min).** `git pull`; `pip install -r requirements.txt rapidocr-onnxruntime python-docx`; copy `.env.example` to `.env` and put my own `GROQ_API_KEY` in it; then run:
> `python -m scripts.ingest_all` (the first run does OCR on 4 scanned PDFs and takes a few minutes),
> `python -m scripts.load_students --dir data/students_csv --rules data/rules.csv`,
> `python -m pytest -q` (expect 33 passed).
>
> **Step 2, local LLM speed on this laptop (10 min).** Install Ollama (`winget install Ollama.Ollama`), run `ollama pull qwen2.5:7b-instruct`, then `ollama ps` (does it say GPU?), then `python -m scripts.bench_llm qwen2.5:7b-instruct`. Then time one full answer: start `uvicorn app.main:app --port 8000` and run
> `curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" -H "X-Student-Id: S1002" -d "{\"question\":\"Am I eligible to appear in the end-semester exam for Data Structures?\",\"as_of_date\":\"2026-10-06\"}"`.
> Expected answer_type is `calculated`, result ELIGIBLE_ONLY_WITH_RELAXATION (77.5% vs 80%). Add one row to docs/MODEL_CHOICE.md: laptop name + GPU, bench median, and the full /ask latency.
> Decision rule: if one full answer takes 20 s or less, the demo uses Ollama (LLM_PROVIDER=ollama). If it takes longer, the demo uses LLM_PROVIDER=groq, and the README discloses it as the configured fallback.
>
> **Step 3, Docker (30 min).**
> - `Dockerfile`: python:3.12-slim. `pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt rapidocr-onnxruntime python-docx`. Pre-download the embedding model at build time with `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"`. Copy the repo.
> - `.dockerignore`: `.env`, `storage/`, `.git`, `__pycache__`.
> - `docker-compose.yml`, two services, both with `env_file: .env`, `OLLAMA_URL=http://host.docker.internal:11434`, `extra_hosts: ["host.docker.internal:host-gateway"]`, and volumes `./storage:/app/storage` and `./data:/app/data`.
>   - `api`: command `sh -c "python -m scripts.ingest_all; python -m scripts.load_students --dir data/students_csv --rules data/rules.csv; uvicorn app.main:app --host 0.0.0.0 --port 8000"`, port 8000:8000, healthcheck on /health.
>   - `ui`: command `streamlit run ui/streamlit_app.py --server.port 8501 --server.address 0.0.0.0`, env `API_URL=http://api:8000`, port 8501:8501, depends_on api.
> - Verify: `docker compose up --build`, then `curl localhost:8000/health` shows all components ok, then the same /ask curl as Step 2 works, then http://localhost:8501 loads.
>
> **Step 4, rehearse the judges' 10 minutes (15 min).**
> - (a) `python -m scripts.live_ingest_check`: uploads an unseen circular through POST /ingest, checks it is searchable, that it supersedes clause 11.6 from 2026-09-01, and that a rule row was extracted; it cleans up after itself.
> - (b) Make a folder `test_students/` with a students.csv containing 2 students S9001 and S9002 (Annex C columns) plus their attendance.csv and courses.csv using a course code JDG101. Run `python -m scripts.load_students --dir test_students`, then ask /ask as S9001. Do NOT commit test_students/, because S9xxx and JDG* are reserved for the judges.
> - Write `docs/DEMO_RUNBOOK.md`: how to start everything on this laptop (with and without Docker); the 4 demo questions with their header and as_of_date (cited policy: "What is the minimum attendance required to appear for end-semester exams?" on 2026-10-06 → 80%, circular; eligibility: S1002 Data Structures → relaxation; not_found: "What is the scholarship for studying in Antarctica?"; conflict: the same minimum-attendance question on 2026-07-15 → 75% plus the upcoming-circular notice); how to ingest a judge document from the UI's Documents tab and with curl; how to load judge students; what to do if Ollama is slow (set LLM_PROVIDER=groq in .env and restart).
>
> Done when: pytest passes on my laptop; `docker compose up` serves /health and a correct /ask; the bench numbers are in MODEL_CHOICE.md; DEMO_RUNBOOK.md is committed from MY GitHub account.
