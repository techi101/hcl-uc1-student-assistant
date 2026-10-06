"""The ONE fixed LangGraph workflow (CONTRACT.md section 1).

  authorise (CODE) ─refused─────────────────────────────────────────────┐
      └─ classify (LLM) ─other_student─────────────────────────────────┤
             └─ retrieve (Chroma) → precedence (CODE, Annex A)          │
                    └─ tools (CODE, SQLite + rule_registry) ─clarify───┤
                           └─ compose (LLM: words only) ────────────────┴→ finalize (CODE: answer_type,
                                                                            citations, audit, trace_id)
Why one fixed graph and not agents: every step except routing and wording is deterministic, so extra agents
would add failure points and latency without a requirement that needs them.
"""
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app import audit, config, llm, precedence, retrieval, tools
from app.db import connect
from app.prompts import CLASSIFY_SYSTEM, COMPOSE_SYSTEM

log = logging.getLogger(__name__)

MIN_SCORE = 0.50          # below this no chunk counts as evidence (measured: unanswerable max 0.53, answerable min 0.55)
MAX_SOURCES = 4           # fewer, shorter sources: 7B on a CPU laptop took 56-106 s with 5 x 1200 chars
PRONOUN = re.compile(r"\b(my|mine|me|am i|can i|do i|will i|have i|i am|i'm|i have|i've|i failed|i passed|i got)\b", re.I)
# personal = pronoun + the student's OWN DATA; "How do I apply ..." is a procedure, not personal
MY_DATA = re.compile(r"attendance|marks|result|grade|cgpa|sgpa|backlog|eligib|detain|record|\bpass(ed)?\b|\bfail(ed)?\b|promot", re.I)
SID = re.compile(r"\bS\d{4}\b", re.I)


class State(TypedDict, total=False):
    question: str
    as_of_date: str
    student_id: str | None
    student: dict | None
    trace_id: str
    category: str
    course_hint: str | None
    refused: str | None
    clarify: str | None
    chunks: list[dict]
    policy: dict
    tools_invoked: list[dict]
    composed: dict
    llm_calls: int
    tokens: int
    model: str
    timings: dict
    t0: float
    response: dict[str, Any]


def _timed(name: str, s: State, t: float) -> dict:
    return {**(s.get("timings") or {}), name: round((time.perf_counter() - t) * 1000)}


def _llm(s: State, system: str, user: str) -> tuple[dict | None, dict]:
    """JSON LLM call with one retry; returns (parsed or None, usage updates for state)."""
    calls, toks, model = s.get("llm_calls", 0), s.get("tokens", 0), s.get("model", "")
    for _ in range(2):
        try:
            out = llm.chat(system, user, json_mode=True)
            calls, toks, model = calls + 1, toks + out.get("tokens", 0), out["model"]
            return json.loads(out["text"]), {"llm_calls": calls, "tokens": toks, "model": model}
        except Exception as e:
            calls += 1
            log.warning("LLM call failed/invalid JSON: %s", e)
    return None, {"llm_calls": calls, "tokens": toks, "model": model}


# ---------------- nodes ----------------
def authorise(s: State) -> State:
    """R7 in CODE before any LLM call: identity only from the header; other students' data refused."""
    t = time.perf_counter()
    q, sid = s["question"], (s.get("student_id") or "").strip().upper() or None
    student = tools.get_student(sid) if sid else None
    refused = None
    other_ids = {m.upper() for m in SID.findall(q)} - ({sid} if sid else set())
    if other_ids:
        refused = "You can only access your own records. Requests for another student's data are not allowed."
    else:
        with connect() as con:
            names = [r[0] for r in con.execute("SELECT full_name FROM students WHERE student_id != ?", (sid or "",))]
        if any(n and len(n) > 3 and re.search(rf"\b{re.escape(n.lower())}\b", q.lower()) for n in names):
            refused = "You can only access your own records. Requests for another student's data are not allowed."
    if not refused and PRONOUN.search(q) and MY_DATA.search(q) and not sid:
        refused = "Please log in: personal questions need your student ID (X-Student-Id header)."
    if not refused and sid and not student:
        refused = f"Student {sid} is not in the records, so personal data cannot be shown."
    return {"student_id": sid, "student": student, "refused": refused, "timings": _timed("authorise_ms", s, t)}


def classify(s: State) -> State:
    t = time.perf_counter()
    parsed, usage = _llm(s, CLASSIFY_SYSTEM, s["question"])
    cat = (parsed or {}).get("category") or "policy"
    upd: State = {"category": cat, "course_hint": (parsed or {}).get("course_hint"), **usage}
    if cat == "other_student":          # the LLM may ADD a refusal, never remove one
        upd["refused"] = "You can only access your own records. Requests for another student's data are not allowed."
    if cat in ("personal", "eligibility") and not s.get("student"):
        if PRONOUN.search(s["question"]):     # "am I eligible ..." without login -> refuse
            upd["refused"] = "Please log in: personal questions need your student ID (X-Student-Id header)."
        else:                                 # "is 65% enough to appear ..." is a general rule question (eval Q04 bug)
            upd["category"] = "policy"
    upd["timings"] = _timed("classify_ms", s, t)
    return upd


def retrieve(s: State) -> State:
    t = time.perf_counter()
    return {"chunks": retrieval.search(s["question"], config.TOP_K), "timings": _timed("retrieve_ms", s, t)}


def apply_policy(s: State) -> State:
    t = time.perf_counter()
    evidence = [c for c in s["chunks"] if c["score"] >= MIN_SCORE]
    return {"policy": precedence.resolve(evidence, s["as_of_date"], s.get("student"), s["question"]),
            "timings": _timed("precedence_ms", s, t)}


def _call(name: str, fn, **kw) -> dict:
    t = time.perf_counter()
    try:
        out, status = fn(**kw), "ok"
    except Exception as e:
        out, status = {"error": str(e)}, "error"
    if isinstance(out, dict) and "error" in out:
        status = "error"
    return {"tool": name, "input": {k: v for k, v in kw.items() if k != "student_id"}, "output": out,
            "status": status, "ms": round((time.perf_counter() - t) * 1000)}


def run_tools(s: State) -> State:
    t = time.perf_counter()
    if s.get("category") not in ("personal", "eligibility", "multi_step") or not s.get("student"):
        return {"tools_invoked": [], "timings": _timed("tools_ms", s, t)}
    st, q, ql = s["student"], s["question"], s["question"].lower()
    sid, day = st["student_id"], s["as_of_date"]
    calls: list[dict] = []
    if re.search(r"backlog|cgpa", ql):
        calls.append(_call("get_backlogs", tools.get_backlogs, student_id=sid))
        calls.append({"tool": "get_student_record", "input": {}, "status": "ok", "ms": 0,
                      "output": {k: st[k] for k in ("programme", "batch_year", "current_semester", "cgpa", "active_backlogs")}})
    needs_course = bool(re.search(r"attendance|eligib|appear|sit|exam|marks|result|grade|pass|fail", ql))
    courses = tools.find_course(f"{s.get('course_hint') or ''} {q}", st["programme"]) if needs_course else []
    if needs_course and not courses and not calls:
        with connect() as con:
            own = [f"{r[0]} {r[1]}" for r in con.execute(
                "SELECT c.course_code, c.course_name FROM courses c JOIN attendance a ON a.course_code = c.course_code "
                "WHERE a.student_id = ?", (sid,))]
        return {"clarify": "Which course do you mean? Your courses: " + ", ".join(own) if own else
                "Which course do you mean? (no courses found in your records)", "tools_invoked": [],
                "timings": _timed("tools_ms", s, t)}
    if len(courses) > 1:
        return {"clarify": "Which course do you mean: " + ", ".join(f"{c['course_code']} {c['course_name']}" for c in courses) + "?",
                "tools_invoked": [], "timings": _timed("tools_ms", s, t)}
    if courses:
        code = courses[0]["course_code"]
        if re.search(r"eligib|appear|sit|allowed|detain", ql):
            calls.append(_call("check_exam_eligibility", tools.check_exam_eligibility, student_id=sid, course_code=code, as_of_date=day))
        elif "attendance" in ql:
            calls.append(_call("get_attendance", tools.get_attendance, student_id=sid, course_code=code))
        if re.search(r"marks|result|grade|pass|fail", ql):
            calls.append(_call("check_course_pass", tools.check_course_pass, student_id=sid, course_code=code, as_of_date=day))
        if not calls:
            calls.append(_call("get_attendance", tools.get_attendance, student_id=sid, course_code=code))
    return {"tools_invoked": calls, "timings": _timed("tools_ms", s, t)}


def compose(s: State) -> State:
    t = time.perf_counter()
    pol = s["policy"]
    srcs = pol["applicable"][:MAX_SOURCES] + pol.get("informational", [])[:1]
    ok_tools = [c for c in s.get("tools_invoked", []) if c["status"] == "ok"]
    if not srcs and not ok_tools:
        return {"composed": {"answer": "NOT_FOUND"}, "timings": _timed("compose_ms", s, t)}
    blocks = [f'<untrusted_source id="S{i}" doc="{c["doc_id"]}" title="{c.get("title", "")[:80]}" section="{c.get("section")}" '
              f'page="{c.get("page")}" authority_level="{c.get("authority_level")}" effective_from="{c.get("effective_from")}">\n'
              f'{c["text"][:900]}\n</untrusted_source>' for i, c in enumerate(srcs, 1)]
    user = (f"QUESTION: {s['question']}\nAS OF DATE: {s['as_of_date']}\n\nSOURCES (precedence order):\n" + "\n".join(blocks)
            + f"\n\nPRECEDENCE NOTES: {pol['decision']}\n\nTOOL RESULTS (computed by code, authoritative):\n"
            + json.dumps([{"tool": c["tool"], "output": c["output"]} for c in ok_tools], default=str))
    parsed, usage = _llm(s, COMPOSE_SYSTEM, user)
    return {"composed": {**(parsed or {"answer": "NOT_FOUND"}), "_srcs": srcs}, **usage,
            "timings": _timed("compose_ms", s, t)}


def finalize(s: State) -> State:
    """CODE decides answer_type and which citations are allowed — never the LLM."""
    pol, comp = s.get("policy") or {}, s.get("composed") or {}
    tools_used = s.get("tools_invoked") or []
    ok_tools = [c for c in tools_used if c["status"] == "ok"]
    citations, applied, conflicts = [], [], list(pol.get("conflicts", []))
    answer, explanation = "", ""
    if s.get("refused"):
        atype, answer = "refused", s["refused"]
    elif s.get("clarify"):
        atype, answer = "clarification_needed", s["clarify"]
    elif pol.get("unresolved"):
        atype = "conflict_flagged"
        answer = ("The authorised sources conflict and the precedence policy cannot decide between them. "
                  "Please contact the issuing office.")
        citations = [c for c in pol.get("applicable", [])][:2]
    elif str(comp.get("answer", "")).strip().upper().startswith("NOT_FOUND") or not comp.get("answer"):
        atype, answer = "not_found", config.NOT_FOUND_MSG
    else:
        atype = "calculated" if ok_tools else "retrieved_fact"
        # internal source labels (S1, S2) mean nothing to a student; citations are attached separately
        def unlabel(txt) -> str:
            t = re.sub(r"\bS\d+(?:\s*(?:,|;|&|and)\s*S\d+)*\b", "the cited clause", str(txt or ""))  # "S1 and S2"
            t = re.sub(r"\s*\((?:the cited clause\s*[,;&]?\s*)+\)", "", t)                       # "(S1; S2)" -> ""
            return t.strip()
        answer, explanation = unlabel(comp["answer"]), unlabel(comp.get("explanation", ""))
        if comp.get("assumptions") and s.get("category") == "multi_step":
            explanation += " Assumptions: " + "; ".join(map(str, comp["assumptions"]))
        srcs = comp.get("_srcs", [])
        used = [u for u in comp.get("used_sources", []) if isinstance(u, str) and re.fullmatch(r"S\d+", u)]
        citations = [srcs[int(u[1:]) - 1] for u in used if 0 < int(u[1:]) <= len(srcs)] or srcs[:1]
    rule_cites = []
    for c in ok_tools:
        o = c["output"] if isinstance(c["output"], dict) else {}
        for ru in o.get("rules_used", []):
            applied.append({"rule_id": ru["rule_id"], "value": ru["value"], "source_doc_id": ru["source_doc_id"]})
            src = retrieval.get_source(ru["source_doc_id"]) or {}
            page = next((ch.get("page") for ch in s.get("chunks", []) if ch["doc_id"] == ru["source_doc_id"]
                         and str(ch.get("section")) == str(ru["source_section"])), None)                 or retrieval.section_page(ru["source_doc_id"], ru["source_section"])
            rule_cites.append({"doc_id": ru["source_doc_id"], "title": src.get("title", ru["source_doc_id"]),
                               "section": ru["source_section"], "page": page, "version": src.get("version"),
                               "effective_from": src.get("effective_from")})
        conflicts += [x for x in o.get("conflicts", []) + [f"upcoming: {u}" for u in o.get("upcoming", [])] if x not in conflicts]
    if atype == "calculated":
        # a tool-based answer is supported by the rule clauses the tool used (traceable thresholds, R5), not by
        # whatever chunks the LLM happened to mention; record lookups alone (e.g. attendance %) need no clause
        citations = rule_cites
    cites = [{"doc_id": c["doc_id"], "title": c.get("title") or c["doc_id"], "section": str(c.get("section") or "") or None,
              "page": c.get("page"), "version": c.get("version") or None, "effective_from": c.get("effective_from") or None}
             for c in citations]
    unique, seen = [], set()
    for c in cites:                     # drop duplicate (doc, section) citations
        if (c["doc_id"], c["section"]) not in seen:
            seen.add((c["doc_id"], c["section"]))
            unique.append(c)
    cites = unique
    if atype in ("not_found", "refused", "clarification_needed"):
        cites = []
    resp = {"trace_id": s["trace_id"], "answer": answer, "answer_type": atype, "citations": cites,
            "tools_invoked": [{"tool": c["tool"], "input": c["input"], "output": c["output"]} for c in tools_used],
            "applied_rules": applied, "conflicts_detected": conflicts if atype not in ("refused", "clarification_needed") else [],
            "explanation": explanation, "as_of_date": s["as_of_date"]}
    latency = round((time.perf_counter() - s["t0"]) * 1000)
    audit.save({  # Annex D shape; no question text or names stored (R7: don't log personal data you don't need)
        "trace_id": s["trace_id"], "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "student_id": s.get("student_id"), "question_category": s.get("category", "refused" if s.get("refused") else None),
        "as_of_date": s["as_of_date"],
        "sources_retrieved": [{"doc_id": c["doc_id"], "section": c.get("section"), "score": c.get("score")} for c in s.get("chunks", [])],
        "precedence_decision": pol.get("decision"), "superseded": [f"{c['doc_id']}#{c.get('section')}" for c in pol.get("superseded", [])],
        "excluded_future": [f"{c['doc_id']}#{c.get('section')}" for c in pol.get("excluded_future", [])],
        "tools_invoked": [{"tool": c["tool"], "status": c["status"], "ms": c["ms"]} for c in tools_used],
        "applied_rules": applied, "conflicts_detected": resp["conflicts_detected"], "answer_type": atype,
        "citations": [f"{c['doc_id']}#{c['section']}" for c in cites], "model": s.get("model") or "none",
        "llm_calls": s.get("llm_calls", 0), "tokens": s.get("tokens", 0), "latency_ms": latency,
        "stage_ms": s.get("timings", {})})
    return {"response": resp}


# ---------------- graph ----------------
def build():
    g = StateGraph(State)
    for name, fn in [("authorise", authorise), ("classify", classify), ("retrieve", retrieve),
                     ("apply_policy", apply_policy), ("run_tools", run_tools), ("compose", compose), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.set_entry_point("authorise")
    g.add_conditional_edges("authorise", lambda s: "finalize" if s.get("refused") else "classify")
    g.add_conditional_edges("classify", lambda s: "finalize" if s.get("refused") else "retrieve")
    g.add_edge("retrieve", "apply_policy")
    g.add_edge("apply_policy", "run_tools")
    g.add_conditional_edges("run_tools", lambda s: "finalize" if s.get("clarify") else "compose")
    g.add_edge("compose", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = build()


def run(question: str, as_of_date: date | None, student_id: str | None) -> dict:
    state = GRAPH.invoke({"question": question, "student_id": student_id, "t0": time.perf_counter(),
                          "as_of_date": (as_of_date or date.today()).isoformat(), "trace_id": uuid.uuid4().hex[:8],
                          "llm_calls": 0, "tokens": 0, "timings": {}})
    return state["response"]
