"""FastAPI app: the 5 endpoints fixed by HCL (Section 6). Owner: C."""
import json
import logging
import shutil

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from app import audit, config, graph, llm, retrieval
from app.db import connect, init_db
from app.schemas import AskRequest, AskResponse, IngestResponse, SourceMeta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title="NSUT Student Services Assistant")
init_db()


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, x_student_id: str | None = Header(default=None)):
    return graph.run(req.question, req.as_of_date, x_student_id)


@app.post("/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), metadata: str = Form(...)):
    try:
        meta = SourceMeta(**json.loads(metadata))
    except Exception as e:
        raise HTTPException(422, f"bad metadata: {e}")
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.DOCS_DIR / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return retrieval.ingest_file(str(dest), meta.model_dump())


@app.get("/health")
def health():
    try:
        with connect() as con:
            con.execute("SELECT 1")
        sqlite_ok = "ok"
    except Exception as e:
        sqlite_ok = f"down: {e}"
    return {"api": "ok", "vector_store": "ok" if config.CHROMA_DIR.exists() else "empty",
            "sqlite": sqlite_ok, "llm": llm.health()}


@app.get("/audit/{trace_id}")
def get_audit(trace_id: str):
    rec = audit.get(trace_id)
    if not rec:
        raise HTTPException(404, "trace_id not found")
    return rec


@app.get("/sources")
def sources():
    return retrieval.list_sources()
