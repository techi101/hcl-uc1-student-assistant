"""Deterministic tools over SQLite. Thresholds ONLY from rule_registry (via Annex A precedence). Shapes: CONTRACT.md.
Every tool returns plain JSON-serialisable dicts and never raises for 'not found' (returns {"error": ...})."""
# WHAT THIS FILE IS: the "calculator" part of the assistant. The LLM never does maths or decides a verdict.
# It calls these small functions, which read the SQLite database and the rule table, and give back facts.
# Big flow: question -> LLM picks a tool -> tool reads DB + rule in force (Annex A) -> exact answer + rule id to cite
import re

from app.db import connect
from app.precedence import get_rule_in_force


# Month name -> month number: {"JAN": 1, "FEB": 2, ..., "DEC": 12}. Used to sort exam sessions in real time order.
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}


# IN: exam session text like "2026-JUL"  ->  OUT: a sortable pair (2026, 7)
# WHY: sorting the plain text put "2026-JUL" before "2026-MAY" (J comes before M). A test caught this bug.
# So we sort by (year, month) numbers instead. Bad/missing parts become 0 so it never crashes.
def session_key(session: str) -> tuple[int, int]:
    """'2026-JUL' -> (2026, 7). Plain string order is wrong ('2026-JUL' < '2026-MAY'), found by test_tools."""
    # split "2026-JUL" at the dash -> year "2026", month "JUL"
    year, _, mon = str(session).partition("-")
    # year as a number; month via the MONTHS table (first 3 letters), or as a number if it was written "07"
    return (int(year) if year.isdigit() else 0, MONTHS.get(mon.upper()[:3], int(mon) if mon.isdigit() else 0))


# IN: an SQL query + its values  ->  OUT: the first matching row as a dict, or None if nothing matched
# Small helper so every "fetch one row" lookup is one line. The "?" marks are filled safely (no SQL injection).
def _one(sql: str, args: tuple) -> dict | None:
    with connect() as con:
        row = con.execute(sql, args).fetchone()
    return dict(row) if row else None


# IN: student id like "S1002"  ->  OUT: that student's row (name, programme, batch, CGPA, backlogs) or None
# SQL in words: "give me every column of the student whose id is this one"
def get_student(student_id: str) -> dict | None:
    return _one("SELECT * FROM students WHERE student_id = ?", (student_id,))


# IN: the user's words + the student's programme  ->  OUT: list of matching course rows
# Flow: try exact course code first (CS201) -> else try course name words ("data structures") -> prefer own programme
def find_course(text: str, programme: str | None) -> list[dict]:
    """Match a course by code (CS201) or by name words ('data structures'), within the student's programme first."""
    # load all courses (only 12 rows, so reading all is fine) and lower-case the question
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM courses")]
    t = (text or "").lower()
    # Step 1, by code. Regex in words: find the code (e.g. "cs201") as a whole word, not inside another word.
    # \b = word edge; re.escape makes sure any special characters in the code are treated as plain letters.
    by_code = [r for r in rows if re.search(rf"\b{re.escape(r['course_code'].lower())}\b", t)]
    if by_code:
        return by_code
    # Step 2, by name. core() cleans a course name: regex removes any "(...)" bracket part, then lower-case.
    def core(name: str) -> str:                          # "Economics (ECE)" -> "economics"
        return re.sub(r"\s*\(.*?\)", "", name).lower().strip()
    # A course matches if its full clean name is in the question, OR (for names longer than 4 letters)
    # every long word of the name (more than 3 letters) appears somewhere in the question.
    by_name = [r for r in rows if core(r["course_name"]) in t or
               (len(core(r["course_name"])) > 4 and all(w in t for w in core(r["course_name"]).split() if len(w) > 3))]
    # Step 3: if both CSE and ECE have "Economics", keep the one from the student's own programme (if any)
    own = [r for r in by_name if programme and r["programme"] == programme]
    return own or by_name


# IN: student id + course code  ->  OUT: classes held, classes attended, and the attendance % (or an error)
# Example: S1002 CS201 -> 31 attended out of 40 held -> 77.5%
def get_attendance(student_id: str, course_code: str) -> dict:
    # SQL in words: "for this student and this course, give me classes held and classes attended"
    row = _one("SELECT classes_held, classes_attended FROM attendance WHERE student_id = ? AND course_code = ?",
               (student_id, course_code))
    # no row -> say so clearly (we never guess)
    if not row:
        return {"error": f"no attendance record for {course_code}"}
    # % is worked out fresh by code every time (31 / 40 * 100 = 77.5), so it can never go stale in the DB
    row["attendance_pct"] = round(100 * row["classes_attended"] / row["classes_held"], 2)   # computed, never stored
    return row


# IN: student id (+ optional course code)  ->  OUT: all exam result rows, oldest exam session first
def get_results(student_id: str, course_code: str | None = None) -> list[dict]:
    # SQL in words: "all results of this student"; if a course is given, add "and only this course"
    sql, args = "SELECT * FROM results WHERE student_id = ?", [student_id]
    if course_code:
        sql += " AND course_code = ?"
        args.append(course_code)
    with connect() as con:
        rows = [dict(r) for r in con.execute(sql, args)]
    # sort by (year, month) using session_key, NOT by text (text put 2026-JUL before 2026-MAY)
    return sorted(rows, key=lambda r: session_key(r["exam_session"]))


# IN: student id  ->  OUT: backlog count stored for the student + list of courses not yet passed
# Flow: all results oldest -> newest -> keep only the latest result per course -> anything not PASS = backlog
def get_backlogs(student_id: str) -> dict:
    s = get_student(student_id) or {}
    latest: dict[str, str] = {}
    # loop over results in time order; a later attempt overwrites an earlier one (FAIL in MAY, PASS in JUL -> PASS)
    for r in get_results(student_id):                      # chronological, so the last attempt wins
        latest[r["course_code"]] = r["result"]
    return {"active_backlogs": s.get("active_backlogs"),
            "uncleared_courses": sorted(c for c, res in latest.items() if res != "PASS")}


# IN: rule name (e.g. "min_attendance_pct") + date + student  ->  OUT: the ONE rule in force that day for that student
# The choosing is done by Annex A precedence code (app/precedence.py), e.g. on 2026-08-01 or later
# ATT-MIN-02 = 80% (circular) wins over ATT-MIN-01 = 75% (Regulations 11.2).
def _rule(parameter: str, as_of_date: str, student: dict) -> dict:
    return get_rule_in_force(parameter, as_of_date, student)


# IN: one rule row  ->  OUT: a short citation: rule id, value (">=80"), document id and section
# This is what lets the answer say "ATT-MIN-02, SYN-CIRC-ATT-2026 section 1".
def _ref(rule: dict) -> dict:
    """The citation trail for a threshold: rule id, value, and the document clause it came from (R5)."""
    return {"rule_id": rule["rule_id"], "value": f"{rule['operator']}{rule['value']}",
            "source_doc_id": rule["source_doc_id"], "source_section": rule["source_section"]}


# IN: student id + course code + date  ->  OUT: verdict + the rule rows used (for citations)
# Flow: attendance row -> % -> rule in force (Annex A) -> compare -> verdict
# Example: S1002 CS201 31/40 = 77.5%. On 2026-08-01 or later the rule is ATT-MIN-02 = 80% -> below 80 but
# above the 60% floor -> ELIGIBLE_ONLY_WITH_RELAXATION. Before that date ATT-MIN-01 = 75% -> ELIGIBLE.
def check_exam_eligibility(student_id: str, course_code: str, as_of_date: str) -> dict:
    """Attendance eligibility for MSE/ESE, 3 tiers (NSUT Regulations 11.2-11.7):
    >= min -> ELIGIBLE; >= floor -> ELIGIBLE_ONLY_WITH_RELAXATION; else NOT_ELIGIBLE."""
    # stop early with a clear error if the student or the attendance row does not exist
    student = get_student(student_id)
    if not student:
        return {"error": "unknown student"}
    att = get_attendance(student_id, course_code)
    if "error" in att:
        return att
    # fetch the two rules in force on that date: the minimum (75% or 80%) and the floor (ATT-FLOOR-01 = 60%, 11.6)
    rmin, rfloor = _rule("min_attendance_pct", as_of_date, student), _rule("attendance_floor_pct", as_of_date, student)
    # if no minimum rule could be chosen (e.g. two sources clash), return the problem instead of guessing
    if not rmin["rule"]:
        return {"error": "no minimum-attendance rule in force", "decision": rmin["decision"],
                "unresolved": rmin["unresolved"], "conflicts": rmin["conflicts"]}
    # the numbers to compare: student's %, the minimum %, and the floor % (None if there is no floor rule)
    pct, mn = att["attendance_pct"], float(rmin["rule"]["value"])
    fl = float(rfloor["rule"]["value"]) if rfloor["rule"] else None
    # 3 tiers (Regulations 11.2-11.7): at/above minimum -> ELIGIBLE; at/above 60% floor -> needs relaxation; below -> NOT_ELIGIBLE
    if pct >= mn:
        result = "ELIGIBLE"
    elif fl is not None and pct >= fl:
        result = "ELIGIBLE_ONLY_WITH_RELAXATION"
    else:
        result = "NOT_ELIGIBLE"
    # build the answer: verdict + the raw numbers + which rule and which document clause it came from.
    # The floor rule is cited only when it mattered (verdict is not plain ELIGIBLE).
    # "conflicts" and "upcoming" tell the user about clashing sources or a rule change coming soon.
    return {"result": result, "attendance_pct": pct, "classes_held": att["classes_held"],
            "classes_attended": att["classes_attended"],
            "rule_id": rmin["rule"]["rule_id"], "value": f">={rmin['rule']['value']}%",
            "source_doc_id": rmin["rule"]["source_doc_id"], "source_section": rmin["rule"]["source_section"],
            "floor_rule_id": rfloor["rule"]["rule_id"] if rfloor["rule"] else None,
            "floor_value": f">={fl}%" if fl is not None else None,
            "floor_source": f"{rfloor['rule']['source_doc_id']}#{rfloor['rule']['source_section']}" if rfloor["rule"] else None,
            "rules_used": [_ref(rmin["rule"])] + ([_ref(rfloor["rule"])] if rfloor["rule"] and result != "ELIGIBLE" else []),
            "precedence_decision": rmin["decision"], "conflicts": rmin["conflicts"] + rfloor["conflicts"],
            "upcoming": rmin["upcoming"] + rfloor["upcoming"]}


# IN: student id + course code + date  ->  OUT: marks, recorded result, and PASS/FAIL worked out again by code
# Pass rule: ESE >= 30% (Regulations 12.7) AND total >= 35 (Table 5). Both must be true.
# Example: S1006 CS201 ESE 14/50 = 28% -> FAIL, even though total is 44 (above 35).
def check_course_pass(student_id: str, course_code: str, as_of_date: str) -> dict:
    """Did the student pass? Uses min_ese_pct (12.7) and min_total_marks (9.5) from rule_registry."""
    # get all attempts for this course (oldest first); none -> clear error
    student = get_student(student_id) or {}
    res = get_results(student_id, course_code)
    if not res:
        return {"error": f"no result for {course_code}"}
    # the last attempt is the one that counts (e.g. a summer re-attempt)
    last = res[-1]
    # fetch the two pass rules in force: PASS-ESE-01 (30%) and PASS-TOTAL-01 (35 marks)
    rese, rtot = _rule("min_ese_pct", as_of_date, student), _rule("min_total_marks", as_of_date, student)
    # start the answer with the facts straight from the database
    out = {"course_code": course_code, "exam_session": last["exam_session"], "recorded_result": last["result"],
           "internal_marks": last["internal_marks"], "external_marks": last["external_marks"],
           "total_marks": last["total_marks"], "max_marks": last["max_marks"], "attempts": len(res)}
    # re-check PASS/FAIL only if both rules exist and the student actually sat the exam (not ABSENT / DETAINED)
    if rese["rule"] and rtot["rule"] and last["result"] not in ("ABSENT", "DETAINED"):
        # ESE (end-semester exam) is out of 50 (half of 100), so ESE % = external marks / 50 * 100
        ext_max = (last["max_marks"] or 100) / 2          # NSUT theory: ESE = 50 of 100 (Regulations Table 1)
        ese_pct = round(100 * (last["external_marks"] or 0) / ext_max, 2)
        # add the % and the rule ids, then the verdict: PASS only if ESE % >= 30 AND total >= 35, else FAIL
        out.update({"ese_pct": ese_pct, "ese_rule": f"{rese['rule']['rule_id']} >= {rese['rule']['value']}%",
                    "total_rule": f"{rtot['rule']['rule_id']} >= {rtot['rule']['value']}",
                    "rules_used": [_ref(rese["rule"]), _ref(rtot["rule"])],
                    "computed_result": "PASS" if ese_pct >= float(rese["rule"]["value"])
                    and (last["total_marks"] or 0) >= float(rtot["rule"]["value"]) else "FAIL"})
    return out
