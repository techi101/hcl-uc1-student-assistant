"""The ONE fixed LangGraph workflow (CONTRACT.md section 1). Owner: C.
Simple on purpose: each step is deterministic code except classify + compose (LLM)."""
import uuid
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app import config, precedence, retrieval


class State(TypedDict, total=False):
    question: str
    as_of_date: str
    student_id: str | None
    trace_id: str
    chunks: list[dict]
    policy: dict
    tools_invoked: list[dict]
    response: dict[str, Any]


def retrieve(s: State) -> State:
    return {"chunks": retrieval.search(s["question"], config.TOP_K)}


def apply_policy(s: State) -> State:
    return {"policy": precedence.resolve(s["chunks"], s["as_of_date"], None)}


def finalize(s: State) -> State:
    # stub: until retrieval + compose land, everything is not_found
    resp = {"trace_id": s["trace_id"], "answer": config.NOT_FOUND_MSG, "answer_type": "not_found",
            "citations": [], "tools_invoked": [], "applied_rules": [], "conflicts_detected": [],
            "explanation": "", "as_of_date": s["as_of_date"]}
    return {"response": resp}


def build():
    g = StateGraph(State)
    g.add_node("retrieve", retrieve)
    g.add_node("apply_policy", apply_policy)
    g.add_node("finalize", finalize)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "apply_policy")
    g.add_edge("apply_policy", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = build()


def run(question: str, as_of_date: date | None, student_id: str | None) -> dict:
    state = GRAPH.invoke({"question": question, "student_id": student_id,
                          "as_of_date": (as_of_date or date.today()).isoformat(),
                          "trace_id": uuid.uuid4().hex[:8]})
    return state["response"]
