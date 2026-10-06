"""FastAPI app: the 5 endpoints fixed by HCL (Section 6) + GET /me for the UI sign-in. Owner: C."""
# WHAT THIS FILE IS: the "front door" of the backend. It defines the 5 web addresses that HCL fixed.
# An ENDPOINT is one web address + one method that the server answers, like "POST /ask" or "GET /health".
# The 5 endpoints: POST /ask, POST /ingest, GET /health, GET /audit/{trace_id}, GET /sources.
# Real example: the UI sends POST /ask with body {"question": "What is my attendance in CS201?"}
# and header "X-Student-Id: S1001". This file passes that to graph.run(), which returns the JSON answer.
# FastAPI = the Python web framework that turns these functions into a web server (run by uvicorn).
# json = read the metadata text sent with /ingest. logging = write messages to the server log.
# shutil = copy the uploaded file to disk. threading = run the startup warm-up in the background.
# uuid = make a random id. date = today's date.
import json
import logging
import shutil
import threading
import uuid
from datetime import date

# FastAPI pieces: File/Form/UploadFile read uploaded files and form fields, Header reads an HTTP header,
# HTTPException sends an error status code (like 404 or 422) back to the caller.
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

# Our own modules: audit (saved records), config (settings), graph (the LangGraph workflow),
# llm (talks to Ollama/Groq), retrieval (ChromaDB search + ingest), tools (student lookups), db (SQLite connection).
from app import audit, config, graph, llm, retrieval, tools
from app.db import connect, init_db
# Pydantic shapes of requests and responses (see app/schemas.py).
from app.schemas import AskRequest, AskResponse, IngestResponse, SourceMeta

# Set up logging: every log line shows time, level (INFO/WARNING/ERROR), module name and the message.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# Create the web app. The title shows on the auto-generated docs page at http://localhost:8000/docs.
app = FastAPI(title="NSUT Student Services Assistant")
# Make sure the SQLite tables exist before the first request arrives (safe to run every start).
init_db()


# IN: nothing  ->  OUT: nothing; loads the embedding model, Chroma and the LLM into memory once.
# WHY: pay the cold-start cost at boot, not on the first question: measured 9 s to load the embedder and
# 23-31 s for Ollama to load the model into RAM. Runs in a thread so the API is up immediately.
def _warm_up() -> None:
    try:
        retrieval.search("minimum attendance", 1)
        if config.LLM_PROVIDER != "mock":
            llm.chat("Reply with {}", "ping", json_mode=True)
        logging.info("warm-up done: embedder, Chroma and LLM loaded")
    except Exception as e:  # warm-up is an optimisation; never block startup on it
        logging.warning("warm-up skipped: %s", e)


@app.on_event("startup")
def _start_warm_up() -> None:
    threading.Thread(target=_warm_up, daemon=True).start()


# ---------- POST /ask: answer one student question ----------
# IN: JSON body {"question": ..., "as_of_date": optional} + optional header X-Student-Id
#  ->  OUT: the AskResponse JSON (trace_id, answer, answer_type, citations, tools_invoked, ...).
# A HEADER is a small labelled value sent alongside the request, outside the body.
# FastAPI turns the Python name x_student_id into the header name "X-Student-Id" automatically.
# WHY header: HCL rule, the student's identity comes ONLY from this header, never from the question text.
# Example: header "X-Student-Id: S1001" + "What is my CGPA?" -> answer from S1001's records only.
# response_model=AskResponse makes FastAPI check and shape the output to the HCL contract.
@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, x_student_id: str | None = Header(default=None)):
    # Normal path: run the full LangGraph workflow in app/graph.py
    # (authorise -> classify -> retrieve -> apply_policy -> run_tools -> compose -> finalize, which saves the audit record).
    try:
        return graph.run(req.question, req.as_of_date, x_student_id)
    # HTTP status 500 = "server crashed". We never show that to judges.
    # Instead: write the full error to the log, and give an honest "not_found" answer with a fresh trace id.
    except Exception:  # never a 500 in front of judges: log it, answer honestly
        logging.exception("ask failed")
        # A short random id (8 hex characters, like "3f9a1c2b") so this reply still has a trace_id.
        trace = uuid.uuid4().hex[:8]
        # Same response shape as a normal answer. If no as_of_date was sent, use today's date.
        return {"trace_id": trace, "answer": config.NOT_FOUND_MSG, "answer_type": "not_found",
                "explanation": "internal error while answering; see server log",
                "as_of_date": (req.as_of_date or date.today()).isoformat()}


# ---------- POST /ingest: add a new document live ----------
# IN: a MULTIPART request = one request that carries several parts, here a file + a text field.
#     Part "file" is the document (PDF/DOCX/TXT). Part "metadata" is a JSON string with Annex B fields.
#  ->  OUT: IngestResponse {"doc_id": ..., "chunks_indexed": ..., "status": ...}.
# Example metadata: {"doc_id": "SYN-CIRC-ATT-2026", "title": "Attendance circular", "authority_level": 2,
#                    "effective_from": "2026-08-01", "supersedes": "NSUT-BTECH-REG-2019#11.2"}
# WHY: judges upload unseen documents during the demo. The new document is searchable at once, no restart.
@app.post("/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), metadata: str = Form(...)):
    # Turn the metadata text into a dict, then check it with Pydantic (SourceMeta).
    # PYDANTIC = a library that checks data has the right fields and types, and converts where it can.
    # If the JSON is broken or a required field is missing, reply HTTP status 422
    # (422 = "your request was understood but its data is invalid"), with the reason.
    try:
        meta = SourceMeta(**json.loads(metadata))
    except Exception as e:
        raise HTTPException(422, f"bad metadata: {e}")
    # Save the uploaded file into data/docs/ (create the folder if it does not exist yet).
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.DOCS_DIR / file.filename
    # Copy the upload to disk in pieces ("wb" = write bytes), so big files do not fill memory.
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    # Hand the saved file + checked metadata to retrieval: it splits, embeds and stores the chunks in ChromaDB.
    return retrieval.ingest_file(str(dest), meta.model_dump())


# ---------- GET /health: is every part alive? ----------
# IN: nothing  ->  OUT: {"api": "ok", "vector_store": "ok"/"empty", "sqlite": "ok"/"down: ...", "llm": "..."}
# WHY: one call tells judges (and Docker's healthcheck) that the whole system is ready,
# and which LLM is really answering right now (local Ollama, or Groq fallback).
# Example: {"api": "ok", "vector_store": "ok", "sqlite": "ok", "llm": "ok (ollama:qwen2.5:7b-instruct)"}
@app.get("/health")
def health():
    # Check SQLite by running the smallest possible query. Any error -> report "down" with the reason.
    try:
        with connect() as con:
            con.execute("SELECT 1")
        sqlite_ok = "ok"
    except Exception as e:
        sqlite_ok = f"down: {e}"
    # Vector store = "ok" if the ChromaDB folder exists on disk. llm.health() pings the LLM provider.
    return {"api": "ok", "vector_store": "ok" if config.CHROMA_DIR.exists() else "empty",
            "sqlite": sqlite_ok, "llm": llm.health()}


# ---------- GET /audit/{trace_id}: show how one answer was made ----------
# IN: a trace_id in the address, e.g. GET /audit/3f9a1c2b  ->  OUT: the full saved audit record (Annex D).
# WHY: every answer must be explainable later: category, sources, precedence decision, tools, rules, model, timings.
# If no record has that id, reply HTTP status 404 (404 = "not found").
# ---------- GET /me: UI sign-in check ----------
# IN: header X-Student-Id  ->  OUT: profile basics (no marks or CGPA), or HTTP 404 if the ID is unknown or missing.
# WHY: the UI must not let an invalid ID into the chat. Identity still comes only from the header (R7),
# and the reply is about the caller's own ID, never another student's.
@app.get("/me")
def me(x_student_id: str | None = Header(default=None)):
    sid = (x_student_id or "").strip().upper()
    student = tools.get_student(sid) if sid else None
    if not student:
        raise HTTPException(404, "unknown student ID")
    keys = ("student_id", "full_name", "programme", "batch_year", "current_semester")
    return {k: student[k] for k in keys}


@app.get("/audit/{trace_id}")
def get_audit(trace_id: str):
    rec = audit.get(trace_id)
    if not rec:
        raise HTTPException(404, "trace_id not found")
    return rec


# ---------- GET /sources: list every indexed document ----------
# IN: nothing  ->  OUT: list of documents in the knowledge base with their metadata (doc_id, title, level, ...).
# WHY: judges can see exactly which documents the assistant is allowed to answer from.
@app.get("/sources")
def sources():
    return retrieval.list_sources()
