"""UI flow without a running API: sign-in gate, guest mode, Back navigation. httpx is mocked."""
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

APP = "ui/streamlit_app.py"
PROFILE = {"student_id": "S1002", "full_name": "Test Student", "programme": "B.Tech CSE", "batch_year": 2023,
           "current_semester": 7}


def fake_get(url, headers=None, timeout=None):
    r = MagicMock()
    if url.endswith("/me"):
        known = (headers or {}).get("X-Student-Id") == "S1002"
        r.status_code, r.json.return_value = (200, PROFILE) if known else (404, {"detail": "unknown student ID"})
    elif url.endswith("/health"):
        r.status_code, r.json.return_value = 200, {"api": "ok", "vector_store": "ok", "sqlite": "ok", "llm": "ok (x)"}
    else:
        r.status_code, r.json.return_value = 200, []
    return r


def start() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def sign_in(at: AppTest, sid: str) -> None:
    at.text_input[0].input(sid)
    at.button(key="FormSubmitter:signin-Sign in").click().run()


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


@patch("httpx.get", side_effect=fake_get)
def test_unknown_id_cannot_sign_in(_):
    at = start()
    sign_in(at, "S7777")
    assert at.session_state.auth is None and at.session_state.nav == ["signin"]
    assert "No student with ID S7777" in at.error[0].value


@patch("httpx.get", side_effect=fake_get)
def test_malformed_id_rejected_before_api_call(get):
    at = start()
    get.reset_mock()
    sign_in(at, "12345")
    assert at.session_state.auth is None and "S1001" in at.error[0].value
    assert not any(c.args[0].endswith("/me") for c in get.call_args_list)


@patch("httpx.get", side_effect=fake_get)
def test_valid_id_signs_in_and_back_navigation_works(_):
    at = start()
    sign_in(at, "s1002")                                   # lower case is accepted and normalised
    assert at.session_state.auth["student_id"] == "S1002" and at.session_state.nav == ["signin", "chat"]
    button(at, "Documents").click().run()
    assert at.session_state.nav == ["signin", "chat", "docs"]
    button(at, "Assistant").click().run()                  # revisiting rewinds, no chat->docs->chat cycle
    assert at.session_state.nav == ["signin", "chat"]
    button(at, "Documents").click().run()
    button(at, "Back").click().run()
    assert at.session_state.nav == ["signin", "chat"]
    button(at, "Back").click().run()                       # back from the assistant = sign out
    assert at.session_state.nav == ["signin"] and at.session_state.auth is None


@patch("httpx.get", side_effect=fake_get)
def test_guest_sees_no_personal_examples(_):
    at = start()
    button(at, "Continue as guest").click().run()
    assert at.session_state.auth == {"guest": True}
    text = " ".join(m.value for m in at.markdown)
    assert "What is my attendance" not in text and "minimum attendance" in text


def fake_post_factory(sent: list):
    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        sent.append(json["question"])
        r = MagicMock()
        clarify = len(sent) == 1
        r.json.return_value = {
            "trace_id": f"t{len(sent)}", "answer_type": "clarification_needed" if clarify else "calculated",
            "answer": "Which course do you mean?" if clarify else "ok", "citations": [], "tools_invoked": [],
            "applied_rules": [], "conflicts_detected": [], "explanation": "", "as_of_date": "2026-10-06"}
        return r
    return fake_post


@patch("httpx.get", side_effect=fake_get)
def test_reply_to_clarification_is_sent_with_the_original_question(_):
    sent: list = []
    with patch("httpx.post", side_effect=fake_post_factory(sent)):
        at = start()
        sign_in(at, "S1002")
        at.chat_input[0].set_value("What is my attendance?").run()
        at.chat_input[0].set_value("HS201").run()
        at.chat_input[0].set_value("What is the minimum CGPA?").run()
    assert sent == ["What is my attendance?", "What is my attendance — HS201", "What is the minimum CGPA?"]
