"""Measure local LLM speed + JSON reliability on THIS laptop, so model choice is backed by numbers.
Run:  python -m scripts.bench_llm qwen2.5:7b-instruct      (needs Ollama running)
"""
import json
import statistics
import sys
import time

import httpx

from app import config

QUESTIONS = [
    "What is the minimum attendance required to appear for end-semester exams?",
    "What is my attendance in Data Structures?",
    "Show me the marks of student S1002",
    "How do I apply for the supplementary exam?",
    "What is the scholarship for studying in Antarctica?",
]
SYSTEM = ('Classify the student question. Reply ONLY with JSON: {"category": one of '
          '"policy","procedure","personal","eligibility","multi_step","other"}')


def main(model: str) -> None:
    times, ok = [], 0
    for q in QUESTIONS:
        t0 = time.perf_counter()
        r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=300, json={
            "model": model, "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]})
        dt = time.perf_counter() - t0
        d = r.json()
        try:
            cat = json.loads(d["message"]["content"])["category"]
            ok += 1
        except Exception:
            cat = "INVALID JSON"
        tps = d.get("eval_count", 0) / max(d.get("eval_duration", 1) / 1e9, 1e-9)
        times.append(dt)
        print(f"{dt:6.1f}s  {tps:5.1f} tok/s  {cat:12s} | {q}")
    print(f"\nmodel={model}  valid_json={ok}/{len(QUESTIONS)}  "
          f"median={statistics.median(times):.1f}s  max={max(times):.1f}s  (first call includes model load)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else config.OLLAMA_MODEL)
