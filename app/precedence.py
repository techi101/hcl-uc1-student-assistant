"""Annex A Source Precedence Policy, in CODE (never the LLM). Owner: A.

Same 5 steps for document chunks (resolve) and for rule_registry rows (pick_rule):
  1 applicability (effective on as_of_date + programme/batch scope)  2 explicit supersession (only level 1-2)
  3 authority (lower level number wins)  4 recency (same authority: later effective_from wins)  5 unresolved -> flag
Level 5 (unofficial) content is informational only and never overrides anything.
"""
# WHAT THIS FILE IS: the "judge" that decides which rule wins when documents disagree.
# It is plain Python (no AI), so the same input always gives the same answer and we can test it.
# Real example: Regulations 11.2 says 75% (level 1), circular SYN-CIRC-ATT-2026 says 80% from 2026-08-01
# (level 2, supersedes 11.2), CSE FAQ SYN-FAQ-ATT-2026 says 65% (level 4). This file decides 80% applies.
# re = Python's "regular expressions" library: patterns for finding text like years or percentages.
import re

# ---------- step 1 helpers: scope ----------
# _YEAR finds years in text: matches "20" + 2 digits (like 2019), optionally "-" + exactly 2 digits
# (like 2019-20). The "(?!\d)" means "the 2 digits must not be followed by another digit",
# so in "2019-2022" it reads 2019 and 2022 as two separate years. We use only the first group (2019).
_YEAR = re.compile(r"(20\d{2})(?:-(\d{2})(?!\d))?")
# Scope words that mean "applies to everyone" (empty, "all", "general").
_ALL = {"", "all", "general"}


# IN: any text  ->  OUT: same text, lowercase, with ALL spaces removed ("  All " -> "all").
# WHY: so "ALL", "All ", "all" are treated the same when we compare scopes.
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


# IN: a document's programme scope (e.g. "B.Tech (all branches)") + the student's programme (e.g. "B.Tech CSE")
#  ->  OUT: True if this document is meant for this student's programme.
# Example: scope "B.Tech" covers "B.Tech CSE"; scope "B.Tech CSE" covers CSE only; "Ph.D. only" does not cover B.Tech.
def programme_in_scope(scope: str, programme: str | None) -> bool:
    """'ALL' / 'B.Tech' / 'B.Tech (all branches)' / 'B.Tech CSE' / 'Ph.D. only' / 'All UG ...' vs 'B.Tech CSE'.
    Assumption (README): a scope naming only the degree ('B.Tech') covers every branch of it."""
    # No student programme known, or scope says "ALL" -> the document applies.
    if programme is None or _norm(scope) in _ALL:
        return True
    # Split the student's programme into degree + branch, keeping only letters and digits:
    # "B.Tech CSE" -> base "btech", branch "cse".
    parts = programme.lower().split()
    base = re.sub(r"[^a-z0-9]", "", parts[0])                 # "btech"
    branch = re.sub(r"[^a-z0-9]", "", "".join(parts[1:]))     # "cse"
    # A scope can list many programmes. Split it on commas, semicolons, slashes or the word "and",
    # then check each piece one by one. If ANY piece matches the student, the document applies.
    for item in re.split(r"[,;/]|\band\b", scope.lower()):
        # Clean the piece: keep only letters, digits and brackets ("B.Tech (all branches)" -> "btech(allbranches)").
        it = re.sub(r"[^a-z0-9()]", "", item)
        if not it:
            continue
        # Ph.D. pieces match only Ph.D. students; for anyone else, skip this piece.
        if "phd" in it:
            if base == "phd":
                return True
            continue
        # "All ...", "UG ..." or "Bachelor's ..." pieces cover every undergraduate, so they match.
        if it.startswith("all") or it.startswith("ug") or "bachelor" in it:
            return True
        # Piece starts with the student's degree ("btech..."). Look at what comes after the degree:
        # nothing ("B.Tech"), a bracket ("B.Tech (all branches)"), or the student's own branch ("B.Tech CSE") -> match.
        if it.startswith(base):
            rest = it[len(base):]
            if rest == "" or rest.startswith("(") or not branch or rest.startswith(branch):
                return True
    # No piece matched -> this document is not for this student's programme.
    return False


# IN: a document's batch scope (e.g. "Admitted 2019-20 onwards") + the student's batch year (e.g. 2023)
#  ->  OUT: True if the document covers that batch.
# flow: scope text -> pull out years -> "onwards"? (>= first year) / a range? (between) / one year? (equal)
def batch_in_scope(scope: str, batch_year: int | None) -> bool:
    """'ALL' / '2023+' / 'Admitted 2019-20 onwards' / '2019-2022' / 'Batches 2020-21 to 2023-24' / 'Admitted 2025-26'."""
    s = (scope or "").lower()
    # No batch known, scope is "ALL", or the scope itself says "unsure" -> be generous and include it.
    if batch_year is None or _norm(s) in _ALL or "unsure" in s:
        return True
    # Collect every starting year written in the scope: "Batches 2020-21 to 2023-24" -> [2020, 2023].
    years = [int(m.group(1)) for m in _YEAR.finditer(s)]
    # No year written at all -> we cannot exclude the student, so include.
    if not years:
        return True
    # "2023+", "onwards", "after" -> open-ended: student's batch must be on or after the first year.
    if "+" in s or "onward" in s or "after" in s:
        return batch_year >= years[0]
    # Two or more years -> a range: student's batch must be between the first and the last year.
    if len(years) >= 2:
        return years[0] <= batch_year <= years[-1]
    # Exactly one year -> only that batch.
    return batch_year == years[0]


# IN: programme scope + batch scope + student (or None)  ->  OUT: True if the document is meant for this student.
# A document is in scope only if BOTH the programme AND the batch match.
def in_scope(scope_programmes: str, scope_batches: str, student: dict | None) -> bool:
    if not student:
        return True                                   # general question: every scope is relevant
    return (programme_in_scope(scope_programmes, student.get("programme"))
            and batch_in_scope(scope_batches, student.get("batch_year")))


# IN: start date + end date of a document + the "as of" date of the question
#  ->  OUT: "future" (not started yet), "expired" (already ended) or "current" (in force).
# Example: the 80% circular starts 2026-08-01, so on 2026-07-15 it is "future", on 2026-10-06 it is "current".
def is_effective(effective_from: str, effective_to: str, as_of_date: str) -> str:
    """'current' | 'future' | 'expired' (dates are ISO strings, so string compare is date compare)."""
    if effective_from and effective_from > as_of_date:
        return "future"
    if effective_to and effective_to < as_of_date:
        return "expired"
    return "current"


# IN: the "supersedes" text of a document  ->  OUT: list of (document id, section or None) it replaces.
# Example: "NSUT-BTECH-REG-2019#11.2" -> [("NSUT-BTECH-REG-2019", "11.2")]. Many targets are split by ";".
# No "#section" means the WHOLE document is replaced -> section is None.
def _targets(supersedes: str) -> list[tuple[str, str | None]]:
    out = []
    for t in (supersedes or "").split(";"):
        t = t.strip()
        if t:
            doc, _, sec = t.partition("#")
            out.append((doc, sec or None))
    return out


# IN: a chunk's section number + the section being replaced  ->  OUT: True if the chunk is inside that section.
# Example: target "11.2" matches section "11.2" and sub-sections like "11.2.1", but NOT "11.20".
# No target section (None) means the whole document is replaced, so every section matches.
def _section_match(section: str, target_sec: str | None) -> bool:
    if target_sec is None:
        return True
    s = str(section or "")
    return s == target_sec or s.startswith(target_sec + ".")


# ---------- chunks ----------
# These patterns pull numbers out of text so we can tell when two documents DISAGREE.
# _PCT: a number (with optional decimals) then optional spaces then "%", like "75%", "77.5 %". Keeps the number.
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# _MONEY: "Rs", "Rs.", "₹" or "INR", then a number of 3+ digits/commas, like "Rs. 1,25,000". re.I = ignore case.
_MONEY = re.compile(r"(?:Rs\.?|₹|INR)\s*([\d,]{3,})", re.I)
# _STOP: common question words we ignore when finding the TOPIC of a question
# (so "what is the minimum attendance" keeps only "attendance" as the topic word).
_STOP = set("what which when where with that this from have shall will your there their about would could should "
            "does required require minimum maximum student students exam exams appear".split())


# IN: chunk text  ->  OUT: the percentages and money amounts written in it, e.g. {"pct": {"80"}, "money": set()}.
# Money commas are removed so "1,25,000" and "125000" count as the same number.
def _numbers(text: str) -> dict[str, set[str]]:
    return {"pct": {m.group(1) for m in _PCT.finditer(text)},
            "money": {m.group(1).replace(",", "") for m in _MONEY.finditer(text)}}


# IN: numbers of chunk A + numbers of chunk B  ->  OUT: True if they disagree.
# Example: circular {"pct": {"80"}} vs FAQ {"pct": {"65"}} -> True (both give a %, and the % values differ).
def _differ(na: dict, nb: dict) -> bool:
    """True if both chunks state numbers of the same kind (% or money) and the numbers differ."""
    return any(na[k] and nb[k] and na[k] != nb[k] for k in na)


# IN: two chunks  ->  OUT: True if one of them (a level 1-2 document) officially replaces the other's document.
# WHY: if the circular already replaced Regulations 11.2 in step 2, we do not ALSO call other
# Regulation clauses a "conflict" with the circular.
def _related_by_supersession(a: dict, b: dict) -> bool:
    """A document that explicitly supersedes (part of) another speaks only to that part; its relation to the
    other document is settled by step 2, so other clauses of that document are not 'conflicts'."""
    def valid_sup(x: dict, y: dict) -> bool:          # only level 1-2 supersession counts (Annex A step 2)
        return int(x.get("authority_level", 3)) <= 2 and any(d == y["doc_id"] for d, _ in _targets(x.get("supersedes", "")))
    # Check both directions: A replaces B, or B replaces A.
    return valid_sup(a, b) or valid_sup(b, a)


# IN: the user's question  ->  OUT: its topic words (lowercase words of 4+ letters, minus the _STOP words).
# Example: "What is the minimum attendance?" -> {"attendance"}.
def _topic_words(query: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (query or "").lower()) if w not in _STOP}


# IN: a chunk  ->  OUT: a short name for messages, e.g. "NSUT-BTECH-REG-2019#11.2".
def _label(c: dict) -> str:
    return f"{c['doc_id']}#{c.get('section', '')}"


# MAIN FUNCTION FOR DOCUMENTS.
# IN: list of chunks (pieces of documents found by search) + date + student + question
#  ->  OUT: which chunks are in force, which were thrown out (and in which bucket), and a written reason.
# flow: chunk -> in force on date? -> in scope? -> level 5? -> applicable -> superseded? -> loses a conflict? -> answer
def resolve(chunks: list[dict], as_of_date: str, student: dict | None, query: str | None = None) -> dict:
    # One list ("bucket") per outcome, so the answer can show WHY each chunk was kept or dropped.
    applicable, future, expired, out_scope, superseded, overridden, informational = [], [], [], [], [], [], []
    notes, conflicts = [], []
    unresolved = False

    # step 1: applicability
    # Put every chunk in one bucket: not started yet -> future; ended -> expired; not for this student -> out_scope;
    # level 5 (unofficial, e.g. a forum post or student council notice) -> informational only;
    # otherwise -> applicable (still in the race).
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
    # Step 2 of Annex A: a level 1-2 document that says "in supersession of X" removes X from the list.
    # Example: circular SYN-CIRC-ATT-2026 (level 2) supersedes NSUT-BTECH-REG-2019#11.2, so the 75% chunk
    # moves from "applicable" to "superseded". A level 4 FAQ saying "supersedes" would be ignored here.
    for s in [c for c in applicable if int(c.get("authority_level", 3)) <= 2]:
        for doc, sec in _targets(s.get("supersedes", "")):
            for c in list(applicable):
                if c["doc_id"] == doc and _section_match(c.get("section"), sec):
                    applicable.remove(c)
                    superseded.append(c)
                    notes.append(f"{s['doc_id']} supersedes {doc}{'#' + sec if sec else ''} (step 2)")
    # Warn about a document that WILL replace something later but is not in force yet.
    # Example: asked on 2026-07-15, the 80% circular is future -> "upcoming: ... will supersede 11.2".
    for f in future:
        if _targets(f.get("supersedes", "")):
            notes.append(f"upcoming: {f['doc_id']} (effective {f.get('effective_from')}) will supersede "
                         f"{f.get('supersedes')} — not yet in force on {as_of_date}")

    # steps 3-5: different documents that state different numbers on the question's topic
    # Compare every pair (a, b) of still-applicable chunks from DIFFERENT documents.
    topic = _topic_words(query)
    for a in list(applicable):
        for b in list(applicable):
            # Skip: same chunk, same document, or one of them already lost to someone else.
            if a is b or a["doc_id"] == b["doc_id"] or a not in applicable or b not in applicable:
                continue
            # Skip: already settled in step 2 (one officially replaces the other).
            if _related_by_supersession(a, b):
                continue
            # A real conflict needs: different numbers (%, money) AND both talk about the question's topic
            # (a shared topic word, e.g. "attendance"). Otherwise, skip this pair.
            shared = {w for w in topic if w in a["text"].lower() and w in b["text"].lower()} if topic else set()
            if not _differ(_numbers(a["text"]), _numbers(b["text"])) or (topic and not shared):
                continue
            # la, lb = authority levels (1 = highest, e.g. Regulations; 4 = FAQ; 5 = unofficial).
            la, lb = int(a.get("authority_level", 3)), int(b.get("authority_level", 3))
            # Step 3 (authority): different levels -> the LOWER number wins.
            # Example: circular 80% (level 2) beats CSE FAQ 65% (level 4); the FAQ goes to "overridden".
            if la != lb:
                win, lose = (a, b) if la < lb else (b, a)
                applicable.remove(lose)
                overridden.append(lose)
                conflicts.append(f"{_label(lose)} (level {max(la, lb)}) conflicts with {_label(win)} "
                                 f"(level {min(la, lb)}); higher authority prevails (step 3)")
            # Step 4 (recency): same level but different start dates -> the LATER start date wins.
            elif a.get("effective_from") != b.get("effective_from"):
                win, lose = (a, b) if a.get("effective_from", "") > b.get("effective_from", "") else (b, a)
                applicable.remove(lose)
                overridden.append(lose)
                conflicts.append(f"{_label(lose)} conflicts with {_label(win)} (same level {la}); "
                                 f"later effective_from {win.get('effective_from')} prevails (step 4)")
            # Step 5 (unresolved): same level AND same date but different numbers -> we do not guess;
            # we flag it and tell the student to contact the office.
            else:
                unresolved = True
                conflicts.append(f"UNRESOLVED: {_label(a)} and {_label(b)} have the same authority (level {la}) and "
                                 f"effective date but state different values — contact the issuing office (step 5)")

    # Order the winners: highest authority first, then newest start date, then best search score.
    applicable.sort(key=lambda c: (int(c.get("authority_level", 3)), _neg(c.get("effective_from", "")),
                                   -float(c.get("score", 0))))
    # One readable sentence explaining all decisions (shown to the user and saved in the audit log).
    decision = "; ".join(notes + conflicts) or "no conflicts among applicable sources"
    # Return every bucket, so the answer can say "80% applies; 75% was superseded; FAQ 65% was overridden".
    return {"applicable": applicable, "excluded_future": future, "expired": expired, "out_of_scope": out_scope,
            "superseded": superseded, "overridden": overridden, "informational": informational,
            "conflicts": conflicts + [n for n in notes if n.startswith("upcoming")],
            "decision": decision, "unresolved": unresolved}


# IN: a date string  ->  OUT: a "flipped" string so that normal A-to-Z sorting puts LATER dates first.
# Trick: replace each character by its "opposite" character (255 minus its code), which reverses the order.
# Example: "2026-08-01" now sorts before "2019-07-01".
def _neg(date: str) -> str:
    """Sort key making later dates come first."""
    return "".join(chr(255 - ord(ch)) for ch in date)


# ---------- rule_registry rows ----------
# Same Annex A steps, but for rows of the rule_registry table (clean numbers like value=80) instead of text chunks.
# IN: one rule row  ->  OUT: (authority level, "supersedes" text) of the document the rule came from.
# Example: row ATT-MIN-02 (source SYN-CIRC-ATT-2026) -> (2, "NSUT-BTECH-REG-2019#11.2").
def _rule_doc(row: dict) -> tuple[int, str]:
    """authority_level + supersedes of the rule's source document (row may carry them already, e.g. in tests)."""
    # Tests can put the level directly on the row; then use it and skip the lookup.
    if "authority_level" in row:
        return int(row["authority_level"]), row.get("doc_supersedes", "")
    # Otherwise look up the source document in the Source Register (imported here, only when needed).
    from app.retrieval import get_source
    src = get_source(row["source_doc_id"]) or {}
    return int(src.get("authority_level", 3)), src.get("supersedes", "")


# MAIN FUNCTION FOR RULES.
# IN: all rule rows for ONE parameter (e.g. min_attendance_pct: 75, 80, 65) + date + student
#  ->  OUT: the one winning rule (e.g. 80) + the reason + any conflicts / upcoming changes.
# flow: rows -> in force on date + in scope + not level 5? -> remove superseded -> sort by level, then newest -> winner
def pick_rule(rows: list[dict], as_of_date: str, student: dict | None) -> dict:
    """Annex A over rule rows of ONE parameter -> {rule, decision, conflicts, unresolved, upcoming, candidates}."""
    # Step 1: keep only rows in force today and meant for this student. Future rows are remembered as "upcoming".
    # Each row is copied (dict(r)) and gets two helper fields: _auth (level) and _sup (what its document replaces).
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
    # Example: ATT-MIN-02 (80%, circular, level 2) supersedes ATT-MIN-01 (75%, Regulations 11.2) -> 75% row removed.
    for s in [c for c in cands if c["_auth"] <= 2]:
        for doc, sec in _targets(s["_sup"]):
            for c in list(cands):
                if c is not s and c["source_doc_id"] == doc and _section_match(c.get("source_section"), sec):
                    cands.remove(c)
                    notes.append(f"{s['rule_id']} ({s['source_doc_id']}) supersedes {c['rule_id']} "
                                 f"({doc}{'#' + sec if sec else ''}) (step 2)")
    # Nothing left -> no rule in force for this student on this date.
    if not cands:
        return {"rule": None, "decision": "; ".join(notes) or "no rule in force", "conflicts": conflicts,
                "unresolved": False, "upcoming": upcoming, "candidates": 0}
    # steps 3-4: authority, then recency
    # Sort: lowest level number first (highest authority), and among equals, the newest start date first.
    # The first row after sorting is the winner.
    cands.sort(key=lambda c: (c["_auth"], _neg(c.get("effective_from", ""))))
    win = cands[0]
    unresolved = False
    # Explain why every other row lost (only rows with a DIFFERENT value count as conflicts).
    for other in cands[1:]:
        if str(other["value"]) == str(win["value"]):
            continue
        # Step 3: the other row's document has lower authority. Example: FAQ 65% (level 4) loses to circular 80% (level 2).
        if other["_auth"] > win["_auth"]:
            conflicts.append(f"{other['rule_id']} ({other['source_doc_id']}, level {other['_auth']}) says "
                             f"{other['value']} but {win['rule_id']} (level {win['_auth']}) prevails (step 3)")
        # Step 4: same level, older start date -> replaced by the newer rule.
        elif other.get("effective_from") != win.get("effective_from"):
            conflicts.append(f"{other['rule_id']} ({other['effective_from']}) replaced by later "
                             f"{win['rule_id']} ({win['effective_from']}) (step 4)")
        # Step 5: same level, same date, different value -> cannot decide; flag it.
        else:
            unresolved = True
            conflicts.append(f"UNRESOLVED: {win['rule_id']} and {other['rule_id']} same authority and date, "
                             f"different values (step 5)")
    # Remove the helper fields (_auth, _sup) before returning the winning rule.
    rule = {k: v for k, v in win.items() if not k.startswith("_")}
    # If unresolved, return NO rule (we never guess). Otherwise return the winner and the reasons.
    return {"rule": None if unresolved else rule, "decision": "; ".join(notes + conflicts) or "single rule in force",
            "conflicts": conflicts, "unresolved": unresolved, "upcoming": upcoming, "candidates": len(cands)}


# IN: a parameter name (e.g. "min_attendance_pct") + date + student  ->  OUT: the rule in force (pick_rule's answer).
# Used by tools.py. Example: S1002 has 77.5% in CS201; after 2026-08-01 this returns 80%, so 77.5% is not enough.
# flow: parameter -> read all its rows from the database -> pick_rule -> winning rule
def get_rule_in_force(parameter: str, as_of_date: str, student: dict | None) -> dict:
    """Convenience for tools.py: fetch all rows of a parameter from rule_registry and apply pick_rule."""
    from app.db import connect
    # Open the database and read every rule_registry row for this parameter ("?" safely fills in the name).
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM rule_registry WHERE parameter = ?", (parameter,))]
    return pick_rule(rows, as_of_date, student)
