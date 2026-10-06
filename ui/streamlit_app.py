"""Streamlit UI for the NSUT Student Services Assistant. Talks ONLY to the FastAPI contract (Section 6).
Run: streamlit run ui/streamlit_app.py      (API must be running: uvicorn app.main:app --port 8000)
HCL scores the UI only for usability, so every panel here answers one judge question:
what kind of answer is this, where did it come from, which rule won and why, what did code compute, what did it cost."""
# WHAT THIS FILE IS: the web screen a student or judge clicks on. It has NO logic of its own.
# It only sends HTTP requests to our FastAPI server (the "API") and draws the reply nicely.
# Real example: you type "What is my attendance in Data Structures?" with Student ID S1002 in the sidebar.
# This file POSTs {"question": ..., "as_of_date": "2026-10-06"} to /ask with the header X-Student-Id: S1002,
# gets back answer_type "calculated" + citations, then fetches /audit/<trace_id> and fills the tabs.
# Judges test the API directly, so every decision (who you are, which rule wins, the maths) lives in app/, not here.
# Streamlit = a Python library that turns a plain script into a web page. Every click re-runs this WHOLE file
# from top to bottom (a "rerun"). Anything that must survive a rerun is kept in st.session_state
# (a dictionary Streamlit keeps alive between reruns, one per browser tab).
# html = escape text ("<" becomes "&lt;") so it shows as text, not as HTML. json = dicts <-> JSON text.
# re = regular expressions (text patterns). os = read environment variables. date = today's date.
import html
import json
import re
import os
from datetime import date

# httpx = a library for sending HTTP requests (same style as the popular "requests" library: httpx.get / httpx.post).
# pandas (pd) = tables (DataFrames) that Streamlit can draw as grids and charts. streamlit (st) = the UI library.
import httpx
import pandas as pd
import streamlit as st

# Browser tab title + icon, and "wide" layout so answers and tabs use the full screen width.
# This must be the first Streamlit command in the file.
st.set_page_config(page_title="NSUT Student Services Assistant", page_icon="🎓", layout="wide")

# Example: "calculated" -> green pill "Calculated by code"; "refused" -> red pill "Refused".
# answer_type -> (label, text colour, background) so a judge sees at a glance WHAT KIND of answer this is (R9)
BADGES = {
    "retrieved_fact": ("From documents", "#1D4ED8", "#DBEAFE"),
    "calculated": ("Calculated by code", "#047857", "#D1FAE5"),
    "not_found": ("Not in authorised sources", "#4B5563", "#E5E7EB"),
    "clarification_needed": ("Needs clarification", "#B45309", "#FEF3C7"),
    "refused": ("Refused", "#B91C1C", "#FEE2E2"),
    "conflict_flagged": ("Unresolved conflict", "#7C3AED", "#EDE9FE"),
}
# Lower number = stronger. A level 2 circular beats a level 4 FAQ.
# Annex A authority levels, shown next to every source so precedence decisions are readable
LEVELS = {1: "Regulation", 2: "Official circular", 3: "Dept notice", 4: "FAQ / handbook", 5: "Unofficial"}

# CSS = the styling rules (colours, fonts, spacing) for the page. Each ".name" is a class used in the HTML below,
# e.g. ".cite" draws the white citation card with a blue left border, ".pill" draws the coloured answer badge.
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stTextInput, .stButton button { font-family: 'Inter', sans-serif; }
.block-container { padding-top: 1.6rem; max-width: 1180px; }
.hero { background: linear-gradient(120deg, #312E81 0%, #4338CA 55%, #6366F1 100%); color: #fff;
        border-radius: 16px; padding: 22px 26px; margin-bottom: 18px; }
.hero h1 { color: #fff; font-size: 1.65rem; font-weight: 700; margin: 0 0 4px 0; padding: 0; }
.hero p { color: #E0E7FF; margin: 0; font-size: .93rem; }
.status { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.status span { background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25); border-radius: 999px;
               padding: 3px 11px; font-size: .78rem; color: #fff; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.pill { display: inline-block; border-radius: 999px; padding: 3px 11px; font-size: .78rem; font-weight: 600; }
.meta { color: #6B7280; font-size: .78rem; margin-left: 8px; }
.answer { font-size: 1.08rem; line-height: 1.55; color: #111827; margin: 10px 0 6px 0; }
.why { color: #4B5563; font-size: .9rem; border-left: 3px solid #C7D2FE; padding-left: 10px; margin: 8px 0 12px 0; }
.callout { background: #F5F3FF; border: 1px solid #DDD6FE; border-radius: 10px; padding: 10px 14px;
           font-size: .86rem; color: #4C1D95; margin: 8px 0; }
.cite { background: #fff; border: 1px solid #E4E4EE; border-left: 4px solid #4338CA; border-radius: 10px;
        padding: 10px 14px; margin: 6px 0; }
.cite b { color: #111827; font-size: .9rem; }
.cite .sub { color: #6B7280; font-size: .78rem; margin-top: 3px; }
.tag { display: inline-block; background: #EEF2FF; color: #3730A3; border-radius: 6px; padding: 1px 7px;
       font-size: .72rem; font-weight: 600; margin-right: 6px; }
.tag.syn { background: #FEF3C7; color: #92400E; }
.src { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid #F0F0F5; font-size: .84rem; }
.src .name { flex: 1; }
.src .bar { width: 120px; height: 6px; background: #EEF2FF; border-radius: 4px; overflow: hidden; }
.src .bar i { display: block; height: 100%; background: #6366F1; }
.src .st { width: 128px; text-align: right; font-size: .74rem; font-weight: 600; }
.step { font-size: .85rem; padding: 6px 0; color: #374151; }
.toolcard { background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 10px; padding: 10px 14px; margin: 6px 0; }
.toolcard code { font-size: .78rem; }
.who { background: #fff; border: 1px solid #E4E4EE; border-radius: 12px; padding: 12px 14px; margin: 4px 0 10px 0; }
.who .lbl { color: #6B7280; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; }
.who .val { font-weight: 600; font-size: 1rem; margin-top: 2px; }
div[data-testid="stChatMessage"] { background: #fff; border: 1px solid #ECECF3; border-radius: 14px; padding: 14px 16px; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
</style>
"""
# st.markdown draws text. unsafe_allow_html=True lets it draw HTML/CSS. We only pass HTML that WE wrote,
# and every outside text inside it is escaped first (see esc below).
st.markdown(CSS, unsafe_allow_html=True)
# esc is a short name for html.escape. Every piece of text that came from the API or a document goes through esc()
# first, so a document containing "<script>" shows as plain text and cannot run (R8: document text is data).
esc = html.escape  # document text is untrusted (R8): never render it as raw HTML


# ---------------- API helpers ----------------
# IN: an API path like "/health"  ->  OUT: the JSON reply as a Python dict.
# Example: api_get("/audit/3f9a1c2b") -> GET http://localhost:8000/audit/3f9a1c2b -> {"latency_ms": 5400, ...}
# st.session_state.api holds the API address (set in the sidebar Settings box).
def api_get(path: str, timeout: float = 10):
    return httpx.get(f"{st.session_state.api}{path}", timeout=timeout).json()


# IN: the API address  ->  OUT: {doc_id: that document's row from GET /sources}.
# Example: {"SYN-CIRC-ATT-2026": {"authority_level": 2, "synthetic": "Y", ...}, ...}
# @st.cache_data(ttl=30) = Streamlit remembers the result for 30 seconds, so /sources is not called on every rerun.
# After a new document is ingested we clear this memory (load_sources.clear()) so the new document shows at once.
@st.cache_data(ttl=30, show_spinner=False)
def load_sources(api: str) -> dict:
    """doc_id -> register row, so citations can show authority level and synthetic flag."""
    try:
        # Turn the list of rows into a dict keyed by doc_id, so looking up a citation's document is instant.
        return {r["doc_id"]: r for r in httpx.get(f"{api}/sources", timeout=10).json()}
    # API down or bad reply -> empty dict. The page still works; citation cards just lose their level tags.
    except Exception:
        return {}


# ---------------- sidebar: who is asking, as of when ----------------
# Remember the API address. setdefault = set it only if it is not set yet, so a value typed in Settings survives reruns.
# Default: the API_URL environment variable (used inside Docker), else localhost port 8000.
st.session_state.setdefault("api", os.getenv("API_URL", "http://localhost:8000"))
# "with st.sidebar:" = everything inside this block is drawn in the left sidebar.
with st.sidebar:
    st.markdown("### 🎓 Who's asking")
    # Student ID box. Whatever is typed here is sent as the X-Student-Id header on /ask.
    # Empty = guest: the API answers rule questions but refuses "my attendance" style questions.
    # The API never reads identity from the question text (R7), so typing "I am S1001" in the chat changes nothing.
    # .strip() removes spaces typed by mistake.
    student_id = st.text_input("Student ID", placeholder="e.g. S1001  (empty = guest)",
                               help="Sent as the X-Student-Id header. Identity is never read from the question text (R7).").strip()
    # A small card showing who is signed in, so a judge always knows which identity the next question uses.
    st.markdown(f"<div class='who'><div class='lbl'>Signed in as</div><div class='val'>"
                f"{'🧑‍🎓 ' + esc(student_id) if student_id else '👤 Guest — rules only'}</div></div>",
                unsafe_allow_html=True)
    # "Answer as of" date. The API applies rules as they stood on this date (Annex A step 1, applicability).
    # Example: 6 Oct 2026 -> the circular's 80% is in force. 15 Jul 2026 -> the regulation's 75% applies
    # and the 80% circular is shown as "upcoming".
    as_of = st.date_input("Answer as of", value=date.today(),
                          help="Rules are applied as they stood on this date (Annex A applicability). "
                               "Try a date before a circular took effect to see the older rule.")
    # st.divider() draws a thin horizontal line.
    st.divider()
    # Clear chat: st.button returns True on the rerun right after it is clicked, so we empty the saved messages.
    # width="stretch" = the button fills the sidebar width.
    if st.button("🗑️  Clear chat", width="stretch"):
        st.session_state.messages = []
    # st.expander = a collapsible box. Hidden Settings: change the API URL (e.g. to a teammate's laptop) without editing code.
    with st.expander("⚙️ Settings"):
        st.session_state.api = st.text_input("API URL", st.session_state.api)

# ---------------- header with live health ----------------
# Call GET /health and turn each component into a small "chip". Example reply:
# {"api": "ok", "vector_store": "ok", "sqlite": "ok", "llm": "mock"}.
# Green dot if the value starts with "ok" (or is "mock"), amber dot otherwise (e.g. "down: ..." or "empty").
try:
    health = api_get("/health", timeout=5)
    # One <span> per component: dot colour, name ("vector_store" -> "vector store"), value without the "ok" prefix.
    pills = "".join(
        f"<span><i class='dot' style='background:{'#34D399' if str(v).startswith('ok') or v == 'mock' else '#FBBF24'}'></i>"
        f"{esc(k.replace('_', ' '))}: {esc(str(v).removeprefix('ok').strip(' ()') or 'ok')}</span>"
        for k, v in health.items())
# API not running -> one red chip saying so, instead of crashing the page.
except Exception:
    pills = f"<span><i class='dot' style='background:#F87171'></i>API not reachable at {esc(st.session_state.api)}</span>"
# The purple header ("hero"): title, the one-line promise, and the live health chips.
st.markdown(f"""<div class='hero'><h1>NSUT Student Services Assistant</h1>
<p>Answers only from authorised NSUT documents and your own records. Every fact is cited;
eligibility and numbers are computed by code, never by the AI.</p><div class='status'>{pills}</div></div>""",
            unsafe_allow_html=True)


# ---------------- answer rendering ----------------
# IN: an answer_type like "refused"  ->  OUT: HTML for a coloured badge, e.g. a red "Refused" pill.
# Unknown answer_type -> grey badge showing the raw value, so nothing is hidden.
def pill(answer_type: str) -> str:
    label, fg, bg = BADGES.get(answer_type, (answer_type or "?", "#374151", "#E5E7EB"))
    return f"<span class='pill' style='color:{fg};background:{bg}'>{esc(label)}</span>"


# IN: the answer's citations + the source register  ->  OUT: nothing returned; draws one card per citation.
# Each card: authority tag ("L2 · Official circular"), a yellow "synthetic" tag for made-up test documents,
# then title, doc_id, section, page, version and effective date.
# Example: "L2 · Official circular | synthetic | SYN-CIRC-ATT-2026 · § 1 · effective 2026-08-01".
def render_citations(citations: list, sources: dict) -> None:
    for c in citations:
        # Look up this citation's document in the register to get its authority level and synthetic flag.
        reg = sources.get(c["doc_id"], {})
        lvl = reg.get("authority_level")
        tags = f"<span class='tag'>L{lvl} · {LEVELS.get(lvl, '')}</span>" if lvl else ""
        tags += "<span class='tag syn'>synthetic</span>" if reg.get("synthetic") == "Y" else ""
        # Join only the parts that exist, with " · " between them. "§" means section.
        where = " · ".join(x for x in [
            f"§ {c['section']}" if c.get("section") else "", f"page {c['page']}" if c.get("page") else "",
            f"version {c['version']}" if c.get("version") else "",
            f"effective {c['effective_from']}" if c.get("effective_from") else ""] if x)
        # Draw the card. Every piece of outside text goes through esc() first.
        st.markdown(f"<div class='cite'>{tags}<b>{esc(c.get('title') or c['doc_id'])}</b>"
                    f"<div class='sub'><code>{esc(c['doc_id'])}</code> · {esc(where)}</div></div>",
                    unsafe_allow_html=True)


# IN: the audit record + the set of cited "doc_id#section" keys  ->  OUT: draws the "Sources & precedence" tab.
# One row per retrieved chunk: its name, a score bar, the score number, and its fate under Annex A.
def render_precedence(audit: dict, cited: set) -> None:
    """Every retrieved chunk with its score and fate under Annex A: cited, superseded, not yet effective, or context."""
    # From the audit record: chunks that lost to a superseding document, and chunks not yet effective on the as-of date.
    superseded, future = set(audit.get("superseded", [])), set(audit.get("excluded_future", []))
    rows = ""
    for s in audit.get("sources_retrieved", []):
        # Key like "NSUT-BTECH-REG-2019#11.2" = document + section, the same format as the cited set.
        key = f"{s['doc_id']}#{s.get('section', '')}"
        # Decide the status, checked in this order: cited (used in the answer, green), superseded (red, struck through),
        # not yet effective (amber), else just "retrieved" (grey: found by search but not needed).
        if key in cited:
            status, col = "✓ cited", "#047857"
        elif key in superseded or s["doc_id"] in superseded:
            status, col = "superseded", "#B91C1C"
        elif key in future or s["doc_id"] in future:
            status, col = "not yet effective", "#B45309"
        else:
            status, col = "retrieved", "#6B7280"
        # <s> = strike-through, so a superseded rule looks crossed out.
        name = f"<s>{esc(key)}</s>" if status == "superseded" else esc(key)
        # Score bar width: similarity score 0.62 -> 62%, kept between 0 and 100.
        pct = max(0, min(100, int(float(s.get("score", 0)) * 100)))
        # Build this row's HTML and add it to the rest.
        rows += (f"<div class='src'><span class='name'><code>{name}</code></span>"
                 f"<span class='bar'><i style='width:{pct}%'></i></span><span style='width:38px;font-size:.74rem'>"
                 f"{s.get('score', 0):.2f}</span><span class='st' style='color:{col}'>{status}</span></div>")
    # Draw all rows, or a grey note if nothing was retrieved.
    st.markdown(rows or "<span class='meta'>No documents retrieved.</span>", unsafe_allow_html=True)
    # The API's precedence decision text, e.g. "SYN-CIRC-ATT-2026 supersedes NSUT-BTECH-REG-2019#11.2 (step 2); ...".
    # We split it into one line per decision so a judge can read which rule won and why.
    # The pattern "; (?=[A-Z])" means: split at "; " only when a capital letter follows (the start of a new decision).
    if audit.get("precedence_decision"):
        st.markdown("**Which rule won, and why (Annex A)**")
        for part in re.split(r"; (?=[A-Z])", audit["precedence_decision"]):  # split decisions, not clauses
            st.markdown(f"<div class='step'>⚖️ {esc(part)}</div>", unsafe_allow_html=True)


# IN: the /ask response  ->  OUT: draws the "Tools & rules" tab.
# One green card per code tool that ran (e.g. check_exam_eligibility, input {"student_id": "S1002", "course_code": "CS201"}),
# then its output, then every rule row used (e.g. ATT-MIN-02 ">=" 80 from SYN-CIRC-ATT-2026).
def render_tools(resp: dict) -> None:
    for t in resp.get("tools_invoked", []):
        out = t.get("output")
        st.markdown(f"<div class='toolcard'>🧮 <b>{esc(t.get('tool', ''))}</b>"
                    f"<div class='sub'>input <code>{esc(json.dumps(t.get('input', {})))}</code></div></div>",
                    unsafe_allow_html=True)
        # Flat output (no nested dicts or lists) -> show it as a one-row table. Nested output -> collapsible JSON viewer.
        if isinstance(out, dict) and all(not isinstance(v, (dict, list)) for v in out.values()):
            st.dataframe(pd.DataFrame([out]), hide_index=True, width="stretch")
        else:
            st.json(out, expanded=False)
    # Rules the API applied, straight from the rule_registry table. This shows the threshold came from data, not code.
    for r in resp.get("applied_rules", []):
        st.markdown(f"<div class='step'>📏 Rule <b>{esc(r['rule_id'])}</b> &nbsp;<code>{esc(str(r['value']))}</code>"
                    f" &nbsp;from <code>{esc(r['source_doc_id'])}</code></div>", unsafe_allow_html=True)


# IN: the audit record  ->  OUT: draws the "Audit" tab, i.e. what this answer cost.
# st.columns(4) = split the row into 4 side-by-side boxes. st.metric = a big number with a small label.
# Example: Latency 5.4 s · LLM calls 2 · Tokens 1830 · Chunks retrieved 6. A refusal shows 0 LLM calls.
def render_audit(audit: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latency", f"{audit.get('latency_ms', 0) / 1000:.1f} s")
    c2.metric("LLM calls", audit.get("llm_calls", "–"))
    c3.metric("Tokens", audit.get("tokens", "–"))
    c4.metric("Chunks retrieved", len(audit.get("sources_retrieved", [])))
    # Which model answered, and which category the router chose (policy, personal, eligibility, ...).
    st.caption(f"Model: `{audit.get('model', '–')}` · category: `{audit.get('question_category', '–')}`")
    # Stage timings, e.g. {"authorise_ms": 3, "retrieve_ms": 220, "compose_ms": 4800}, drawn as a horizontal bar chart
    # so a judge sees where the time went (almost always the LLM). The "_ms" ending is removed from the labels.
    stages = audit.get("stage_ms") or {}
    if stages:
        df = pd.DataFrame({"stage": [k.removesuffix("_ms") for k in stages], "ms": list(stages.values())})
        st.bar_chart(df, x="stage", y="ms", horizontal=True, height=200, color="#6366F1", sort=False)
    # The full raw audit JSON, hidden in a collapsible box, for anyone who wants every field.
    with st.expander("Raw audit record (GET /audit)"):
        st.json(audit, expanded=False)


# IN: one /ask response + its audit record (or None)  ->  OUT: draws the whole answer block.
# Order: badge + date + trace id, the answer, the "why" line, conflict boxes, citation cards, then the tabs.
def render_answer(resp: dict, audit: dict | None) -> None:
    st.markdown(f"{pill(resp.get('answer_type'))}<span class='meta'>as of {esc(resp.get('as_of_date', ''))}"
                f" · trace <code>{esc(resp.get('trace_id', ''))}</code></span>", unsafe_allow_html=True)
    # The answer text itself, escaped.
    st.markdown(f"<div class='answer'>{esc(resp.get('answer', ''))}</div>", unsafe_allow_html=True)
    # The explanation line, shown only if it says something beyond the answer.
    if resp.get("explanation") and resp["explanation"] != resp.get("answer"):
        st.markdown(f"<div class='why'>💡 {esc(resp['explanation'])}</div>", unsafe_allow_html=True)
    # One purple box per conflict the API found, e.g. "the CSE FAQ says 65%, overridden by the circular's 80% (step 3)".
    for c in resp.get("conflicts_detected", []):
        st.markdown(f"<div class='callout'>⚠️ {esc(c)}</div>", unsafe_allow_html=True)
    # Citation cards. load_sources gives the register so each card can show its L1-L5 tag.
    if resp.get("citations"):
        render_citations(resp["citations"], load_sources(st.session_state.api))

    # Tabs. "Tools & rules" appears only when code tools or rule rows were used (a pure policy answer has none).
    # st.tabs(names) returns one tab object per name; zip + dict lets us pick a tab by its name.
    names = ["📚 Sources & precedence"]
    has_tools = bool(resp.get("tools_invoked") or resp.get("applied_rules"))
    names += ["🧮 Tools & rules"] if has_tools else []
    names += ["🔎 Audit"]
    tabs = dict(zip(names, st.tabs(names)))
    # Set of "doc_id#section" keys the answer cited, so the precedence tab can mark them as cited.
    cited = {f"{c['doc_id']}#{c.get('section', '')}" for c in resp.get("citations", [])}
    # "with <tab>:" = everything inside this block is drawn inside that tab.
    with tabs["📚 Sources & precedence"]:
        if audit:
            render_precedence(audit, cited)
        else:
            st.caption("Audit record not available.")
    if has_tools:
        with tabs["🧮 Tools & rules"]:
            st.caption("Computed by code over SQLite and the rule registry, not by the AI (R5).")
            render_tools(resp)
    with tabs["🔎 Audit"]:
        if audit:
            render_audit(audit)
        else:
            st.caption("Audit record not available.")


# IN: the question text  ->  OUT: (the /ask response, the audit record or None).
# This is the ONLY place the UI talks to /ask. Example request:
# POST /ask  body {"question": "Am I eligible for CS201?", "as_of_date": "2026-10-06"}  header X-Student-Id: S1001.
def ask(question: str) -> tuple[dict, dict | None]:
    # Identity goes ONLY in the header. Guest -> no header at all.
    headers = {"X-Student-Id": student_id} if student_id else {}
    # timeout=300 seconds, because a local LLM on a laptop can be slow.
    r = httpx.post(f"{st.session_state.api}/ask", json={"question": question, "as_of_date": as_of.isoformat()},
                   headers=headers, timeout=300)
    # raise_for_status() = turn an HTTP error (like 500) into a Python exception; the caller shows it as "Request failed".
    r.raise_for_status()
    resp = r.json()
    # Then fetch the audit record for this trace_id (latency, tokens, sources, precedence decision).
    try:  # fetched once and stored, so reruns don't re-hit the API
        audit = api_get(f"/audit/{resp['trace_id']}")
    except Exception:
        audit = None
    return resp, audit


# Page switch at the top: "Ask" (chat) or "Documents" (live ingest + source register).
# st.segmented_control = a row of toggle buttons. If nothing is selected it returns None, so "or" falls back to Ask.
page = st.segmented_control("Page", ["💬 Ask", "📚 Documents"], default="💬 Ask",
                            label_visibility="collapsed") or "💬 Ask"

# ---------------- chat ----------------
# Example question cards shown on an empty chat. Each pair is (card label, question text).
EXAMPLES = [  # one per question type in Section 2.1, so a judge can try each with one click
    ("📄 Policy fact", "What is the minimum attendance required to appear for end-semester exams?"),
    ("📝 Procedure", "How do I apply for the supplementary exam?"),
    ("📊 My data", "What is my attendance in Data Structures?"),
    ("✅ My eligibility", "Am I eligible to appear in the end-semester exam for CS201?"),
    ("🔀 What-if", "I failed Data Structures. If I pass the supplementary, will I be eligible for placement?"),
    ("❔ Not answerable", "What is the scholarship for studying in Antarctica?"),
]


# IN: a question  ->  OUT: nothing; saves it as "pending" in session_state.
# The card's button calls this BEFORE the rerun, so on the rerun the question is picked up and the cards disappear.
def queue(q: str) -> None:  # button callback: runs before the rerun, so the cards can hide immediately
    st.session_state.pending = q


# ---- Chat page ----
if page == "💬 Ask":
    # Chat history lives in session_state["messages"], so it survives reruns. Each item is a user line or an assistant answer.
    st.session_state.setdefault("messages", [])
    # st.chat_input = the message box pinned to the bottom. It returns the typed text once, on the rerun after Enter.
    typed = st.chat_input("Ask about NSUT rules, or your own attendance / eligibility…")  # top level = pinned bottom
    # The question for this rerun: typed text, or a clicked example card. pop() removes "pending" so it is asked only once.
    question = typed or st.session_state.pop("pending", None)
    # Empty chat and no question yet -> show the 6 example cards in 2 rows of 3.
    # st.columns(3) = 3 side-by-side columns. container(border=True) = a card with a border.
    if not st.session_state.messages and not question:
        st.markdown("##### Try a question")
        for row in (EXAMPLES[:3], EXAMPLES[3:]):
            for col, (label, q) in zip(st.columns(3), row):
                with col.container(border=True, height="stretch"):
                    st.markdown(f"**{label}**  \n<span class='meta' style='margin:0'>{esc(q)}</span>",
                                unsafe_allow_html=True)
                    st.button("Ask this", key=label, width="stretch", on_click=queue, args=(q,))

    # Redraw the whole chat history (the file re-runs, so old messages must be drawn again every time).
    # st.chat_message = a chat bubble with an avatar. Old answers are redrawn from the saved response, without calling the API again.
    for m in st.session_state.messages:
        with st.chat_message(m["role"], avatar="🧑‍🎓" if m["role"] == "user" else "🎓"):
            if m["role"] == "assistant":
                render_answer(m["resp"], m.get("audit"))
            else:
                st.markdown(m["text"], unsafe_allow_html=True)

    # A new question arrived: show it, call the API, show the answer, save both to history.
    if question:
        # Show who asked (the Student ID or "guest") under the question, so identity is always visible.
        who = esc(student_id) if student_id else "guest"
        text = f"{esc(question)}  \n<span class='meta' style='margin:0'>as {who}</span>"
        st.session_state.messages.append({"role": "user", "text": text})
        with st.chat_message("user", avatar="🧑‍🎓"):
            st.markdown(text, unsafe_allow_html=True)
        with st.chat_message("assistant", avatar="🎓"):
            # st.status = a box with a spinner and a label. The label lists the API's real steps in order.
            with st.status("Checking identity → searching documents → applying precedence → running tools…") as s:
                # Call the API. Success -> mark the box "Done". Any failure (API down, timeout, 500) -> red box with the error, no crash.
                try:
                    resp, audit = ask(question)
                    s.update(label="Done", state="complete")
                except Exception as e:
                    s.update(label=f"Request failed: {e}", state="error")
                    resp = None
            # Draw the answer and save it (with its audit record) so later reruns redraw it without calling the API.
            if resp:
                render_answer(resp, audit)
                st.session_state.messages.append({"role": "assistant", "resp": resp, "audit": audit})

# ---------------- documents: live ingestion + source register ----------------
# ---- Documents page ----
if page == "📚 Documents":
    # Summary numbers on top: documents, chunks in the search index, authority levels present, synthetic docs.
    sources = load_sources(st.session_state.api)
    if sources:
        rows = list(sources.values())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Documents", len(rows))
        c2.metric("Chunks indexed", sum(int(r.get("chunks_indexed") or 0) for r in rows))
        c3.metric("Issuing authority levels", len({r.get("authority_level") for r in rows}))
        c4.metric("Synthetic docs", sum(r.get("synthetic") == "Y" for r in rows))

    # Live ingest form. A judge can upload a document they wrote (e.g. a new circular) while everything is running.
    # expanded=not sources -> the form starts open only if there are no documents yet.
    # st.form = groups the inputs so nothing is sent until "Ingest document" is pressed (no rerun on every keystroke).
    with st.expander("➕  Add a document while the system is running (POST /ingest)", expanded=not sources):
        with st.form("ingest", border=False):
            # File picker: PDF (text or scanned; scanned pages go through OCR in the API), DOCX, TXT or MD.
            f = st.file_uploader("Document — PDF (text or scanned), DOCX, TXT, MD", type=["pdf", "docx", "txt", "md"])
            # The metadata the precedence policy needs, laid out 3 per row. Fields with * are required.
            # Example: doc_id ACAD-2026-08, authority_level 2, effective_from 2026-08-01, supersedes NSUT-BTECH-REG-2019#11.2.
            c1, c2, c3 = st.columns(3)
            doc_id = c1.text_input("doc_id *", placeholder="ACAD-2026-08")
            title = c2.text_input("title *")
            issuer = c3.text_input("issuer", placeholder="Office of the Dean (Academics)")
            c4, c5, c6 = st.columns(3)
            # format_func shows "2 · Official circular" in the dropdown, but the value kept is just 2.
            level = c4.selectbox("authority_level *", [1, 2, 3, 4, 5], index=1,
                                 format_func=lambda x: f"{x} · {LEVELS[x]}")
            doc_type = c5.selectbox("doc_type", ["regulation", "circular", "notice", "faq", "handbook", "unofficial"],
                                    index=1)
            version = c6.text_input("version")
            c7, c8, c9 = st.columns(3)
            eff_from = c7.date_input("effective_from *", value=date.today())
            eff_to = c8.text_input("effective_to", placeholder="YYYY-MM-DD or empty")
            # supersedes = "doc_id#section" of the clause this document replaces.
            # Only levels 1-2 may supersede (Annex A step 2); the API enforces that, not this form.
            supersedes = c9.text_input("supersedes", placeholder="NSUT-BTECH-REG-2019#11.2")
            c10, c11, c12 = st.columns(3)
            scope_p = c10.text_input("scope_programmes", "ALL")
            scope_b = c11.text_input("scope_batches", "ALL")
            synthetic = c12.selectbox("synthetic", ["N", "Y"])
            provenance = st.text_input("provenance (URL / source)")
            submitted = st.form_submit_button("Ingest document", type="primary")
        # After the button is pressed: check the 3 required fields, then send everything to POST /ingest.
        if submitted:
            if not (f and doc_id and title):
                st.error("File, doc_id and title are required.")
            else:
                # All metadata goes as one JSON string in a form field named "metadata"; the file goes as a multipart upload.
                # retrieved_on = today, recorded for provenance.
                meta = {"doc_id": doc_id, "title": title, "issuer": issuer, "authority_level": level,
                        "doc_type": doc_type, "version": version, "effective_from": eff_from.isoformat(),
                        "effective_to": eff_to, "supersedes": supersedes, "scope_programmes": scope_p,
                        "scope_batches": scope_b, "provenance": provenance,
                        "retrieved_on": date.today().isoformat(), "synthetic": synthetic}
                # The API extracts text (OCR if scanned), splits it into chunks, embeds them into the vector store, and extracts rule rows.
                # timeout=600 seconds, because OCR of a scanned PDF can take minutes.
                with st.status("Extracting text (OCR if scanned) → chunking → embedding → extracting rules…") as s:
                    try:
                        r = httpx.post(f"{st.session_state.api}/ingest", files={"file": (f.name, f.getvalue())},
                                       data={"metadata": json.dumps(meta)}, timeout=600)
                        # 200 = success: show the API's summary and clear the cached source list so the new document appears at once.
                        # Anything else: show the status code and the first 300 characters of the error.
                        if r.status_code == 200:
                            s.update(label=f"Ingested: {r.json()}", state="complete")
                            load_sources.clear()
                        else:
                            s.update(label=f"{r.status_code}: {r.text[:300]}", state="error")
                    except Exception as e:
                        s.update(label=f"Ingest failed: {e}", state="error")

    # Source Register table (GET /sources): every ingested document with the fields the precedence policy uses.
    st.markdown("#### Source Register")
    st.caption("GET /sources — every ingested document with the metadata the precedence policy uses.")
    if sources:
        # Add a readable "authority" column ("L2 · Official circular"), keep only columns that exist, sort so L1 comes first.
        # column_config: a wide title column, provenance as a clickable link, shorter column names.
        df = pd.DataFrame(list(sources.values()))
        df["authority"] = df["authority_level"].map(lambda x: f"L{x} · {LEVELS.get(x, '')}")
        cols = ["doc_id", "title", "authority", "doc_type", "version", "effective_from", "effective_to",
                "supersedes", "scope_programmes", "scope_batches", "synthetic", "chunks_indexed", "ocr_pages",
                "provenance"]
        st.dataframe(df[[c for c in cols if c in df.columns]].sort_values("authority"), width="stretch",
                     hide_index=True, column_config={
                         "title": st.column_config.TextColumn(width="large"),
                         "provenance": st.column_config.LinkColumn(display_text="source ↗"),
                         "chunks_indexed": st.column_config.NumberColumn("chunks"),
                         "ocr_pages": st.column_config.NumberColumn("OCR pages")})
    # Nothing ingested yet, or the API is down.
    else:
        st.info("No documents ingested yet, or the API is not reachable.")
