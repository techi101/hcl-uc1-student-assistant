"""Streamlit UI for the NSUT Student Services Assistant. Talks ONLY to the FastAPI API (Section 6 + GET /me for sign-in).
Run: streamlit run ui/streamlit_app.py      (API must be running: uvicorn app.main:app --port 8000)
Screens: sign in -> assistant -> documents, with a navigation stack so "Back" returns to the previous screen.
Every answer panel answers one judge question: what kind of answer is this, where did it come from,
which rule won and why, what did code compute, what did it cost."""
import html
import json
import os
import re
from datetime import date

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="NSUT Student Services Assistant", page_icon="🎓", layout="wide",
                   initial_sidebar_state="collapsed")

# ---------------- icons: inline Lucide SVG paths (ISC licence), so no extra dependency or network fetch ----------------
ICONS = {
    "cap": '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 '
           '3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
            '<path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
    "clipboard": '<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 '
                 '0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/>'
                 '<path d="M8 16h.01"/>',
    "award": '<circle cx="12" cy="8" r="6"/><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "wallet": '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 '
              '1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "check": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4 12 14.01l-3-3"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "shuffle": '<path d="M16 3h5v5"/><path d="M4 20 21 3"/><path d="M21 16v5h-5"/><path d="m15 15 6 6"/>'
               '<path d="M4 4l5 5"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "book": '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    "calc": '<rect width="16" height="20" x="4" y="2" rx="2"/><path d="M8 6h8"/><path d="M16 14v4"/>'
            '<path d="M16 10h.01M12 10h.01M8 10h.01M12 14h.01M8 14h.01M12 18h.01M8 18h.01"/>',
    "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 '
             '1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/>'
             '<path d="M12 17h.01"/>',
    "ban": '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "sparkles": '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 '
                '1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/>'
                '<path d="M3 12a9 3 0 0 0 18 0"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "arrow": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "user": '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
}


def icon(name: str, size: int = 18, stroke: float = 2) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' "
            f"stroke='currentColor' stroke-width='{stroke}' stroke-linecap='round' stroke-linejoin='round' "
            f"aria-hidden='true'>{ICONS[name]}</svg>")


# answer_type -> (label, icon, text colour, background) so a judge sees at a glance WHAT KIND of answer this is (R9)
BADGES = {
    "retrieved_fact": ("From documents", "book", "#1D4ED8", "#DBEAFE"),
    "calculated": ("Calculated by code", "calc", "#047857", "#D1FAE5"),
    "not_found": ("Not in authorised sources", "search", "#4B5563", "#E5E7EB"),
    "clarification_needed": ("Needs clarification", "help", "#B45309", "#FEF3C7"),
    "refused": ("Refused", "ban", "#B91C1C", "#FEE2E2"),
    "conflict_flagged": ("Unresolved conflict", "alert", "#7C3AED", "#EDE9FE"),
}
# Annex A authority levels, shown next to every source so precedence decisions are readable
LEVELS = {1: "Regulation", 2: "Official circular", 3: "Dept notice", 4: "FAQ / handbook", 5: "Unofficial"}
SID_FORMAT = re.compile(r"^S\d{4}$")
# card tint per example type: (icon colour, tile background)
TINTS = {"indigo": ("#4F46E5", "#EEF2FF"), "sky": ("#0284C7", "#E0F2FE"), "emerald": ("#059669", "#D1FAE5"),
         "amber": ("#D97706", "#FEF3C7"), "rose": ("#E11D48", "#FFE4E6"), "violet": ("#7C3AED", "#EDE9FE"),
         "slate": ("#475569", "#F1F5F9")}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root { --ink: #0F172A; --muted: #64748B; --line: #E2E8F0; --brand: #4F46E5; --brand2: #7C3AED; --card: #FFFFFF; }
html, body, [class*="css"], .stMarkdown, .stTextInput, .stButton button, input { font-family: 'Inter', sans-serif; }
header[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
#MainMenu, footer { display: none !important; }
.stApp { background:
  radial-gradient(900px 500px at 100% -10%, rgba(124,58,237,.10), transparent 60%),
  radial-gradient(800px 500px at -10% 10%, rgba(79,70,229,.10), transparent 60%), #F8FAFC; }
.block-container { padding-top: 0.6rem; padding-bottom: 7rem; max-width: 1100px; }
[data-testid="stBottomBlockContainer"] { max-width: 1100px; margin: 0 auto; background: transparent; }
[data-testid="stBottom"] > div { background: linear-gradient(to top, #F8FAFC 70%, transparent); }
[data-testid="stChatInput"] { border-radius: 16px; box-shadow: 0 10px 30px -12px rgba(15,23,42,.25); }
.stButton button, .stFormSubmitButton button { border-radius: 12px; font-weight: 600; transition: all .15s ease; }
button[data-testid^="stBaseButton-primary"] {
  background: linear-gradient(135deg, var(--brand), var(--brand2)); border: 0; }
button[data-testid^="stBaseButton-primary"]:hover {
  filter: brightness(1.08); box-shadow: 0 8px 20px -8px rgba(79,70,229,.6); }

/* sticky glass top bar */
.st-key-topbar { position: sticky; top: 0; z-index: 50; padding: 10px 14px; margin: 0 0 20px 0;
  background: rgba(255,255,255,.72); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(226,232,240,.9); border-radius: 18px; box-shadow: 0 6px 24px -14px rgba(15,23,42,.25); }
.brand { display: flex; align-items: center; gap: 10px; }
.logo { width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; color: #fff; flex: none;
  background: linear-gradient(135deg, var(--brand), var(--brand2)); box-shadow: 0 6px 16px -6px rgba(79,70,229,.7); }
.brand .name { font-weight: 700; font-size: 1rem; color: var(--ink); line-height: 1.15; }
.brand .sub { font-size: .74rem; color: var(--muted); }
.health { font-size: .76rem; color: var(--muted); white-space: nowrap; display: inline-flex; align-items: center; gap: 6px;
  background: #fff; border: 1px solid var(--line); border-radius: 999px; padding: 4px 10px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.dot.ok { background: #10B981; box-shadow: 0 0 0 3px rgba(16,185,129,.18); }
.dot.warn { background: #F59E0B; box-shadow: 0 0 0 3px rgba(245,158,11,.18); }
.dot.down { background: #EF4444; box-shadow: 0 0 0 3px rgba(239,68,68,.18); }

/* sign-in */
.panel { position: relative; overflow: hidden; border-radius: 24px; padding: 40px 36px; color: #fff; min-height: 520px;
  background: linear-gradient(145deg, #312E81 0%, #4F46E5 55%, #7C3AED 100%); box-shadow: 0 30px 60px -30px rgba(49,46,129,.7); }
.panel .grid { position: absolute; inset: 0; opacity: .14; pointer-events: none; }
.panel .blob { position: absolute; width: 320px; height: 320px; border-radius: 50%; right: -90px; bottom: -110px;
  background: radial-gradient(circle, rgba(255,255,255,.35), transparent 65%); }
.panel .logo { width: 52px; height: 52px; border-radius: 15px; background: rgba(255,255,255,.16);
  border: 1px solid rgba(255,255,255,.3); box-shadow: none; margin-bottom: 26px; }
.panel h1 { color: #fff; font-size: 2.1rem; font-weight: 800; line-height: 1.12; margin: 0 0 12px 0; padding: 0;
  letter-spacing: -.02em; }
.panel p.lead { color: #E0E7FF; font-size: .98rem; line-height: 1.55; margin: 0 0 28px 0; max-width: 430px; }
.feat { display: flex; gap: 12px; align-items: flex-start; margin: 0 0 16px 0; position: relative; }
.feat .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; flex: none;
  background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.22); }
.feat b { display: block; font-size: .92rem; } .feat span { color: #C7D2FE; font-size: .82rem; }
.signin-head { margin: 34px 0 18px 0; }
.signin-head h2 { font-size: 1.55rem; font-weight: 800; color: var(--ink); margin: 0; padding: 0; letter-spacing: -.01em; }
.signin-head p { color: var(--muted); margin: 6px 0 0 0; font-size: .92rem; }
.st-key-signin_card { background: var(--card); border: 1px solid var(--line); border-radius: 20px; padding: 26px 24px;
  box-shadow: 0 20px 50px -30px rgba(15,23,42,.35); }
.or { display: flex; align-items: center; gap: 10px; color: #94A3B8; font-size: .76rem; margin: 6px 0;
  text-transform: uppercase; letter-spacing: .08em; }
.or:before, .or:after { content: ""; flex: 1; border-top: 1px solid var(--line); }
.fine { color: var(--muted); font-size: .78rem; text-align: center; margin-top: 6px; display: flex; gap: 6px;
  justify-content: center; align-items: center; }

/* welcome + example cards (the whole card is the button) */
.hello { margin: 6px 0 18px 0; }
.hello h2 { font-size: 2rem; font-weight: 800; margin: 0; padding: 0; letter-spacing: -.02em;
  background: linear-gradient(135deg, #0F172A 30%, var(--brand2)); -webkit-background-clip: text; background-clip: text;
  color: transparent; }
.hello p { color: var(--muted); margin: 6px 0 0 0; font-size: .96rem; }
.note { display: flex; gap: 10px; align-items: center; background: #EEF2FF; border: 1px solid #C7D2FE; color: #3730A3;
  border-radius: 14px; padding: 11px 14px; font-size: .86rem; margin: 0 0 16px 0; }
[class*="st-key-card_"] { position: relative; background: var(--card); border: 1px solid var(--line); border-radius: 18px;
  padding: 18px 18px 18px 18px; min-height: 178px; box-sizing: border-box; gap: 0; overflow: visible; transition: transform .16s ease, box-shadow .16s ease, border-color .16s; }
[class*="st-key-card_"]:hover { transform: translateY(-3px); border-color: #C7D2FE;
  box-shadow: 0 16px 36px -18px rgba(79,70,229,.45); }
[class*="st-key-card_"]:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(79,70,229,.2); }
[class*="st-key-card_"] .stElementContainer:has(.stButton) { position: absolute; inset: 0; margin: 0; z-index: 2; }
[class*="st-key-card_"] .stButton, [class*="st-key-card_"] .stButton button { width: 100%; height: 100%; }
[class*="st-key-card_"] .stButton button { opacity: 0; cursor: pointer; }
.tile { width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center; margin-bottom: 12px; }
.card-h { font-weight: 700; font-size: .93rem; color: var(--ink); margin-bottom: 4px; }
.card-q { color: var(--muted); font-size: .85rem; line-height: 1.5; }
.card-go { position: absolute; right: 18px; top: 28px; color: #CBD5E1; transition: all .16s; }
[class*="st-key-card_"]:hover .card-go { color: var(--brand); transform: translateX(3px); }

/* chat */
div[data-testid="stChatMessage"] { background: var(--card); border: 1px solid var(--line); border-radius: 18px;
  padding: 16px 18px; box-shadow: 0 8px 24px -20px rgba(15,23,42,.35); }
div[data-testid="stChatMessage"]:has(.umsg) { background: linear-gradient(135deg, var(--brand), var(--brand2));
  border: 0; flex-direction: row-reverse; width: fit-content; max-width: 80%; margin-left: auto; }
div[data-testid="stChatMessage"]:has(.umsg) p, .umsg, .umsg .meta { color: #fff !important; text-align: right; }
.umsg .meta { opacity: .75; }
.pill { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 11px; font-size: .78rem;
  font-weight: 600; }
.meta { color: var(--muted); font-size: .78rem; margin-left: 8px; }
.answer { font-size: 1.05rem; line-height: 1.65; color: var(--ink); margin: 12px 0 6px 0; }
.why { display: flex; gap: 8px; color: #475569; font-size: .9rem; background: #F8FAFC; border: 1px solid var(--line);
  border-radius: 12px; padding: 10px 12px; margin: 8px 0 12px 0; }
.why svg { flex: none; margin-top: 2px; color: var(--brand); }
.callout { display: flex; gap: 8px; background: #F5F3FF; border: 1px solid #DDD6FE; border-radius: 12px; padding: 10px 14px;
  font-size: .86rem; color: #4C1D95; margin: 8px 0; }
.cites { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; margin: 8px 0; }
.cite { display: flex; gap: 10px; background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 10px 12px; }
.cite .ic { width: 32px; height: 32px; border-radius: 9px; background: #EEF2FF; color: var(--brand); display: grid;
  place-items: center; flex: none; }
.cite b { color: var(--ink); font-size: .86rem; display: block; line-height: 1.3; }
.cite .sub, .toolcard .sub { color: var(--muted); font-size: .75rem; margin-top: 3px; }
.tag { display: inline-block; background: #EEF2FF; color: #3730A3; border-radius: 6px; padding: 1px 7px;
  font-size: .7rem; font-weight: 600; margin: 4px 4px 0 0; }
.tag.syn { background: #FEF3C7; color: #92400E; }
.src { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid #F1F5F9; font-size: .84rem; }
.src .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.src .bar { width: 110px; height: 6px; background: #EEF2FF; border-radius: 4px; overflow: hidden; }
.src .bar i { display: block; height: 100%; background: linear-gradient(90deg, var(--brand), var(--brand2)); }
.src .st { width: 120px; text-align: right; font-size: .74rem; font-weight: 600; }
.step { display: flex; gap: 8px; font-size: .85rem; padding: 6px 0; color: #334155; }
.step svg { flex: none; margin-top: 2px; color: var(--brand); }
.toolcard { display: flex; gap: 10px; background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 12px;
  padding: 10px 14px; margin: 6px 0; color: #065F46; }
.toolcard code { font-size: .76rem; }
.page-h { display: flex; gap: 12px; align-items: center; margin: 4px 0 18px 0; }
.page-h .tile { margin: 0; width: 44px; height: 44px; }
.page-h h2 { font-size: 1.6rem; font-weight: 800; margin: 0; padding: 0; color: var(--ink); }
.page-h p { color: var(--muted); margin: 2px 0 0 0; font-size: .9rem; }
[data-testid="stMetric"] { background: #fff; border-radius: 16px; }
.profile .n { font-weight: 700; font-size: 1rem; color: var(--ink); }
.profile .m { color: var(--muted); font-size: .8rem; margin-top: 2px; }
@media (max-width: 640px) { .src .bar, .health span.t { display: none; } .panel { min-height: 0; padding: 28px 22px; }
  div[data-testid="stChatMessage"]:has(.umsg) { max-width: 100%; } }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)
esc = html.escape  # document text is untrusted (R8): never render it as raw HTML


# ---------------- state: who is signed in, and the screen stack behind "Back" ----------------
ss = st.session_state
ss.setdefault("api", os.getenv("API_URL", "http://localhost:8000"))
ss.setdefault("auth", None)          # None = not signed in; {"guest": True}; or the /me profile
ss.setdefault("nav", ["signin"])     # screen stack; Back pops it
ss.setdefault("messages", [])
ss.setdefault("as_of", date.today())


def go(screen: str) -> None:
    # revisiting a screen rewinds to it, so Back never cycles chat -> docs -> chat -> docs
    ss.nav = ss.nav[:ss.nav.index(screen) + 1] if screen in ss.nav else ss.nav + [screen]


def back() -> None:
    ss.nav.pop()
    if not ss.nav or ss.nav[-1] == "signin":   # leaving the app screens = signing out
        sign_out()


def sign_out() -> None:
    ss.auth, ss.messages, ss.nav = None, [], ["signin"]


def student_id() -> str | None:
    return None if not ss.auth or ss.auth.get("guest") else ss.auth["student_id"]


# ---------------- API helpers ----------------
@st.cache_data(ttl=15, show_spinner=False)
def load_health(api: str) -> dict | None:
    try:
        return httpx.get(f"{api}/health", timeout=5).json()
    except Exception:
        return None


@st.cache_data(ttl=30, show_spinner=False)
def load_sources(api: str) -> dict:
    """doc_id -> register row, so citations can show authority level and synthetic flag."""
    try:
        return {r["doc_id"]: r for r in httpx.get(f"{api}/sources", timeout=10).json()}
    except Exception:
        return {}


def lookup_student(sid: str) -> tuple[dict | None, str | None]:
    """Sign-in check via GET /me with the X-Student-Id header (same identity channel as /ask, R7)."""
    try:
        r = httpx.get(f"{ss.api}/me", headers={"X-Student-Id": sid}, timeout=10)
    except Exception:
        return None, f"Can't reach the API at {ss.api}. Start it with: uvicorn app.main:app --port 8000"
    if r.status_code == 404:
        return None, f"No student with ID {sid} exists in the university records."
    if r.status_code != 200:
        return None, f"Sign-in check failed ({r.status_code})."
    return r.json(), None


def ask(question: str) -> tuple[dict, dict | None]:
    sid = student_id()
    headers = {"X-Student-Id": sid} if sid else {}
    r = httpx.post(f"{ss.api}/ask", json={"question": question, "as_of_date": ss.as_of.isoformat()},
                   headers=headers, timeout=300)
    r.raise_for_status()
    resp = r.json()
    try:  # fetched once and stored, so reruns don't re-hit the API
        audit = httpx.get(f"{ss.api}/audit/{resp['trace_id']}", timeout=10).json()
    except Exception:
        audit = None
    return resp, audit


def health_line(h: dict | None) -> str:
    if h is None:
        return "<span class='health'><i class='dot down'></i><span class='t'>API offline</span></span>"
    bad = [k for k, v in h.items() if not (str(v).startswith("ok") or v == "mock")]
    if bad:  # name the broken part plainly; the full reason is in the tooltip
        names = {"llm": "AI model", "vector_store": "Document index", "sqlite": "Student database", "api": "API"}
        detail = "; ".join(f"{k}: {h[k]}" for k in bad)
        return (f"<span class='health' title='{esc(detail)}'><i class='dot warn'></i><span class='t'>"
                f"{esc(', '.join(names.get(k, k) for k in bad))} unavailable</span></span>")
    model = str(h.get("llm", "")).removeprefix("ok").strip(" ()")
    return (f"<span class='health' title='model: {esc(model)}'><i class='dot ok'></i>"
            f"<span class='t'>All systems ok</span></span>")


# ---------------- answer rendering ----------------
def pill(answer_type: str) -> str:
    label, ic, fg, bg = BADGES.get(answer_type, (answer_type or "?", "help", "#374151", "#E5E7EB"))
    return f"<span class='pill' style='color:{fg};background:{bg}'>{icon(ic, 14, 2.4)}{esc(label)}</span>"


def render_citations(citations: list, sources: dict) -> None:
    cards = ""
    for c in citations:
        reg = sources.get(c["doc_id"], {})
        lvl = reg.get("authority_level")
        tags = f"<span class='tag'>L{lvl} · {LEVELS.get(lvl, '')}</span>" if lvl else ""
        tags += "<span class='tag syn'>synthetic</span>" if reg.get("synthetic") == "Y" else ""
        where = " · ".join(x for x in [
            f"§ {c['section']}" if c.get("section") else "", f"page {c['page']}" if c.get("page") else "",
            f"v{c['version']}" if c.get("version") else "",
            f"effective {c['effective_from']}" if c.get("effective_from") else ""] if x)
        cards += (f"<div class='cite'><div class='ic'>{icon('file', 16)}</div><div><b>"
                  f"{esc(c.get('title') or c['doc_id'])}</b><div class='sub'><code>{esc(c['doc_id'])}</code> · "
                  f"{esc(where)}</div>{tags}</div></div>")
    st.markdown(f"<div class='cites'>{cards}</div>", unsafe_allow_html=True)


def render_precedence(audit: dict, cited: set) -> None:
    """Every retrieved chunk with its score and fate under Annex A: cited, superseded, not yet effective, or context."""
    superseded, future = set(audit.get("superseded", [])), set(audit.get("excluded_future", []))
    rows = ""
    for s in audit.get("sources_retrieved", []):
        key = f"{s['doc_id']}#{s.get('section', '')}"
        if key in cited:
            status, col = "✓ cited", "#047857"
        elif key in superseded or s["doc_id"] in superseded:
            status, col = "superseded", "#B91C1C"
        elif key in future or s["doc_id"] in future:
            status, col = "not yet effective", "#B45309"
        else:
            status, col = "retrieved", "#64748B"
        name = f"<s>{esc(key)}</s>" if status == "superseded" else esc(key)
        pct = max(0, min(100, int(float(s.get("score", 0)) * 100)))
        rows += (f"<div class='src'><span class='name'><code>{name}</code></span>"
                 f"<span class='bar'><i style='width:{pct}%'></i></span><span style='width:38px;font-size:.74rem'>"
                 f"{s.get('score', 0):.2f}</span><span class='st' style='color:{col}'>{status}</span></div>")
    st.markdown(rows or "<span class='meta'>No documents retrieved.</span>", unsafe_allow_html=True)
    if audit.get("precedence_decision"):
        st.markdown("**Which rule won, and why (Annex A)**")
        steps = "".join(f"<div class='step'>{icon('scale', 15)}<span>{esc(part)}</span></div>"
                        for part in re.split(r"; (?=[A-Z])", audit["precedence_decision"]))  # decisions, not clauses
        st.markdown(steps, unsafe_allow_html=True)


def render_tools(resp: dict) -> None:
    for t in resp.get("tools_invoked", []):
        out = t.get("output")
        st.markdown(f"<div class='toolcard'>{icon('calc', 16)}<div><b>{esc(t.get('tool', ''))}</b>"
                    f"<div class='sub'>input <code>{esc(json.dumps(t.get('input', {})))}</code></div></div></div>",
                    unsafe_allow_html=True)
        if isinstance(out, dict) and all(not isinstance(v, (dict, list)) for v in out.values()):
            st.dataframe(pd.DataFrame([out]), hide_index=True, width="stretch")
        else:
            st.json(out, expanded=False)
    for r in resp.get("applied_rules", []):
        st.markdown(f"<div class='step'>{icon('shield', 15)}<span>Rule <b>{esc(r['rule_id'])}</b> &nbsp;"
                    f"<code>{esc(str(r['value']))}</code> &nbsp;from <code>{esc(r['source_doc_id'])}</code></span></div>",
                    unsafe_allow_html=True)


def render_audit(audit: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latency", f"{audit.get('latency_ms', 0) / 1000:.1f} s", border=True)
    c2.metric("LLM calls", audit.get("llm_calls", "–"), border=True)
    c3.metric("Tokens", audit.get("tokens", "–"), border=True)
    c4.metric("Chunks", len(audit.get("sources_retrieved", [])), border=True)
    st.caption(f"Model: `{audit.get('model', '–')}` · category: `{audit.get('question_category', '–')}`")
    stages = audit.get("stage_ms") or {}
    if stages:
        df = pd.DataFrame({"stage": [k.removesuffix("_ms") for k in stages], "ms": list(stages.values())})
        st.bar_chart(df, x="stage", y="ms", horizontal=True, height=200, color="#6366F1", sort=False)
    with st.expander("Raw audit record (GET /audit)"):
        st.json(audit, expanded=False)


def render_answer(resp: dict, audit: dict | None, key: str) -> None:
    st.markdown(f"{pill(resp.get('answer_type'))}<span class='meta'>as of {esc(resp.get('as_of_date', ''))}"
                f" · trace <code>{esc(resp.get('trace_id', ''))}</code></span>", unsafe_allow_html=True)
    st.markdown(f"<div class='answer'>{esc(resp.get('answer', ''))}</div>", unsafe_allow_html=True)
    if resp.get("explanation") and resp["explanation"] != resp.get("answer"):
        st.markdown(f"<div class='why'>{icon('sparkles', 16)}<span>{esc(resp['explanation'])}</span></div>",
                    unsafe_allow_html=True)
    for c in resp.get("conflicts_detected", []):
        st.markdown(f"<div class='callout'>{icon('alert', 16)}<span>{esc(c)}</span></div>", unsafe_allow_html=True)
    if resp.get("citations"):
        render_citations(resp["citations"], load_sources(ss.api))

    # details collapsed by default: the answer is the headline, the evidence is one click away
    with st.expander("Evidence: sources, rules and audit", icon=":material/fact_check:", key=f"ev_{key}"):
        names = ["Sources & precedence"]
        has_tools = bool(resp.get("tools_invoked") or resp.get("applied_rules"))
        names += ["Tools & rules"] if has_tools else []
        names += ["Audit"]
        tabs = dict(zip(names, st.tabs(names)))
        cited = {f"{c['doc_id']}#{c.get('section', '')}" for c in resp.get("citations", [])}
        with tabs["Sources & precedence"]:
            if audit:
                render_precedence(audit, cited)
            else:
                st.caption("Audit record not available.")
        if has_tools:
            with tabs["Tools & rules"]:
                st.caption("Computed by code over SQLite and the rule registry, not by the AI (R5).")
                render_tools(resp)
        with tabs["Audit"]:
            if audit:
                render_audit(audit)
            else:
                st.caption("Audit record not available.")


# ---------------- top bar (all screens after sign-in) ----------------
def top_bar(screen: str) -> None:
    with st.container(key="topbar"):
        c_back, c_brand, c_health, c_nav, c_user = st.columns([1.05, 3.3, 1.7, 1.45, 1.5], vertical_alignment="center")
        c_back.button("Back", icon=":material/arrow_back:", on_click=back, key="back", width="stretch",
                      help="Return to the previous screen")
        c_brand.markdown(f"<div class='brand'><div class='logo'>{icon('cap', 20)}</div><div><div class='name'>"
                         "NSUT Student Services</div><div class='sub'>Answers only from authorised sources</div>"
                         "</div></div>", unsafe_allow_html=True)
        c_health.markdown(health_line(load_health(ss.api)), unsafe_allow_html=True)
        if screen == "chat":
            c_nav.button("Documents", icon=":material/library_books:", on_click=go, args=("docs",), width="stretch")
        else:
            c_nav.button("Assistant", icon=":material/forum:", on_click=go, args=("chat",), width="stretch")
        sid = student_id()
        with c_user.popover(sid or "Guest", icon=":material/account_circle:", width="stretch"):
            if sid:
                a = ss.auth
                st.markdown(f"<div class='profile'><div class='n'>{esc(a['full_name'])}</div><div class='m'>"
                            f"{esc(sid)} · {esc(a['programme'])} · batch {a['batch_year']} · semester "
                            f"{a['current_semester']}</div></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='profile'><div class='n'>Guest</div><div class='m'>Rules and procedures "
                            "only. Sign in to ask about your own records.</div></div>", unsafe_allow_html=True)
            st.divider()
            ss.as_of = st.date_input("Answer as of", value=ss.as_of,
                                     help="Rules are applied as they stood on this date (Annex A applicability). "
                                          "Try a date before a circular took effect to see the older rule.")
            ss.api = st.text_input("API URL", ss.api)
            st.button("Sign out", icon=":material/logout:", on_click=sign_out, width="stretch", type="primary")


# ---------------- screen: sign in ----------------
def do_sign_in() -> None:
    """Callback, so the screen switch happens before the rerun (no stale sign-in widgets left on the page)."""
    sid = (ss.get("sid_input") or "").strip().upper()
    if not sid:
        ss.signin_error = "Enter your student ID."
    elif not SID_FORMAT.match(sid):
        ss.signin_error = "Student IDs look like S1001: the letter S followed by 4 digits."
    else:
        profile, err = lookup_student(sid)
        if err:
            ss.signin_error = err
        else:  # only a verified ID gets in; the chat history starts fresh for each identity
            ss.auth, ss.messages, ss.nav = profile, [], ["signin", "chat"]


def do_guest() -> None:
    ss.auth, ss.messages, ss.nav = {"guest": True}, [], ["signin", "chat"]


GRID_SVG = ("<svg class='grid' xmlns='http://www.w3.org/2000/svg' width='100%' height='100%'><defs><pattern id='g' "
            "width='28' height='28' patternUnits='userSpaceOnUse'><path d='M28 0H0V28' fill='none' stroke='white' "
            "stroke-width='1'/></pattern></defs><rect width='100%' height='100%' fill='url(#g)'/></svg>")
FEATURES = [("book", "Cited answers", "Every fact links to the regulation, circular or FAQ it came from."),
            ("calc", "Computed by code", "Attendance, eligibility and backlogs come from your records, not the AI."),
            ("scale", "Latest rule wins", "Superseded and not-yet-effective rules are detected and explained."),
            ("lock", "Your data only", "Personal questions need sign-in; other students' records are refused.")]


def screen_signin() -> None:
    st.markdown("<div style='height:4vh'></div>", unsafe_allow_html=True)
    left, gap, right = st.columns([1.15, 0.08, 1])
    feats = "".join(f"<div class='feat'><div class='ic'>{icon(i, 17)}</div><div><b>{t}</b><span>{d}</span></div></div>"
                    for i, t, d in FEATURES)
    left.markdown(f"<div class='panel'>{GRID_SVG}<div class='blob'></div><div class='logo'>{icon('cap', 26)}</div>"
                  "<h1>NSUT Student<br>Services Assistant</h1><p class='lead'>Ask about university rules, "
                  "procedures, and your own attendance, results and eligibility.</p>"
                  f"{feats}</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='signin-head'><h2>Welcome back</h2><p>Sign in with your student ID to get answers "
                    "about your own records.</p></div>", unsafe_allow_html=True)
        with st.container(key="signin_card"):
            with st.form("signin", border=False, enter_to_submit=True):
                st.text_input("Student ID", placeholder="e.g. S1001", max_chars=5, key="sid_input")
                st.form_submit_button("Sign in", type="primary", width="stretch", icon=":material/login:",
                                      on_click=do_sign_in)
            if ss.get("signin_error"):
                st.error(ss.pop("signin_error"), icon=":material/error:")
            st.markdown("<div class='or'>or</div>", unsafe_allow_html=True)
            st.button("Continue as guest", icon=":material/person_outline:", width="stretch", on_click=do_guest)
            st.markdown(f"<div class='fine'>{icon('shield', 13)}Guests can ask about rules and procedures, "
                        "not personal records.</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='margin-top:14px;text-align:center'>{health_line(load_health(ss.api))}</div>",
                    unsafe_allow_html=True)


# ---------------- screen: assistant (chat) ----------------
# example questions, one per question type in Section 2.1; personal ones use a course from the student's programme
COURSE_EXAMPLE = {"B.Tech CSE": ("Data Structures", "CS201"), "B.Tech ECE": ("Signals and Systems", "EC201")}
GENERAL = [
    ("file", "indigo", "Policy fact", "What is the minimum attendance required to appear for end-semester exams?"),
    ("clipboard", "sky", "Procedure", "How do I apply for re-registration of a failed course?"),
    ("award", "emerald", "Degree rule", "What is the minimum CGPA required for the award of a B.Tech degree?"),
    ("clock", "amber", "Attendance relaxation", "Can the Dean relax the attendance requirement, and by how much?"),
    ("wallet", "violet", "Fees", "What is the annual tuition fee for B.Tech students admitted in 2025-26?"),
    ("help", "slate", "Not answerable", "What is the scholarship for studying in Antarctica?"),
]


def examples() -> list[tuple[str, str, str, str]]:
    if not student_id():
        return GENERAL
    name, code = COURSE_EXAMPLE.get(ss.auth["programme"], next(iter(COURSE_EXAMPLE.values())))
    return [GENERAL[0],
            ("chart", "sky", "My attendance", f"What is my attendance in {name}?"),
            ("check", "emerald", "My eligibility", f"Am I eligible to appear in the end-semester exam for {code}?"),
            ("layers", "amber", "My backlogs", "Do I have any active backlogs?"),
            ("shuffle", "violet", "What-if",
             f"I failed {name}. If I pass it in the re-registration exam, will I be eligible for placement?"),
            GENERAL[5]]


def with_context(question: str) -> str:
    """/ask is stateless, so a reply to "Which course do you mean?" (e.g. just "HS201") is sent together with
    the question it answers. Only after a clarification request: other follow-ups stay independent questions."""
    if len(ss.messages) >= 2 and ss.messages[-1]["role"] == "assistant" \
            and ss.messages[-1]["resp"].get("answer_type") == "clarification_needed":
        return f"{ss.messages[-2].get('question', '').rstrip(' ?')} — {question}"
    return question


def queue(q: str) -> None:  # button callback: runs before the rerun, so the cards can hide immediately
    ss.pending = q


def screen_chat() -> None:
    top_bar("chat")
    typed = st.chat_input("Ask about NSUT rules, or your own attendance and eligibility…")  # pinned bottom
    question = typed or ss.pop("pending", None)
    sid = student_id()

    if not ss.messages and not question:
        first = ss.auth.get("full_name", "").split(" ")[0] if sid else ""
        st.markdown(f"<div class='hello'><h2>Hi{', ' + esc(first) if first else ' there'}, how can I help?</h2>"
                    "<p>Pick an example or type your own question below.</p></div>", unsafe_allow_html=True)
        if not sid:
            st.markdown(f"<div class='note'>{icon('lock', 16)}<span>You're browsing as a guest. Questions about "
                        "your own attendance, results or eligibility need you to sign in.</span></div>",
                        unsafe_allow_html=True)
        ex = examples()
        for i in range(0, len(ex), 3):
            for j, (col, (ic, tint, label, q)) in enumerate(zip(st.columns(3), ex[i:i + 3])):
                fg, bg = TINTS[tint]
                with col.container(key=f"card_{i + j}"):
                    st.markdown(f"<div class='tile' style='color:{fg};background:{bg}'>{icon(ic, 19)}</div>"
                                f"<span class='card-go'>{icon('arrow', 16)}</span><div class='card-h'>{esc(label)}"
                                f"</div><div class='card-q'>{esc(q)}</div>", unsafe_allow_html=True)
                    st.button(f"Ask: {q}", key=f"ex_{i + j}", on_click=queue, args=(q,))
    else:
        _, right = st.columns([5, 1])
        right.button("New chat", icon=":material/add_comment:", width="stretch",
                     on_click=lambda: ss.update(messages=[]))

    for i, m in enumerate(ss.messages):
        with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user" else ":material/school:"):
            if m["role"] == "assistant":
                render_answer(m["resp"], m.get("audit"), key=str(i))
            else:
                st.markdown(m["text"], unsafe_allow_html=True)

    if question:
        sent = with_context(question)
        note = f" · asked as “{esc(sent)}”" if sent != question else ""
        text = (f"<div class='umsg'>{esc(question)}<div class='meta'>as {esc(sid) if sid else 'guest'}{note}</div></div>")
        ss.messages.append({"role": "user", "text": text, "question": sent})
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(text, unsafe_allow_html=True)
        with st.chat_message("assistant", avatar=":material/school:"):
            slot = st.empty()  # progress shows while waiting, then disappears so only the answer remains
            with slot.status("Checking identity → searching documents → applying precedence → running tools…") as s:
                try:
                    resp, audit = ask(sent)
                except Exception as e:
                    s.update(label=f"Request failed: {e}", state="error")
                    resp = None
            if resp:
                slot.empty()
                render_answer(resp, audit, key=str(len(ss.messages)))
                ss.messages.append({"role": "assistant", "resp": resp, "audit": audit})


# ---------------- screen: documents (live ingestion + source register) ----------------
def screen_docs() -> None:
    top_bar("docs")
    fg, bg = TINTS["indigo"]
    st.markdown(f"<div class='page-h'><div class='tile' style='color:{fg};background:{bg}'>{icon('book', 22)}</div>"
                "<div><h2>Documents</h2><p>The authorised sources the assistant answers from, and live ingestion "
                "of new ones.</p></div></div>", unsafe_allow_html=True)
    sources = load_sources(ss.api)
    if sources:
        rows = list(sources.values())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Documents", len(rows), border=True)
        c2.metric("Chunks indexed", sum(int(r.get("chunks_indexed") or 0) for r in rows), border=True)
        c3.metric("Authority levels", len({r.get("authority_level") for r in rows}), border=True)
        c4.metric("Synthetic docs", sum(r.get("synthetic") == "Y" for r in rows), border=True)

    with st.expander("Add a document while the system is running (POST /ingest)", icon=":material/upload_file:",
                     expanded=not sources):
        with st.form("ingest", border=False):
            f = st.file_uploader("Document: PDF (text or scanned), DOCX, TXT, MD", type=["pdf", "docx", "txt", "md"])
            c1, c2, c3 = st.columns(3)
            doc_id = c1.text_input("doc_id *", placeholder="ACAD-2026-08")
            title = c2.text_input("title *")
            issuer = c3.text_input("issuer", placeholder="Office of the Dean (Academics)")
            c4, c5, c6 = st.columns(3)
            level = c4.selectbox("authority_level *", [1, 2, 3, 4, 5], index=1,
                                 format_func=lambda x: f"{x} · {LEVELS[x]}")
            doc_type = c5.selectbox("doc_type", ["regulation", "circular", "notice", "faq", "handbook", "unofficial"],
                                    index=1)
            version = c6.text_input("version")
            c7, c8, c9 = st.columns(3)
            eff_from = c7.date_input("effective_from *", value=date.today())
            eff_to = c8.text_input("effective_to", placeholder="YYYY-MM-DD or empty")
            supersedes = c9.text_input("supersedes", placeholder="NSUT-BTECH-REG-2019#11.2")
            c10, c11, c12 = st.columns(3)
            scope_p = c10.text_input("scope_programmes", "ALL")
            scope_b = c11.text_input("scope_batches", "ALL")
            synthetic = c12.selectbox("synthetic", ["N", "Y"])
            provenance = st.text_input("provenance (URL / source)")
            submitted = st.form_submit_button("Ingest document", type="primary", icon=":material/upload:")
        if submitted:
            if not (f and doc_id.strip() and title.strip()):
                st.error("File, doc_id and title are required.")
            else:
                meta = {"doc_id": doc_id.strip(), "title": title.strip(), "issuer": issuer,
                        "authority_level": level, "doc_type": doc_type, "version": version,
                        "effective_from": eff_from.isoformat(), "effective_to": eff_to, "supersedes": supersedes,
                        "scope_programmes": scope_p, "scope_batches": scope_b, "provenance": provenance,
                        "retrieved_on": date.today().isoformat(), "synthetic": synthetic}
                with st.status("Extracting text (OCR if scanned) → chunking → embedding → extracting rules…") as s:
                    try:
                        r = httpx.post(f"{ss.api}/ingest", files={"file": (f.name, f.getvalue())},
                                       data={"metadata": json.dumps(meta)}, timeout=600)
                        if r.status_code == 200:
                            s.update(label=f"Ingested: {r.json()}", state="complete")
                            load_sources.clear()
                        else:
                            s.update(label=f"{r.status_code}: {r.text[:300]}", state="error")
                    except Exception as e:
                        s.update(label=f"Ingest failed: {e}", state="error")

    st.markdown("#### Source register")
    st.caption("GET /sources: every ingested document with the metadata the precedence policy uses.")
    if sources:
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
    else:
        st.info("No documents ingested yet, or the API is not reachable.")


# ---------------- router ----------------
if ss.auth is None and ss.nav[-1] != "signin":   # no way past sign-in without a verified ID or explicit guest choice
    ss.nav = ["signin"]
{"signin": screen_signin, "chat": screen_chat, "docs": screen_docs}[ss.nav[-1]]()
