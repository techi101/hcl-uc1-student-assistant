"""Deterministic tools over the generated data (data/students_csv loaded into SQLite). No LLM.
Edge-case IDs are documented in data/students_csv/edge_cases.json."""
from app import tools
from app.db import connect
from app.precedence import get_rule_in_force

AFTER, BEFORE = "2026-10-06", "2026-07-15"     # circular (80%) in force from 2026-08-01


def test_attendance_is_computed_not_stored():
    a = tools.get_attendance("S1002", "CS201")
    assert (a["classes_held"], a["classes_attended"], a["attendance_pct"]) == (40, 31, 77.5)
    with connect() as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(attendance)")]
    assert "attendance_pct" not in cols


def test_exactly_at_threshold_is_eligible():
    assert tools.check_exam_eligibility("S1001", "CS201", AFTER)["result"] == "ELIGIBLE"            # 80.0% vs 80%


def test_one_class_below_threshold_needs_relaxation():
    r = tools.check_exam_eligibility("S1002", "CS201", AFTER)                                       # 77.5% vs 80%
    assert r["result"] == "ELIGIBLE_ONLY_WITH_RELAXATION" and r["rule_id"] == "ATT-MIN-02"


def test_rule_in_force_depends_on_as_of_date():
    assert tools.check_exam_eligibility("S1003", "CS201", BEFORE)["result"] == "ELIGIBLE"           # 75% vs 75%
    assert tools.check_exam_eligibility("S1003", "CS201", AFTER)["result"] == "ELIGIBLE_ONLY_WITH_RELAXATION"


def test_below_floor_is_not_eligible():
    assert tools.check_exam_eligibility("S1005", "CS201", AFTER)["result"] == "NOT_ELIGIBLE"        # 55%


def test_cse_faq_65_never_applies():
    assert get_rule_in_force("min_attendance_pct", AFTER, {"programme": "B.Tech CSE", "batch_year": 2023})["rule"]["value"] == "80"


def test_threshold_comes_from_registry_not_code():
    with connect() as con:
        con.execute("UPDATE rule_registry SET value = '70' WHERE rule_id = 'ATT-MIN-02'")
    try:
        assert tools.check_exam_eligibility("S1002", "CS201", AFTER)["result"] == "ELIGIBLE"        # 77.5 >= 70
    finally:
        with connect() as con:
            con.execute("UPDATE rule_registry SET value = '80' WHERE rule_id = 'ATT-MIN-02'")


def test_ese_below_30_percent_fails_even_with_total_44():
    r = tools.check_course_pass("S1006", "CS201", AFTER)
    assert r["computed_result"] == "FAIL" and r["ese_pct"] == 28.0 and r["total_marks"] == 44


def test_total_34_fails():
    assert tools.check_course_pass("S1007", "CS201", AFTER)["computed_result"] == "FAIL"


def test_reregistration_clears_backlog():
    assert "CS203" not in tools.get_backlogs("S1010")["uncleared_courses"]
    assert len(tools.get_backlogs("S1009")["uncleared_courses"]) >= 3


def test_course_lookup_by_name_and_ambiguity():
    assert [c["course_code"] for c in tools.find_course("my data structures attendance", "B.Tech CSE")] == ["CS201"]
    assert len(tools.find_course("economics", None)) == 2            # HS201 + HS202 -> clarification needed


def test_unknown_record_returns_error_not_exception():
    assert "error" in tools.get_attendance("S1001", "EC201")
