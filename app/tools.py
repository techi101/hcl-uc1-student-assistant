"""Deterministic tools over SQLite. Thresholds ONLY from rule_registry (via Annex A precedence). Shapes: CONTRACT.md.
Every tool returns plain JSON-serialisable dicts and never raises for 'not found' (returns {"error": ...})."""
import re

from app.db import connect
from app.precedence import get_rule_in_force


MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}


def session_key(session: str) -> tuple[int, int]:
    """'2026-JUL' -> (2026, 7). Plain string order is wrong ('2026-JUL' < '2026-MAY'), found by test_tools."""
    year, _, mon = str(session).partition("-")
    return (int(year) if year.isdigit() else 0, MONTHS.get(mon.upper()[:3], int(mon) if mon.isdigit() else 0))


def _one(sql: str, args: tuple) -> dict | None:
    with connect() as con:
        row = con.execute(sql, args).fetchone()
    return dict(row) if row else None


def get_student(student_id: str) -> dict | None:
    return _one("SELECT * FROM students WHERE student_id = ?", (student_id,))


def find_course(text: str, programme: str | None) -> list[dict]:
    """Match a course by code (CS201) or by name words ('data structures'), within the student's programme first."""
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM courses")]
    t = (text or "").lower()
    by_code = [r for r in rows if re.search(rf"\b{re.escape(r['course_code'].lower())}\b", t)]
    if by_code:
        return by_code
    def core(name: str) -> str:                          # "Economics (ECE)" -> "economics"
        return re.sub(r"\s*\(.*?\)", "", name).lower().strip()
    by_name = [r for r in rows if core(r["course_name"]) in t or
               (len(core(r["course_name"])) > 4 and all(w in t for w in core(r["course_name"]).split() if len(w) > 3))]
    own = [r for r in by_name if programme and r["programme"] == programme]
    return own or by_name


def get_attendance(student_id: str, course_code: str) -> dict:
    row = _one("SELECT classes_held, classes_attended FROM attendance WHERE student_id = ? AND course_code = ?",
               (student_id, course_code))
    if not row:
        return {"error": f"no attendance record for {course_code}"}
    row["attendance_pct"] = round(100 * row["classes_attended"] / row["classes_held"], 2)   # computed, never stored
    return row


def get_results(student_id: str, course_code: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM results WHERE student_id = ?", [student_id]
    if course_code:
        sql += " AND course_code = ?"
        args.append(course_code)
    with connect() as con:
        rows = [dict(r) for r in con.execute(sql, args)]
    return sorted(rows, key=lambda r: session_key(r["exam_session"]))


def get_backlogs(student_id: str) -> dict:
    s = get_student(student_id) or {}
    latest: dict[str, str] = {}
    for r in get_results(student_id):                      # chronological, so the last attempt wins
        latest[r["course_code"]] = r["result"]
    return {"active_backlogs": s.get("active_backlogs"),
            "uncleared_courses": sorted(c for c, res in latest.items() if res != "PASS")}


def _rule(parameter: str, as_of_date: str, student: dict) -> dict:
    return get_rule_in_force(parameter, as_of_date, student)


def _ref(rule: dict) -> dict:
    """The citation trail for a threshold: rule id, value, and the document clause it came from (R5)."""
    return {"rule_id": rule["rule_id"], "value": f"{rule['operator']}{rule['value']}",
            "source_doc_id": rule["source_doc_id"], "source_section": rule["source_section"]}


def check_exam_eligibility(student_id: str, course_code: str, as_of_date: str) -> dict:
    """Attendance eligibility for MSE/ESE, 3 tiers (NSUT Regulations 11.2-11.7):
    >= min -> ELIGIBLE; >= floor -> ELIGIBLE_ONLY_WITH_RELAXATION; else NOT_ELIGIBLE."""
    student = get_student(student_id)
    if not student:
        return {"error": "unknown student"}
    att = get_attendance(student_id, course_code)
    if "error" in att:
        return att
    rmin, rfloor = _rule("min_attendance_pct", as_of_date, student), _rule("attendance_floor_pct", as_of_date, student)
    if not rmin["rule"]:
        return {"error": "no minimum-attendance rule in force", "decision": rmin["decision"],
                "unresolved": rmin["unresolved"], "conflicts": rmin["conflicts"]}
    pct, mn = att["attendance_pct"], float(rmin["rule"]["value"])
    fl = float(rfloor["rule"]["value"]) if rfloor["rule"] else None
    if pct >= mn:
        result = "ELIGIBLE"
    elif fl is not None and pct >= fl:
        result = "ELIGIBLE_ONLY_WITH_RELAXATION"
    else:
        result = "NOT_ELIGIBLE"
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


def check_course_pass(student_id: str, course_code: str, as_of_date: str) -> dict:
    """Did the student pass? Uses min_ese_pct (12.7) and min_total_marks (9.5) from rule_registry."""
    student = get_student(student_id) or {}
    res = get_results(student_id, course_code)
    if not res:
        return {"error": f"no result for {course_code}"}
    last = res[-1]
    rese, rtot = _rule("min_ese_pct", as_of_date, student), _rule("min_total_marks", as_of_date, student)
    out = {"course_code": course_code, "exam_session": last["exam_session"], "recorded_result": last["result"],
           "internal_marks": last["internal_marks"], "external_marks": last["external_marks"],
           "total_marks": last["total_marks"], "max_marks": last["max_marks"], "attempts": len(res)}
    if rese["rule"] and rtot["rule"] and last["result"] not in ("ABSENT", "DETAINED"):
        ext_max = (last["max_marks"] or 100) / 2          # NSUT theory: ESE = 50 of 100 (Regulations Table 1)
        ese_pct = round(100 * (last["external_marks"] or 0) / ext_max, 2)
        out.update({"ese_pct": ese_pct, "ese_rule": f"{rese['rule']['rule_id']} >= {rese['rule']['value']}%",
                    "total_rule": f"{rtot['rule']['rule_id']} >= {rtot['rule']['value']}",
                    "rules_used": [_ref(rese["rule"]), _ref(rtot["rule"])],
                    "computed_result": "PASS" if ese_pct >= float(rese["rule"]["value"])
                    and (last["total_marks"] or 0) >= float(rtot["rule"]["value"]) else "FAIL"})
    return out
