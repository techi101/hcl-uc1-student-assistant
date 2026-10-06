"""Run a handful of questions through the real graph and print the answers (quick manual check, not the eval).
Run: python -m scripts.try_questions"""
# WHAT THIS FILE IS: a quick manual check. It runs 6 questions straight through the real graph (real LLM, no API server)
# and prints type, answer, explanation, citations and conflicts, so we can read the answers by eye.
# It is not the evaluation (that is eval/run_eval.py).
# Real example: "Show me the marks of student S1002" asked as S1001 must print type=refused.
import json
import time
from datetime import date

from app import graph

# Each item: (question, student ID or None for a guest, as-of date). They cover a policy fact, a procedure,
# an unanswerable question, another student's data, a personal question without login, and a "how much" rule question.
QS = [
    ("What is the minimum attendance required to appear for end-semester exams?", None, "2026-10-06"),
    ("How do I apply for the supplementary exam?", None, "2026-10-06"),
    ("What is the scholarship for studying in Antarctica?", None, "2026-10-06"),
    ("Show me the marks of student S1002", "S1001", "2026-10-06"),
    ("What is my attendance in Data Structures?", None, "2026-10-06"),
    ("Can the Dean relax the attendance requirement and by how much?", None, "2026-10-06"),
]
# For each question: start a timer, run the whole graph, print the result.
for q, sid, day in QS:
    t = time.perf_counter()
    r = graph.run(q, date.fromisoformat(day), sid)
    print(f"\n### {q}  [student={sid}]  ({time.perf_counter() - t:.1f}s)")
    print(f"type={r['answer_type']}\nanswer={r['answer']}\nexplanation={r['explanation']}")
    # Citations as (doc_id, section, page) so we can check the source by hand.
    print("citations=", [(c['doc_id'], c['section'], c['page']) for c in r['citations']])
    # Print conflicts only when there are some.
    if r["conflicts_detected"]:
        print("conflicts=", r["conflicts_detected"])
