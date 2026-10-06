"""Evaluation runner (HCL Section 7). Owner: A.

Two modes:
  python -m eval.run_eval --retrieval-only            # no LLM: retrieval hit rate@k for the current EMBED_MODEL/TOP_K
  python -m eval.run_eval                             # full: every question through POST /ask (in-process), all 6 metrics
Options: --testset eval/testset.json  --k 5  --fresh (ignore saved results)  --url http://host:8000 (real server)
Results are saved per question to eval/results_<config>.jsonl (resumable: a crash or 429 doesn't lose progress).

Test set item (eval/testset.json, written by Neetu):
  {"id","question","student_id"|null,"as_of_date","category","expected_answer_type","expected_answer",
   "expected_doc_id"|null,"expected_section"|null,"expected_tool_result": {...}|null,"notes"}

Method (disclosed in the report): exact match, no LLM judge —
  answer correctness  = answer_type matches AND every number/date in expected_answer appears in the answer text
  citation accuracy   = (answerable questions with an expected doc) a citation has expected doc_id (+ section prefix)
  abstention accuracy = unanswerable -> not_found, answerable -> not not_found
  tool-result correct = every key/value in expected_tool_result appears in some tools_invoked output
  retrieval hit rate  = expected doc_id (+ section prefix) in the top-k retrieved chunks
  latency/cost        = p50/p95 wall-clock ms; llm_calls + tokens from the audit record
"""
# WHAT THIS FILE IS: our "exam paper" checker. eval/testset.json has 29 questions, each with the answer we
# expect. This script asks every question to our own /ask endpoint and marks the reply with plain code
# rules (no AI judge), then writes a report table.
# Real example: Q01 "What is the minimum attendance required to appear for end-semester exams?" expects
# answer_type "retrieved_fact", the number 80, and a citation to SYN-CIRC-ATT-2026 section 1.
# If the reply is a retrieved_fact, says "80%", and cites that circular section 1 -> correct + citation OK.
# The 6 metrics (each is "how many passed / how many were checked"):
#   answer correctness, citation accuracy, abstention accuracy, tool-result correctness,
#   retrieval hit rate@k, and latency/cost (p50/p95 time, LLM calls, tokens).
# Two modes: --retrieval-only (no LLM at all, only checks search; e.g. MiniLM found 16/20 vs bge 11/20,
# so we kept MiniLM) and full mode (every question through /ask).
# argparse = reads command-line options like "--k 5" or "--fresh" into a Python object.
import argparse
# json = reads/writes JSON (a standard text format for data, like {"id": "Q01"}).
import json
# re = regular expressions (text patterns); statistics = median and mean; time = stopwatch.
import re
import statistics
import time
# Path = a file path object that works the same on Windows and Linux.
from pathlib import Path

# config = our settings: TOP_K, EMBED_MODEL, LLM provider and model names.
from app import config

# ROOT = the eval/ folder (the folder this file is in). Test set, results and report live here.
ROOT = Path(__file__).resolve().parent
# NUM finds the "facts" we demand in an answer: a date like 2026-08-01 (\d{4}-\d{2}-\d{2} = 4 digits,
# dash, 2 digits, dash, 2 digits) OR a number like 80 or 6.5 (\d+(?:\.\d+)?). The date is tried first,
# so "2026-08-01" stays one item instead of becoming "2026", "08", "01".
# Example: expected_answer "80% from 2026-08-01" -> ["80", "2026-08-01"].
NUM = re.compile(r"\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?")


# IN: path to the test set file  ->  OUT: list of question dicts.
# WHY the clear error: if the file is missing, stop with a message saying who writes it and where the format is.
def load(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"{p} not found — Neetu writes eval/testset.json (format in this file's docstring)")
    return json.loads(p.read_text(encoding="utf-8"))


# IN: section we found (e.g. "11.2") + section we expected (e.g. "11")  ->  OUT: True if it counts as a match.
# Rule: exact match, or the found section is a SUB-section of the expected one.
# Example: expected "11" accepts "11" and "11.2", but NOT "110" (we check for "11." with the dot).
# No expected section -> any section is fine (True).
def sec_ok(found: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    f = str(found or "")
    return f == str(expected) or f.startswith(str(expected) + ".")


# IN: one question + k (how many chunks to fetch)  ->  OUT: True (hit), False (miss), None (not scored).
# hit@k = "did the right document show up in the top k search results?" No LLM involved.
# Example: k=5, Q01 expects SYN-CIRC-ATT-2026 section 1; if any of the 5 chunks is from it -> True.
# Questions with no expected document (e.g. "out of scope" questions) return None and are left out of the count.
def retrieval_hit(q: dict, k: int) -> bool | None:
    if not q.get("expected_doc_id"):
        return None
    from app.retrieval import search
    return any(c["doc_id"] == q["expected_doc_id"] and sec_ok(c.get("section"), q.get("expected_section"))
               for c in search(q["question"], k))


# IN: an HTTP client + one question  ->  OUT: (the /ask JSON reply, time taken in milliseconds).
# Example: Q05 has student_id "S1001", so we send header X-Student-Id: S1001 (identity only via the header,
# never inside the question text, as the rules require).
def ask(client, q: dict) -> tuple[dict, float]:
    # Personal questions send the student id as a header; general questions send no header.
    headers = {"X-Student-Id": q["student_id"]} if q.get("student_id") else {}
    body = {"question": q["question"]}
    # Fix the "today" date for the question so results do not change depending on the day we run the test.
    if q.get("as_of_date"):
        body["as_of_date"] = q["as_of_date"]
    # Time only the /ask call: stopwatch before, stopwatch after, seconds x 1000 = milliseconds.
    t0 = time.perf_counter()
    r = client.post("/ask", json=body, headers=headers, timeout=300)
    return r.json(), (time.perf_counter() - t0) * 1000


# IN: one question (with expected values) + our /ask reply  ->  OUT: dict of pass/fail marks for that question.
# True = passed, False = failed, None = this metric does not apply to this question (not counted).
# Example: Q05 expects "calculated", number "80", tool result {"result": "ELIGIBLE"}.
#   Reply type "calculated" + text has "80" -> answer_correct True; a tool output has result == "ELIGIBLE" -> tool_ok True.
def score(q: dict, resp: dict) -> dict:
    exp_type = q.get("expected_answer_type")
    # Search for numbers in the answer AND the explanation together, so a number in either place counts.
    answer = f"{resp.get('answer', '')} {resp.get('explanation', '')}"
    # The numbers/dates we demand, pulled out of the expected answer ("80%" -> ["80"]).
    nums = NUM.findall(str(q.get("expected_answer") or ""))
    type_ok = resp.get("answer_type") == exp_type
    # Answer correctness = type matches AND (type is a "no answer" kind, which needs no numbers,
    # OR every demanded number appears in the text). Example: expected "80", text "80% attendance" -> True.
    correct = type_ok and (exp_type in ("not_found", "refused", "clarification_needed") or all(n in answer for n in nums))
    cites = resp.get("citations") or []
    # Citation accuracy: only for questions that SHOULD be answered and have an expected document.
    # Pass if ANY citation has the expected doc_id and a matching section (see sec_ok).
    cite = None
    if q.get("expected_doc_id") and exp_type not in ("not_found", "refused"):
        cite = any(c.get("doc_id") == q["expected_doc_id"] and sec_ok(c.get("section"), q.get("expected_section"))
                   for c in cites)
    # Abstention accuracy: "did we say not_found?" must equal "should we say not_found?".
    # Expected not_found and we said not_found -> True. Answerable and we said not_found -> False (gave up wrongly).
    # Unanswerable and we answered anyway -> False (made something up).
    abst = (resp.get("answer_type") == "not_found") == (exp_type == "not_found")
    # Tool-result correctness: only when the question lists expected tool values.
    # Collect the output of every tool that ran, then EVERY expected key/value must be found in SOME output.
    # Values are compared as text, so 80 and "80" count as equal.
    tool = None
    if q.get("expected_tool_result"):
        outs = [t.get("output") or {} for t in resp.get("tools_invoked") or []]
        tool = all(any(isinstance(o, dict) and str(o.get(k)) == str(v) for o in outs)
                   for k, v in q["expected_tool_result"].items())
    return {"answer_correct": correct, "type_ok": type_ok, "citation_ok": cite, "abstention_ok": abst, "tool_ok": tool}


# IN: list of True/False/None marks  ->  OUT: text like "25/29 = 86%" (or "n/a" if nothing to count).
# Formula: passed / counted x 100. None values are dropped first, because that metric did not apply.
# Python counts True as 1 and False as 0, so sum([True, False, True]) = 2.
# Example: 25 True out of 29 -> "25/29 = 86%". Retrieval: 16 hits of 20 scored questions -> "16/20 = 80%".
def pct(vals: list) -> str:
    vals = [v for v in vals if v is not None]
    return f"{sum(vals)}/{len(vals)} = {100 * sum(vals) / len(vals):.0f}%" if vals else "n/a"


# IN: command-line options  ->  OUT: nothing returned; prints progress and writes eval/report_<config>.md.
# Flow: read options -> load questions -> (retrieval-only? check search and stop) -> else ask each question,
# save each result line, then build the metrics table.
def main() -> None:
    # Command-line options (argparse):
    #   --testset: which question file; --k: how many chunks to retrieve (default = TOP_K from config, 5)
    #   --retrieval-only: test search only, no LLM; --fresh: delete old saved results and start over
    #   --url: test a real running server (e.g. http://localhost:8000) instead of the in-process app
    ap = argparse.ArgumentParser()
    ap.add_argument("--testset", default=str(ROOT / "testset.json"))
    ap.add_argument("--k", type=int, default=config.TOP_K)
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--url", default="")
    a = ap.parse_args()
    qs = load(a.testset)
    # cfg = a short name for this setup, used in file names so different setups never mix.
    # Example: EMBED_MODEL "sentence-transformers/all-MiniLM-L6-v2" and k 5 -> "all-MiniLM-L6-v2_k5".
    cfg = f"{config.EMBED_MODEL.split('/')[-1]}_k{a.k}"

    # Mode 1, retrieval only (no LLM, fast, free): check hit@k for every question, print each MISS so we
    # can see what search got wrong, then print the total. This is how we compared embedding models:
    # MiniLM 16/20 vs bge 11/20.
    if a.retrieval_only:
        hits = [retrieval_hit(q, a.k) for q in qs]
        for q, h in zip(qs, hits):
            if h is False:
                print(f"  MISS {q['id']}: expected {q['expected_doc_id']}#{q.get('expected_section')} | {q['question'][:70]}")
        print(f"[{cfg}] retrieval hit rate@{a.k}: {pct(hits)}")
        return

    # Mode 2, full run. Results go to a .jsonl file (JSON Lines = one JSON object per line, one line per question).
    # WHY jsonl: we add one line after each question, so if the run crashes or the LLM says 429 (too many
    # requests), the finished questions are already saved and a re-run continues where it stopped.
    out_path = ROOT / f"results_{cfg}.jsonl"
    done = {}
    # --fresh: delete the old results file so every question is asked again.
    if a.fresh and out_path.exists():
        out_path.unlink()                    # --fresh really starts over (was appending to old rows)
    # Resume: read every saved line into done = {"Q01": {...row...}, ...}; empty lines are skipped.
    if out_path.exists():
        done = {json.loads(l)["id"]: json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l}
    # Pick how to talk to the API:
    #   --url given -> httpx (an HTTP client library) sends real web requests to that running server.
    #   no --url    -> FastAPI's TestClient calls our app directly inside this same Python process,
    #                  no server needed, but it runs the exact same /ask code.
    if a.url:
        import httpx
        client = httpx.Client(base_url=a.url)
    else:
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

    # Open the results file in "a" (append) mode, so new lines go at the end and saved ones stay.
    with out_path.open("a", encoding="utf-8") as f:
        for q in qs:
            # Already answered in an earlier run -> skip (this is the resume step).
            if q["id"] in done:
                continue
            resp, ms = ask(client, q)
            # Fetch the audit record for this answer (via its trace_id) to get LLM calls and tokens used.
            # If the audit call fails (not status 200 = OK), keep audit empty instead of crashing.
            audit = {}
            if resp.get("trace_id"):
                r = client.get(f"/audit/{resp['trace_id']}")
                audit = r.json() if r.status_code == 200 else {}
            # One result row: id, category, time, all the marks from score(), the hit@k check,
            # what type we got vs expected, the first 300 characters of the answer, LLM calls and tokens.
            row = {"id": q["id"], "category": q.get("category"), "ms": round(ms), **score(q, resp),
                   "retrieval_hit": retrieval_hit(q, a.k), "answer_type": resp.get("answer_type"),
                   "expected_answer_type": q.get("expected_answer_type"), "answer": resp.get("answer", "")[:300],
                   "llm_calls": audit.get("llm_calls"), "tokens": audit.get("tokens")}
            # Write the row as one JSON line and flush (push it to disk NOW), so a crash cannot lose it.
            f.write(json.dumps(row) + "\n")
            f.flush()
            done[q["id"]] = row
            # Progress line (format only, timing invented for illustration), e.g. "Q01   OK  retrieved_fact   4210ms | What is the minimum attendance ..."
            print(f"{q['id']:5s} {'OK ' if row['answer_correct'] else 'BAD'} {row['answer_type']:20s} "
                  f"{row['ms']:6d}ms | {q['question'][:60]}")

    # Build the report from all saved rows, in test set order.
    rows = [done[q["id"]] for q in qs if q["id"] in done]
    # Latency: all answer times sorted from fastest to slowest.
    lat = sorted(r["ms"] for r in rows)
    # p50 = the median = the middle time: half the answers were faster (computed below with statistics.median).
    # p95 = the time that 95% of answers beat: take the item at position int(0.95 x count) in the sorted list.
    # Worked number: 29 answers -> int(0.95 x 29) = int(27.55) = 27 -> index 27 = the 28th fastest answer.
    # min(len(lat) - 1, ...) stops the index from going past the end of the list. No answers -> 0.
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
    # Cost: LLM calls and tokens per question (only rows where the audit gave a number). Mean = average.
    # Tokens = pieces of words the model reads and writes; providers charge and rate-limit by tokens.
    calls = [r["llm_calls"] for r in rows if r.get("llm_calls") is not None]
    toks = [r["tokens"] for r in rows if r.get("tokens") is not None]
    # The report is Markdown (a simple text format; "| a | b |" lines become a table).
    # Title shows the config and which LLM was used (Ollama model or Groq model, depending on LLM_PROVIDER).
    # Each table row uses pct() for "passed/counted = %", e.g. "| Answer correctness ... | 25/29 = 86% |".
    report = [f"# Evaluation report — config `{cfg}` ({len(rows)} questions, model {config.LLM_PROVIDER}:"
              f"{config.OLLAMA_MODEL if config.LLM_PROVIDER == 'ollama' else config.GROQ_MODEL})", "",
              "| Metric | Result |", "|---|---|",
              f"| Answer correctness (type + exact numbers/dates) | {pct([r['answer_correct'] for r in rows])} |",
              f"| Citation accuracy (expected doc + section cited) | {pct([r['citation_ok'] for r in rows])} |",
              f"| Abstention accuracy | {pct([r['abstention_ok'] for r in rows])} |",
              f"| Tool-result correctness | {pct([r['tool_ok'] for r in rows])} |",
              f"| Retrieval hit rate@{a.k} | {pct([r['retrieval_hit'] for r in rows])} |",
              f"| Latency p50 / p95 | {statistics.median(lat) if lat else 0:.0f} ms / {p95} ms |",
              f"| LLM calls / tokens per question (mean) | {statistics.mean(calls) if calls else 'n/a'} / "
              f"{round(statistics.mean(toks)) if toks else 'n/a'} |", "",
              "## Failures", ""]
    # List every question we got wrong: expected type vs got type, plus the start of our answer.
    # WHY: an honest report shows failures, and this list tells us exactly what to fix next.
    report += [f"- **{r['id']}** ({r['category']}): expected `{r['expected_answer_type']}`, got `{r['answer_type']}` — "
               f"{r['answer'][:160]}" for r in rows if not r["answer_correct"]]
    # Save the report as eval/report_<config>.md and also print it on screen.
    (ROOT / f"report_{cfg}.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


# Run main() only when started directly (python -m eval.run_eval), not when imported by another file.
if __name__ == "__main__":
    main()
