"""Deterministic tools over the generated data (data/students_csv loaded into SQLite). No LLM.
Edge-case IDs are documented in data/students_csv/edge_cases.json."""
# WHAT THIS FILE IS: tests for app/tools.py, the code (not AI) that looks up a student's records and computes verdicts.
# They run on the real SQLite database built from data/students_csv. Each student ID is a planted edge case
# (listed in data/students_csv/edge_cases.json). Real example: S1001 has exactly 32/40 = 80.0% in CS201,
# and the rule in force on 2026-10-06 is 80%, so the verdict must be ELIGIBLE (meeting the minimum exactly counts).
# pytest runs every test_* function; "assert X" fails the test if X is False.
# connect = opens the SQLite database. get_rule_in_force = asks precedence.py which rule row wins on a date.
from app import tools
from app.db import connect
from app.precedence import get_rule_in_force

# Two dates used everywhere: AFTER = the circular's 80% is in force, BEFORE = the regulation's 75% applies.
AFTER, BEFORE = "2026-10-06", "2026-07-15"     # circular (80%) in force from 2026-08-01


# PROVES: S1002's attendance (31 of 40 = 77.5%) is calculated from class counts, and the attendance table has NO stored % column.
# WHY: a stored percentage can go stale or be typed wrong. Computing it from held/attended every time keeps one source of truth.
# PRAGMA table_info(attendance) = SQLite command that lists a table's columns; r[1] is each column's name.
def test_attendance_is_computed_not_stored():
    a = tools.get_attendance("S1002", "CS201")
    assert (a["classes_held"], a["classes_attended"], a["attendance_pct"]) == (40, 31, 77.5)
    with connect() as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(attendance)")]
    assert "attendance_pct" not in cols


# PROVES: S1001 at exactly 80.0% against an 80% rule is ELIGIBLE.
# WHY: the rule says "minimum 80%", so >= is right and > would wrongly reject this student. Boundary bugs are the classic mistake.
def test_exactly_at_threshold_is_eligible():
    assert tools.check_exam_eligibility("S1001", "CS201", AFTER)["result"] == "ELIGIBLE"            # 80.0% vs 80%


# PROVES: S1002 at 77.5% (one class short of 80%) gets ELIGIBLE_ONLY_WITH_RELAXATION, citing rule ATT-MIN-02.
# WHY: the Regulations allow relaxation above the 60% floor. The answer must say "only with relaxation", not a flat yes or no,
# and it must name the rule row it used.
def test_one_class_below_threshold_needs_relaxation():
    r = tools.check_exam_eligibility("S1002", "CS201", AFTER)                                       # 77.5% vs 80%
    assert r["result"] == "ELIGIBLE_ONLY_WITH_RELAXATION" and r["rule_id"] == "ATT-MIN-02"


# PROVES: S1003 at exactly 75% is ELIGIBLE on 2026-07-15 (75% rule) but needs relaxation on 2026-10-06 (80% rule).
# WHY: same student, same data, different date -> different verdict. The as_of_date really drives which rule is used.
def test_rule_in_force_depends_on_as_of_date():
    assert tools.check_exam_eligibility("S1003", "CS201", BEFORE)["result"] == "ELIGIBLE"           # 75% vs 75%
    assert tools.check_exam_eligibility("S1003", "CS201", AFTER)["result"] == "ELIGIBLE_ONLY_WITH_RELAXATION"


# PROVES: S1005 at 55% (below the 60% floor) is NOT_ELIGIBLE.
# WHY: below the floor no relaxation is possible, so the verdict must be a clear no.
def test_below_floor_is_not_eligible():
    assert tools.check_exam_eligibility("S1005", "CS201", AFTER)["result"] == "NOT_ELIGIBLE"        # 55%


# PROVES: for a B.Tech CSE student on 2026-10-06 the rule in force is 80%, never the CSE FAQ's 65%.
# WHY: the FAQ is level 4 and the circular is level 2. A lower-authority document must never lower the bar.
def test_cse_faq_65_never_applies():
    assert get_rule_in_force("min_attendance_pct", AFTER, {"programme": "B.Tech CSE", "batch_year": 2023})["rule"]["value"] == "80"


# PROVES: change the 80% rule to 70% in the database and S1002 (77.5%) becomes ELIGIBLE; then 80% is put back.
# WHY: hard rule 2: thresholds live in the rule_registry table, not as numbers in Python. If 80 were hard-coded, this would fail.
# try/finally = the finally block always runs, even if the assert fails, so the database is restored for the other tests.
def test_threshold_comes_from_registry_not_code():
    with connect() as con:
        con.execute("UPDATE rule_registry SET value = '70' WHERE rule_id = 'ATT-MIN-02'")
    try:
        assert tools.check_exam_eligibility("S1002", "CS201", AFTER)["result"] == "ELIGIBLE"        # 77.5 >= 70
    finally:
        with connect() as con:
            con.execute("UPDATE rule_registry SET value = '80' WHERE rule_id = 'ATT-MIN-02'")


# PROVES: S1006 has total 44 (above 35) but ESE 14/50 = 28% (below 30%), so the result is FAIL.
# WHY: the pass rule needs BOTH conditions (clause 12.7 for ESE). A tool that only checked the total would wrongly say PASS.
def test_ese_below_30_percent_fails_even_with_total_44():
    r = tools.check_course_pass("S1006", "CS201", AFTER)
    assert r["computed_result"] == "FAIL" and r["ese_pct"] == 28.0 and r["total_marks"] == 44


# PROVES: S1007 with total 34 (one below 35) is FAIL.
# WHY: the boundary on the other pass rule; 34 < 35 must fail even though the ESE part was fine.
def test_total_34_fails():
    assert tools.check_course_pass("S1007", "CS201", AFTER)["computed_result"] == "FAIL"


# PROVES: S1010 failed CS203 then passed it on re-registration, so CS203 is NOT a backlog; S1009 has 3 or more backlogs.
# WHY: only the latest attempt counts. Counting old FAIL rows would give a student backlogs they already cleared.
def test_reregistration_clears_backlog():
    assert "CS203" not in tools.get_backlogs("S1010")["uncleared_courses"]
    assert len(tools.get_backlogs("S1009")["uncleared_courses"]) >= 3


# PROVES: "my data structures attendance" finds exactly CS201 for a CSE student; "economics" matches two courses (HS201, HS202).
# WHY: students type course names, not codes. One match -> use it; two matches -> the system must ask which one (clarification_needed).
def test_course_lookup_by_name_and_ambiguity():
    assert [c["course_code"] for c in tools.find_course("my data structures attendance", "B.Tech CSE")] == ["CS201"]
    assert len(tools.find_course("economics", None)) == 2            # HS201 + HS202 -> clarification needed


# PROVES: asking about a course the student does not take (S1001, EC201) returns {"error": ...} instead of crashing.
# WHY: tools must fail politely, so the graph can answer "no record found" instead of a 500 error.
def test_unknown_record_returns_error_not_exception():
    assert "error" in tools.get_attendance("S1001", "EC201")
