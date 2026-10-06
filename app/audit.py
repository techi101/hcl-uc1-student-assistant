"""Audit trail (R10): one JSON record per answer, fetched by GET /audit/{trace_id}. Owner: C."""
import json
from datetime import datetime, timezone

from app.db import connect


def save(record: dict) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO audit_log VALUES (?,?,?)",
                    (record["trace_id"], datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     json.dumps(record, default=str)))


def get(trace_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT record_json FROM audit_log WHERE trace_id = ?", (trace_id,)).fetchone()
    return json.loads(row[0]) if row else None
