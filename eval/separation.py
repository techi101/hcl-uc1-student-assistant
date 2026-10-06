"""Config comparison #2: how well does the top similarity score separate answerable from unanswerable questions?
(The not_found gate needs a threshold between the two groups; a bigger gap = safer threshold.)
Run: python -m eval.separation   (uses current EMBED_MODEL)"""
import json
import statistics

from app import config
from app.retrieval import search

ANSWERABLE = [q["question"] for q in json.load(open("tests/fixtures/retrieval_dev.json", encoding="utf-8"))]
UNANSWERABLE = ["What is the scholarship for studying in Antarctica?", "What is today's hostel mess menu?",
                "What salary package does Google offer NSUT students?", "Who won the NSUT cricket tournament?",
                "What is the parking fee for cars on campus?", "How do I apply for a passport?"]

ans = [search(q, 1)[0]["score"] for q in ANSWERABLE]
una = [search(q, 1)[0]["score"] for q in UNANSWERABLE]
print(f"[{config.EMBED_MODEL.split('/')[-1]}] answerable top score: min {min(ans):.3f} median {statistics.median(ans):.3f}")
print(f"[{config.EMBED_MODEL.split('/')[-1]}] unanswerable top score: max {max(una):.3f} median {statistics.median(una):.3f}")
print(f"gap (min answerable - max unanswerable) = {min(ans) - max(una):+.3f}")
