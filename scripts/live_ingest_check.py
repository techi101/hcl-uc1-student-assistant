"""Rehearse the judges' live test: POST /ingest an unseen circular, check it is searchable, that precedence
applies it, and which rule rows were extracted. Cleans up afterwards unless --keep.
Run: python -m scripts.live_ingest_check [--keep]
"""
import json
import sys
import time

from fastapi.testclient import TestClient

from app import precedence, retrieval
from app.db import connect
from app.main import app

DOC = "tests/fixtures/TEST-CIRC-FLOOR.md"
META = {"doc_id": "TEST-CIRC-FLOOR", "title": "Revised floor for attendance after relaxation (TEST)",
        "issuer": "Controller of Examinations", "authority_level": "2", "doc_type": "circular",
        "effective_from": "2026-09-01", "supersedes": "NSUT-BTECH-REG-2019#11.6", "scope_programmes": "B.Tech",
        "synthetic": "Y"}

c = TestClient(app)
t0 = time.perf_counter()
with open(DOC, "rb") as f:
    r = c.post("/ingest", files={"file": ("TEST-CIRC-FLOOR.md", f, "text/markdown")}, data={"metadata": json.dumps(META)})
print("POST /ingest ->", r.status_code, r.json(), f"{time.perf_counter() - t0:.1f}s")

q = "What is the minimum attendance after relaxation below which a student cannot appear in the ESE?"
hits = retrieval.search(q, 4)
print("\nsearch:", [(h["doc_id"], h["section"], h["score"], h.get("added_by", "")) for h in hits])
for day in ("2026-08-15", "2026-10-06"):
    res = precedence.resolve(hits, day, {"programme": "B.Tech CSE", "batch_year": 2023}, q)
    print(f"\nas_of {day}: applicable={[(x['doc_id'], x['section']) for x in res['applicable']][:3]}")
    print("  decision:", res["decision"][:300])
    print("  rule in force:", precedence.get_rule_in_force("attendance_floor_pct", day, {"programme": "B.Tech CSE", "batch_year": 2023})["rule"])
print("\nGET /sources has it:", any(s["doc_id"] == "TEST-CIRC-FLOOR" for s in c.get("/sources").json()))

if "--keep" not in sys.argv:
    retrieval._collection().delete(where={"doc_id": "TEST-CIRC-FLOOR"})
    with connect() as con:
        con.execute("DELETE FROM sources WHERE doc_id = 'TEST-CIRC-FLOOR'")
        con.execute("DELETE FROM rule_registry WHERE source_doc_id = 'TEST-CIRC-FLOOR'")
    print("cleaned up (use --keep to leave it in)")
