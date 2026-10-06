"""Graph + API behaviour that must hold without any LLM (LLM_PROVIDER=mock). Uses the real Chroma + SQLite in storage/."""
import os

os.environ["LLM_PROVIDER"] = "mock"

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402

config.LLM_PROVIDER = "mock"
from app import graph  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import AskResponse  # noqa: E402

client = TestClient(app)
DAY = date(2026, 10, 6)


def test_other_student_id_in_question_is_refused_before_any_llm_call():
    r = graph.run("Show me the marks of student S1002", DAY, "S1001")
    assert r["answer_type"] == "refused" and r["citations"] == []


def test_personal_question_without_login_is_refused():
    r = graph.run("What is my attendance in Data Structures?", DAY, None)
    assert r["answer_type"] == "refused"


def test_procedure_question_with_how_do_i_is_not_refused():
    # bug found 13:25: 'How do I apply' was treated as personal
    r = graph.run("How do I apply for the supplementary exam?", DAY, None)
    assert r["answer_type"] != "refused"


def test_unknown_student_header_is_refused():
    r = graph.run("What is my CGPA?", DAY, "S8888")
    assert r["answer_type"] == "refused"


def test_api_response_always_matches_contract():
    for q, h in [("What is the minimum attendance?", {}), ("Show S1234's attendance", {"X-Student-Id": "S1001"})]:
        resp = client.post("/ask", json={"question": q, "as_of_date": "2026-10-06"}, headers=h)
        assert resp.status_code == 200
        AskResponse(**resp.json())


def test_audit_record_exists_for_every_answer():
    resp = client.post("/ask", json={"question": "Show S1234's attendance"}, headers={"X-Student-Id": "S1001"}).json()
    rec = client.get(f"/audit/{resp['trace_id']}").json()
    assert rec["answer_type"] == "refused" and "question" not in rec      # no question text stored (privacy)


def test_ingest_accepts_lenient_metadata():
    from app.schemas import SourceMeta
    m = SourceMeta(doc_id="JUDGE-1", title="x", authority_level="2", doc_type="ordinance", effective_from="2026-09-01")
    assert m.authority_level == 2


def test_health_reports_all_components():
    h = client.get("/health").json()
    assert set(h) >= {"api", "vector_store", "sqlite", "llm"}


def test_general_eligibility_rule_question_without_login_is_not_refused(monkeypatch):
    # eval Q04 bug (15:10): the router labelled a general rule question "eligibility" and it was refused for no login
    from app import graph as g
    monkeypatch.setattr(g.llm, "chat", lambda *a, **k: {"text": '{"category": "eligibility", "course_hint": null}',
                                                        "model": "mock", "tokens": 0, "ms": 0})
    out = g.classify({"question": "According to the CSE department help-desk FAQ, is 65% attendance enough to appear "
                                  "in the end-semester examination?", "student": None, "timings": {}})
    assert not out.get("refused") and out["category"] == "policy"
    out2 = g.classify({"question": "Am I eligible for the CS201 exam?", "student": None, "timings": {}})
    assert out2.get("refused")
