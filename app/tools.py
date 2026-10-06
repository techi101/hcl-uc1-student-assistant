"""Deterministic tools over SQLite. Thresholds ONLY from rule_registry (via Annex A precedence). Shapes: CONTRACT.md.
Every tool returns plain JSON-serialisable dicts and never raises for 'not found' (returns {"error": ...})."""
import re

from app.db import connect
from app.precedence import get_rule_in_force


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
    by_name = [r for r in rows if r["course_name"].lower() in t or
               (len(r["course_name"]) > 4 and all(w in t for w in r["course_name"].lower().split() if len(w) > 3))]
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
        return [dict(r) for r in con.execute(sql + " ORDER BY exam_session", args)]


def get_backlogs(student_id: str) -> dict:
    s = get_student(student_id) or {}
    with connect() as con:
        failed = [r[0] for r in con.execute(
            "SELECT DISTINCT course_code FROM results r WHERE student_id = ? AND result IN ('FAIL','ABSENT','DETAINED') "
            "AND NOT EXISTS (SELECT 1 FROM results p WHERE p.student_id = r.student_id AND p.course_code = r.course_code "
            "AND p.result = 'PASS' AND p.exam_session > r.exam_session)", (student_id,))]
    return {"active_backlogs": s.get("active_backlogs"), "uncleared_courses": failed}


def _rule(parameter: str, as_of_date: str, student: dict) -> dict:
    return get_rule_in_force(parameter, as_of_date, student)


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
                    "computed_result": "PASS" if ese_pct >= float(rese["rule"]["value"])
                    and (last["total_marks"] or 0) >= float(rtot["rule"]["value"]) else "FAIL"})
    return out
