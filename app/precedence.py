"""Annex A Source Precedence Policy, in CODE (never the LLM). Owner: A.

Same 5 steps for document chunks (resolve) and for rule_registry rows (pick_rule):
  1 applicability (effective on as_of_date + programme/batch scope)  2 explicit supersession (only level 1-2)
  3 authority (lower level number wins)  4 recency (same authority: later effective_from wins)  5 unresolved -> flag
Level 5 (unofficial) content is informational only and never overrides anything.
"""
import re

# ---------- step 1 helpers: scope ----------
_YEAR = re.compile(r"(20\d{2})(?:-(\d{2})(?!\d))?")
_ALL = {"", "all", "general"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def programme_in_scope(scope: str, programme: str | None) -> bool:
    """'ALL' / 'B.Tech' / 'B.Tech (all branches)' / 'B.Tech CSE' / 'Ph.D. only' / 'All UG ...' vs 'B.Tech CSE'.
    Assumption (README): a scope naming only the degree ('B.Tech') covers every branch of it."""
    if programme is None or _norm(scope) in _ALL:
        return True
    parts = programme.lower().split()
    base = re.sub(r"[^a-z0-9]", "", parts[0])                 # "btech"
    branch = re.sub(r"[^a-z0-9]", "", "".join(parts[1:]))     # "cse"
    for item in re.split(r"[,;/]|\band\b", scope.lower()):
        it = re.sub(r"[^a-z0-9()]", "", item)
        if not it:
            continue
        if "phd" in it:
            if base == "phd":
                return True
            continue
        if it.startswith("all") or it.startswith("ug") or "bachelor" in it:
            return True
        if it.startswith(base):
            rest = it[len(base):]
            if rest == "" or rest.startswith("(") or not branch or rest.startswith(branch):
                return True
    return False


def batch_in_scope(scope: str, batch_year: int | None) -> bool:
    """'ALL' / '2023+' / 'Admitted 2019-20 onwards' / '2019-2022' / 'Batches 2020-21 to 2023-24' / 'Admitted 2025-26'."""
    s = (scope or "").lower()
    if batch_year is None or _norm(s) in _ALL or "unsure" in s:
        return True
    years = [int(m.group(1)) for m in _YEAR.finditer(s)]
    if not years:
        return True
    if "+" in s or "onward" in s or "after" in s:
        return batch_year >= years[0]
    if len(years) >= 2:
        return years[0] <= batch_year <= years[-1]
    return batch_year == years[0]


def in_scope(scope_programmes: str, scope_batches: str, student: dict | None) -> bool:
    if not student:
        return True                                   # general question: every scope is relevant
    return (programme_in_scope(scope_programmes, student.get("programme"))
            and batch_in_scope(scope_batches, student.get("batch_year")))


def is_effective(effective_from: str, effective_to: str, as_of_date: str) -> str:
    """'current' | 'future' | 'expired' (dates are ISO strings, so string compare is date compare)."""
    if effective_from and effective_from > as_of_date:
        return "future"
    if effective_to and effective_to < as_of_date:
        return "expired"
    return "current"


def _targets(supersedes: str) -> list[tuple[str, str | None]]:
    out = []
    for t in (supersedes or "").split(";"):
        t = t.strip()
        if t:
            doc, _, sec = t.partition("#")
            out.append((doc, sec or None))
    return out


def _section_match(section: str, target_sec: str | None) -> bool:
    if target_sec is None:
        return True
    s = str(section or "")
    return s == target_sec or s.startswith(target_sec + ".")


# ---------- chunks ----------
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MONEY = re.compile(r"(?:Rs\.?|₹|INR)\s*([\d,]{3,})", re.I)
_STOP = set("what which when where with that this from have shall will your there their about would could should "
            "does required require minimum maximum student students exam exams appear".split())


def _numbers(text: str) -> dict[str, set[str]]:
    return {"pct": {m.group(1) for m in _PCT.finditer(text)},
            "money": {m.group(1).replace(",", "") for m in _MONEY.finditer(text)}}


def _differ(na: dict, nb: dict) -> bool:
    """True if both chunks state numbers of the same kind (% or money) and the numbers differ."""
    return any(na[k] and nb[k] and na[k] != nb[k] for k in na)


def _related_by_supersession(a: dict, b: dict) -> bool:
    """A document that explicitly supersedes (part of) another speaks only to that part; its relation to the
    other document is settled by step 2, so other clauses of that document are not 'conflicts'."""
    def valid_sup(x: dict, y: dict) -> bool:          # only level 1-2 supersession counts (Annex A step 2)
        return int(x.get("authority_level", 3)) <= 2 and any(d == y["doc_id"] for d, _ in _targets(x.get("supersedes", "")))
    return valid_sup(a, b) or valid_sup(b, a)


def _topic_words(query: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (query or "").lower()) if w not in _STOP}


def _label(c: dict) -> str:
    return f"{c['doc_id']}#{c.get('section', '')}"


def resolve(chunks: list[dict], as_of_date: str, student: dict | None, query: str | None = None) -> dict:
    applicable, future, expired, out_scope, superseded, overridden, informational = [], [], [], [], [], [], []
    notes, conflicts = [], []
    unresolved = False

    # step 1: applicability
    for c in chunks:
        state = is_effective(c.get("effective_from", ""), c.get("effective_to", ""), as_of_date)
        if state == "future":
            future.append(c)
        elif state == "expired":
            expired.append(c)
        elif not in_scope(c.get("scope_programmes", "ALL"), c.get("scope_batches", "ALL"), student):
            out_scope.append(c)
        elif int(c.get("authority_level", 3)) == 5:
            informational.append(c)
        else:
            applicable.append(c)

    # step 2: explicit supersession (only by authority level 1-2 documents that are themselves applicable)
    for s in [c for c in applicable if int(c.get("authority_level", 3)) <= 2]:
        for doc, sec in _targets(s.get("supersedes", "")):
            for c in list(applicable):
                if c["doc_id"] == doc and _section_match(c.get("section"), sec):
                    applicable.remove(c)
                    superseded.append(c)
                    notes.append(f"{s['doc_id']} supersedes {doc}{'#' + sec if sec else ''} (step 2)")
    for f in future:
        if _targets(f.get("supersedes", "")):
            notes.append(f"upcoming: {f['doc_id']} (effective {f.get('effective_from')}) will supersede "
                         f"{f.get('supersedes')} — not yet in force on {as_of_date}")

    # steps 3-5: different documents that state different numbers on the question's topic
    topic = _topic_words(query)
    for a in list(applicable):
        for b in list(applicable):
            if a is b or a["doc_id"] == b["doc_id"] or a not in applicable or b not in applicable:
                continue
            if _related_by_supersession(a, b):
                continue
            shared = {w for w in topic if w in a["text"].lower() and w in b["text"].lower()} if topic else set()
            if not _differ(_numbers(a["text"]), _numbers(b["text"])) or (topic and not shared):
                continue
            la, lb = int(a.get("authority_level", 3)), int(b.get("authority_level", 3))
            if la != lb:
                win, lose = (a, b) if la < lb else (b, a)
                applicable.remove(lose)
                overridden.append(lose)
                conflicts.append(f"{_label(lose)} (level {max(la, lb)}) conflicts with {_label(win)} "
                                 f"(level {min(la, lb)}); higher authority prevails (step 3)")
            elif a.get("effective_from") != b.get("effective_from"):
                win, lose = (a, b) if a.get("effective_from", "") > b.get("effective_from", "") else (b, a)
                applicable.remove(lose)
                overridden.append(lose)
                conflicts.append(f"{_label(lose)} conflicts with {_label(win)} (same level {la}); "
                                 f"later effective_from {win.get('effective_from')} prevails (step 4)")
            else:
                unresolved = True
                conflicts.append(f"UNRESOLVED: {_label(a)} and {_label(b)} have the same authority (level {la}) and "
                                 f"effective date but state different values — contact the issuing office (step 5)")

    applicable.sort(key=lambda c: (int(c.get("authority_level", 3)), _neg(c.get("effective_from", "")),
                                   -float(c.get("score", 0))))
    decision = "; ".join(notes + conflicts) or "no conflicts among applicable sources"
    return {"applicable": applicable, "excluded_future": future, "expired": expired, "out_of_scope": out_scope,
            "superseded": superseded, "overridden": overridden, "informational": informational,
            "conflicts": conflicts + [n for n in notes if n.startswith("upcoming")],
            "decision": decision, "unresolved": unresolved}


def _neg(date: str) -> str:
    """Sort key making later dates come first."""
    return "".join(chr(255 - ord(ch)) for ch in date)


# ---------- rule_registry rows ----------
def _rule_doc(row: dict) -> tuple[int, str]:
    """authority_level + supersedes of the rule's source document (row may carry them already, e.g. in tests)."""
    if "authority_level" in row:
        return int(row["authority_level"]), row.get("doc_supersedes", "")
    from app.retrieval import get_source
    src = get_source(row["source_doc_id"]) or {}
    return int(src.get("authority_level", 3)), src.get("supersedes", "")


def pick_rule(rows: list[dict], as_of_date: str, student: dict | None) -> dict:
    """Annex A over rule rows of ONE parameter -> {rule, decision, conflicts, unresolved, upcoming, candidates}."""
    cands, upcoming = [], []
    for r in rows:
        r = dict(r)
        r["_auth"], r["_sup"] = _rule_doc(r)
        state = is_effective(r.get("effective_from", ""), r.get("effective_to") or "", as_of_date)
        if state == "future":
            upcoming.append(f"{r['rule_id']} = {r['value']} from {r['effective_from']} ({r['source_doc_id']})")
        elif state == "current" and in_scope(r.get("scope_programmes", "ALL"), r.get("scope_batches", "ALL"), student) \
                and r["_auth"] != 5:
            cands.append(r)
    notes, conflicts = [], []
    # step 2: explicit supersession by level 1-2 source documents
    for s in [c for c in cands if c["_auth"] <= 2]:
        for doc, sec in _targets(s["_sup"]):
            for c in list(cands):
                if c is not s and c["source_doc_id"] == doc and _section_match(c.get("source_section"), sec):
                    cands.remove(c)
                    notes.append(f"{s['rule_id']} ({s['source_doc_id']}) supersedes {c['rule_id']} "
                                 f"({doc}{'#' + sec if sec else ''}) (step 2)")
    if not cands:
        return {"rule": None, "decision": "; ".join(notes) or "no rule in force", "conflicts": conflicts,
                "unresolved": False, "upcoming": upcoming, "candidates": 0}
    # steps 3-4: authority, then recency
    cands.sort(key=lambda c: (c["_auth"], _neg(c.get("effective_from", ""))))
    win = cands[0]
    unresolved = False
    for other in cands[1:]:
        if str(other["value"]) == str(win["value"]):
            continue
        if other["_auth"] > win["_auth"]:
            conflicts.append(f"{other['rule_id']} ({other['source_doc_id']}, level {other['_auth']}) says "
                             f"{other['value']} but {win['rule_id']} (level {win['_auth']}) prevails (step 3)")
        elif other.get("effective_from") != win.get("effective_from"):
            conflicts.append(f"{other['rule_id']} ({other['effective_from']}) replaced by later "
                             f"{win['rule_id']} ({win['effective_from']}) (step 4)")
        else:
            unresolved = True
            conflicts.append(f"UNRESOLVED: {win['rule_id']} and {other['rule_id']} same authority and date, "
                             f"different values (step 5)")
    rule = {k: v for k, v in win.items() if not k.startswith("_")}
    return {"rule": None if unresolved else rule, "decision": "; ".join(notes + conflicts) or "single rule in force",
            "conflicts": conflicts, "unresolved": unresolved, "upcoming": upcoming, "candidates": len(cands)}


def get_rule_in_force(parameter: str, as_of_date: str, student: dict | None) -> dict:
    """Convenience for tools.py: fetch all rows of a parameter from rule_registry and apply pick_rule."""
    from app.db import connect
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM rule_registry WHERE parameter = ?", (parameter,))]
    return pick_rule(rows, as_of_date, student)
