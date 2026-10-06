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
import argparse
import json
import re
import statistics
import time
from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parent
NUM = re.compile(r"\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?")


def load(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"{p} not found — Neetu writes eval/testset.json (format in this file's docstring)")
    return json.loads(p.read_text(encoding="utf-8"))


def sec_ok(found: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    f = str(found or "")
    return f == str(expected) or f.startswith(str(expected) + ".")


def retrieval_hit(q: dict, k: int) -> bool | None:
    if not q.get("expected_doc_id"):
        return None
    from app.retrieval import search
    return any(c["doc_id"] == q["expected_doc_id"] and sec_ok(c.get("section"), q.get("expected_section"))
               for c in search(q["question"], k))


def ask(client, q: dict) -> tuple[dict, float]:
    headers = {"X-Student-Id": q["student_id"]} if q.get("student_id") else {}
    body = {"question": q["question"]}
    if q.get("as_of_date"):
        body["as_of_date"] = q["as_of_date"]
    t0 = time.perf_counter()
    r = client.post("/ask", json=body, headers=headers, timeout=300)
    return r.json(), (time.perf_counter() - t0) * 1000


def score(q: dict, resp: dict) -> dict:
    exp_type = q.get("expected_answer_type")
    answer = f"{resp.get('answer', '')} {resp.get('explanation', '')}"
    nums = NUM.findall(str(q.get("expected_answer") or ""))
    type_ok = resp.get("answer_type") == exp_type
    correct = type_ok and (exp_type in ("not_found", "refused", "clarification_needed") or all(n in answer for n in nums))
    cites = resp.get("citations") or []
    cite = None
    if q.get("expected_doc_id") and exp_type not in ("not_found", "refused"):
        cite = any(c.get("doc_id") == q["expected_doc_id"] and sec_ok(c.get("section"), q.get("expected_section"))
                   for c in cites)
    abst = (resp.get("answer_type") == "not_found") == (exp_type == "not_found")
    tool = None
    if q.get("expected_tool_result"):
        outs = [t.get("output") or {} for t in resp.get("tools_invoked") or []]
        tool = all(any(isinstance(o, dict) and str(o.get(k)) == str(v) for o in outs)
                   for k, v in q["expected_tool_result"].items())
    return {"answer_correct": correct, "type_ok": type_ok, "citation_ok": cite, "abstention_ok": abst, "tool_ok": tool}


def pct(vals: list) -> str:
    vals = [v for v in vals if v is not None]
    return f"{sum(vals)}/{len(vals)} = {100 * sum(vals) / len(vals):.0f}%" if vals else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testset", default=str(ROOT / "testset.json"))
    ap.add_argument("--k", type=int, default=config.TOP_K)
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--url", default="")
    a = ap.parse_args()
    qs = load(a.testset)
    cfg = f"{config.EMBED_MODEL.split('/')[-1]}_k{a.k}"

    if a.retrieval_only:
        hits = [retrieval_hit(q, a.k) for q in qs]
        for q, h in zip(qs, hits):
            if h is False:
                print(f"  MISS {q['id']}: expected {q['expected_doc_id']}#{q.get('expected_section')} | {q['question'][:70]}")
        print(f"[{cfg}] retrieval hit rate@{a.k}: {pct(hits)}")
        return

    out_path = ROOT / f"results_{cfg}.jsonl"
    done = {}
    if a.fresh and out_path.exists():
        out_path.unlink()                    # --fresh really starts over (was appending to old rows)
    if out_path.exists():
        done = {json.loads(l)["id"]: json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l}
    if a.url:
        import httpx
        client = httpx.Client(base_url=a.url)
    else:
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)

    with out_path.open("a", encoding="utf-8") as f:
        for q in qs:
            if q["id"] in done:
                continue
            resp, ms = ask(client, q)
            audit = {}
            if resp.get("trace_id"):
                r = client.get(f"/audit/{resp['trace_id']}")
                audit = r.json() if r.status_code == 200 else {}
            row = {"id": q["id"], "category": q.get("category"), "ms": round(ms), **score(q, resp),
                   "retrieval_hit": retrieval_hit(q, a.k), "answer_type": resp.get("answer_type"),
                   "expected_answer_type": q.get("expected_answer_type"), "answer": resp.get("answer", "")[:300],
                   "llm_calls": audit.get("llm_calls"), "tokens": audit.get("tokens")}
            f.write(json.dumps(row) + "\n")
            f.flush()
            done[q["id"]] = row
            print(f"{q['id']:5s} {'OK ' if row['answer_correct'] else 'BAD'} {row['answer_type']:20s} "
                  f"{row['ms']:6d}ms | {q['question'][:60]}")

    rows = [done[q["id"]] for q in qs if q["id"] in done]
    lat = sorted(r["ms"] for r in rows)
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
    calls = [r["llm_calls"] for r in rows if r.get("llm_calls") is not None]
    toks = [r["tokens"] for r in rows if r.get("tokens") is not None]
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
    report += [f"- **{r['id']}** ({r['category']}): expected `{r['expected_answer_type']}`, got `{r['answer_type']}` — "
               f"{r['answer'][:160]}" for r in rows if not r["answer_correct"]]
    (ROOT / f"report_{cfg}.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
