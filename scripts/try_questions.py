"""Run a handful of questions through the real graph and print the answers (quick manual check, not the eval).
Run: python -m scripts.try_questions"""
import json
import time
from datetime import date

from app import graph

QS = [
    ("What is the minimum attendance required to appear for end-semester exams?", None, "2026-10-06"),
    ("How do I apply for the supplementary exam?", None, "2026-10-06"),
    ("What is the scholarship for studying in Antarctica?", None, "2026-10-06"),
    ("Show me the marks of student S1002", "S1001", "2026-10-06"),
    ("What is my attendance in Data Structures?", None, "2026-10-06"),
    ("Can the Dean relax the attendance requirement and by how much?", None, "2026-10-06"),
]
for q, sid, day in QS:
    t = time.perf_counter()
    r = graph.run(q, date.fromisoformat(day), sid)
    print(f"\n### {q}  [student={sid}]  ({time.perf_counter() - t:.1f}s)")
    print(f"type={r['answer_type']}\nanswer={r['answer']}\nexplanation={r['explanation']}")
    print("citations=", [(c['doc_id'], c['section'], c['page']) for c in r['citations']])
    if r["conflicts_detected"]:
        print("conflicts=", r["conflicts_detected"])
