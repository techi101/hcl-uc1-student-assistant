"""Audit trail (R10): one JSON record per answer, fetched by GET /audit/{trace_id}. Owner: C."""
# WHAT THIS FILE IS: the "black box recorder" for answers. Every answer is saved as one JSON record
# in the SQLite table audit_log, keyed by its trace_id (the Annex D audit record HCL asks for).
# Real example: /ask returns trace_id "3f9a1c2b". Later, GET /audit/3f9a1c2b returns the saved record:
# {"trace_id": "3f9a1c2b", "student_id": "S1001", "question_category": "personal", "sources_retrieved": [...],
#  "precedence_decision": "...", "tools_invoked": [...], "answer_type": "calculated", "model": "ollama:...", "latency_ms": 2140}
# The record itself is built in app/graph.py (finalize). The question text is NOT stored (privacy rule R7).
# json = turn the Python dict into text and back. datetime/timezone = the time the record was saved, in UTC.
import json
from datetime import datetime, timezone

from app.db import connect


# IN: one audit record (a dict that must contain "trace_id")  ->  OUT: nothing (the record is written to SQLite).
# WHY: so any answer can be explained later, step by step, even after the server restarts.
# The table has 3 columns: trace_id, saved time (UTC, e.g. "2026-10-06T09:15:02+00:00"), the whole record as JSON text.
# "INSERT OR REPLACE" = if this trace_id already exists, overwrite it instead of failing.
# default=str = anything JSON cannot store directly (like a date object) is saved as text.
# The "?" marks are placeholders: SQLite fills them in safely, so odd text cannot break the SQL.
def save(record: dict) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO audit_log VALUES (?,?,?)",
                    (record["trace_id"], datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     json.dumps(record, default=str)))


# IN: a trace_id like "3f9a1c2b"  ->  OUT: the saved record as a dict, or None if no such id exists.
# WHY: GET /audit/{trace_id} calls this. main.py turns None into HTTP status 404.
# fetchone() gives one row (a tuple) or None. row[0] is the JSON text, which json.loads turns back into a dict.
def get(trace_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT record_json FROM audit_log WHERE trace_id = ?", (trace_id,)).fetchone()
    return json.loads(row[0]) if row else None
