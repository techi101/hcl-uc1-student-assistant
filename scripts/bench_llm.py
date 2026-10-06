"""Measure local LLM speed + JSON reliability on THIS laptop, so model choice is backed by numbers.
Run:  python -m scripts.bench_llm qwen2.5:7b-instruct      (needs Ollama running)
"""
# WHAT THIS FILE IS: a tiny speed + routing test for a local LLM, run on our own laptop, so the model choice is backed by numbers.
# It sends the same 5 student questions to Ollama and asks the model to label each one (policy, personal, other, ...).
# Real result (docs/MODEL_CHOICE.md): qwen2.5:7b routed 5/5 correctly; qwen2.5:3b got only 2/5 (it labelled
# "Show me the marks of student S1002" as just "other"). So we use the 7B model. 5 questions = a smoke test, not a full evaluation.
# Ollama = a program that runs open-source LLMs on your own machine and serves them over HTTP (localhost:11434).
# json / statistics / sys / time = standard library: parse JSON, median, command-line arguments, timers. httpx = HTTP requests.
import json
import statistics
import sys
import time

import httpx

from app import config

# The 5 test questions, one per route: policy, my own data, another student's data, procedure, not answerable.
# Routing accuracy is scored by reading the category printed next to each question.
QUESTIONS = [
    "What is the minimum attendance required to appear for end-semester exams?",
    "What is my attendance in Data Structures?",
    "Show me the marks of student S1002",
    "How do I apply for the supplementary exam?",
    "What is the scholarship for studying in Antarctica?",
]
# The instruction (system prompt): reply with JSON only, with one category from a fixed list.
SYSTEM = ('Classify the student question. Reply ONLY with JSON: {"category": one of '
          '"policy","procedure","personal","eligibility","multi_step","other"}')


# IN: a model name like "qwen2.5:7b-instruct"  ->  OUT: nothing returned; prints one line per question and a summary.
# Example line: "   3.1s   21.4 tok/s  policy       | What is the minimum attendance ..."
def main(model: str) -> None:
    # times = seconds per question; ok = how many replies were valid JSON with a "category".
    times, ok = [], 0
    for q in QUESTIONS:
        # Start a timer, then call Ollama's chat API. stream False = wait for the full reply; format "json" = force JSON output;
        # temperature 0 = no randomness, so the same question gets the same label every run.
        t0 = time.perf_counter()
        r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=300, json={
            "model": model, "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]})
        dt = time.perf_counter() - t0
        d = r.json()
        # Try to read the category. Broken or missing JSON -> not counted, and "INVALID JSON" is printed instead.
        try:
            cat = json.loads(d["message"]["content"])["category"]
            ok += 1
        except Exception:
            cat = "INVALID JSON"
        # Tokens per second = tokens generated (eval_count) / generation time (eval_duration is in nanoseconds, so divide by 1e9).
        tps = d.get("eval_count", 0) / max(d.get("eval_duration", 1) / 1e9, 1e-9)
        times.append(dt)
        print(f"{dt:6.1f}s  {tps:5.1f} tok/s  {cat:12s} | {q}")
    # Summary: valid JSON count, median and max time. The first call is slower because Ollama loads the model into memory.
    # Note: valid_json counts replies we could parse; the 5/5 vs 2/5 routing score comes from checking the printed categories.
    print(f"\nmodel={model}  valid_json={ok}/{len(QUESTIONS)}  "
          f"median={statistics.median(times):.1f}s  max={max(times):.1f}s  (first call includes model load)")


# Run as a script: model name from the command line, else the default OLLAMA_MODEL from app/config.py.
if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else config.OLLAMA_MODEL)
