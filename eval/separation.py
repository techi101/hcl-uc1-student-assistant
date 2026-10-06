"""Config comparison #2: how well does the top similarity score separate answerable from unanswerable questions?
(The not_found gate needs a threshold between the two groups; a bigger gap = safer threshold.)
Run: python -m eval.separation   (uses current EMBED_MODEL)"""
# WHAT THIS FILE IS: measures whether the search score alone can tell "we have a document for this" from "we do not".
# For each question we take the top search score. Answerable questions (from tests/fixtures/retrieval_dev.json) should score high,
# off-topic ones (Antarctica scholarship, mess menu, ...) should score low.
# gap = lowest answerable score minus highest unanswerable score. Positive gap = some threshold splits them perfectly; bigger = safer.
# Real result: MiniLM gap +0.013, bge-small gap +0.020. Both are tiny, so a score threshold alone is unsafe;
# the not_found decision also uses the LLM's signal (docs/SYSTEM_GUIDE.md). It uses whichever EMBED_MODEL config is set to.
import json
import statistics

from app import config
from app.retrieval import search

# Answerable = the dev set questions. Unanswerable = 6 questions no NSUT document covers.
ANSWERABLE = [q["question"] for q in json.load(open("tests/fixtures/retrieval_dev.json", encoding="utf-8"))]
UNANSWERABLE = ["What is the scholarship for studying in Antarctica?", "What is today's hostel mess menu?",
                "What salary package does Google offer NSUT students?", "Who won the NSUT cricket tournament?",
                "What is the parking fee for cars on campus?", "How do I apply for a passport?"]

# search(q, 1) = the single best chunk; [0]["score"] = its similarity (near 1 = same meaning, near 0 = unrelated).
ans = [search(q, 1)[0]["score"] for q in ANSWERABLE]
una = [search(q, 1)[0]["score"] for q in UNANSWERABLE]
# Print the model name (last part of e.g. "sentence-transformers/all-MiniLM-L6-v2"), lowest and median answerable score,
# highest and median unanswerable score, then the gap. "+.3f" prints the sign, so a negative gap (overlap) is obvious.
print(f"[{config.EMBED_MODEL.split('/')[-1]}] answerable top score: min {min(ans):.3f} median {statistics.median(ans):.3f}")
print(f"[{config.EMBED_MODEL.split('/')[-1]}] unanswerable top score: max {max(una):.3f} median {statistics.median(una):.3f}")
print(f"gap (min answerable - max unanswerable) = {min(ans) - max(una):+.3f}")
