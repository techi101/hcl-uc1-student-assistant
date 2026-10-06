"""Rehearse the judges' live test: POST /ingest an unseen circular, check it is searchable, that precedence
applies it, and which rule rows were extracted. Cleans up afterwards unless --keep.
Run: python -m scripts.live_ingest_check [--keep]
"""
# WHAT THIS FILE IS: a rehearsal of the judges' live test. They will upload a document we have never seen and ask about it.
# This script uploads tests/fixtures/TEST-CIRC-FLOOR.md (a fake circular: "the attendance floor after relaxation is now 65%,
# replacing clause 11.6, from 1 Sep 2026") through POST /ingest, then checks:
# 1) /ingest returns 200, 2) search finds the new chunk, 3) precedence applies it on 2026-10-06 but not on 2026-08-15,
# 4) a rule row (attendance_floor_pct = 65) was extracted, so the eligibility tools would use 65% instead of the old 60%.
# Then it deletes everything it added, unless you pass --keep.
# TestClient = FastAPI's fake browser: it calls the API inside this Python process, no server needed.
import json
import sys
import time

from fastapi.testclient import TestClient

from app import precedence, retrieval
from app.db import connect
from app.main import app

# The test document and its metadata, typed the way a judge would fill the form. authority_level is the text "2" on purpose
# (the API must accept it). supersedes = "doc_id#section" of the clause this circular replaces. synthetic "Y" = made-up test document.
DOC = "tests/fixtures/TEST-CIRC-FLOOR.md"
META = {"doc_id": "TEST-CIRC-FLOOR", "title": "Revised floor for attendance after relaxation (TEST)",
        "issuer": "Controller of Examinations", "authority_level": "2", "doc_type": "circular",
        "effective_from": "2026-09-01", "supersedes": "NSUT-BTECH-REG-2019#11.6", "scope_programmes": "B.Tech",
        "synthetic": "Y"}

# Step 1: upload the file + metadata to POST /ingest and time it.
c = TestClient(app)
t0 = time.perf_counter()
with open(DOC, "rb") as f:
    r = c.post("/ingest", files={"file": ("TEST-CIRC-FLOOR.md", f, "text/markdown")}, data={"metadata": json.dumps(META)})
print("POST /ingest ->", r.status_code, r.json(), f"{time.perf_counter() - t0:.1f}s")

# Step 2: search with a question about the new circular. Print each hit's doc_id, section, score and who added it.
q = "What is the minimum attendance after relaxation below which a student cannot appear in the ESE?"
hits = retrieval.search(q, 4)
print("\nsearch:", [(h["doc_id"], h["section"], h["score"], h.get("added_by", "")) for h in hits])
# Step 3: run precedence on those hits for two dates. 2026-08-15 is before the circular starts (old floor applies);
# 2026-10-06 is after (the new 65% applies). Also print the floor rule row in force on each date: this is the
# check that rule extraction worked (a 65% row from TEST-CIRC-FLOOR should win on 2026-10-06).
for day in ("2026-08-15", "2026-10-06"):
    res = precedence.resolve(hits, day, {"programme": "B.Tech CSE", "batch_year": 2023}, q)
    print(f"\nas_of {day}: applicable={[(x['doc_id'], x['section']) for x in res['applicable']][:3]}")
    print("  decision:", res["decision"][:300])
    print("  rule in force:", precedence.get_rule_in_force("attendance_floor_pct", day, {"programme": "B.Tech CSE", "batch_year": 2023})["rule"])
# Step 4: the new document must be listed in the source register (GET /sources).
print("\nGET /sources has it:", any(s["doc_id"] == "TEST-CIRC-FLOOR" for s in c.get("/sources").json()))

# Clean-up: remove the test chunks from the vector store, its row from sources, and any rule rows it created,
# so the demo database is back to normal.
if "--keep" not in sys.argv:
    retrieval._collection().delete(where={"doc_id": "TEST-CIRC-FLOOR"})
    with connect() as con:
        con.execute("DELETE FROM sources WHERE doc_id = 'TEST-CIRC-FLOOR'")
        con.execute("DELETE FROM rule_registry WHERE source_doc_id = 'TEST-CIRC-FLOOR'")
    print("cleaned up (use --keep to leave it in)")
