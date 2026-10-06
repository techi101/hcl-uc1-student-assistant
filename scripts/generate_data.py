"""Synthetic student data WITH an LLM, in the fixed Annex C schema (HCL 4.2). Owner: Suryansh (part B).

How AI is used, and how it is kept honest:
  1. PROMPT (saved verbatim in prompts/generate_students.txt): the LLM writes names + realistic attendance/marks
     for one programme x batch at a time, as strict JSON.
  2. SCHEMA ENFORCEMENT: every response is parsed with Pydantic (ranges, every course exactly once, attended <= held);
     invalid -> retry (max 3), then fail loudly. Nothing the LLM says is trusted without validation.
  3. CODE DERIVES everything rule-based: total = internal + external; result PASS/FAIL/DETAINED from data/rules.csv
     (min_ese_pct, min_total_marks, attendance_floor_pct); active_backlogs from the results. The LLM never decides these.
  4. EDGE CASES are planted deliberately by code on fixed student IDs (listed in data/students_csv/edge_cases.json).
Run: python -m scripts.generate_data      -> data/students_csv/{students,courses,attendance,results}.csv
"""
# WHAT THIS FILE IS: makes FAKE (synthetic) student data for testing, with an LLM's help.
# Split of work: LLM generates names/marks; code decides IDs, totals, PASS/FAIL, backlogs and plants edge cases.
# Flow: prompt -> LLM JSON -> Pydantic check (retry if bad) -> code adds IDs/totals/results -> edge cases -> 4 CSVs
import csv
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

# Settings: where files go, which LLM model (from .env), how creative it may be (0.7), and the exam session label
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "students_csv"
PROMPT_FILE = ROOT / "prompts" / "generate_students.txt"
load_dotenv(ROOT / ".env")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
TEMPERATURE = 0.7
EXAM_SESSION = "2026-MAY"

# The 6 courses per programme (fixed by us, not by the LLM), so course codes are always valid
COURSES = {  # course_code PK -> one programme (Annex C), NSUT-style semester-3 courses, 4 credits each
    "B.Tech CSE": [("CS201", "Data Structures"), ("CS203", "Discrete Mathematics"), ("MA201", "Mathematics-III"),
                   ("CS205", "Computer Organisation"), ("CS207", "Object Oriented Programming"), ("HS201", "Economics")],
    "B.Tech ECE": [("EC201", "Signals and Systems"), ("EC203", "Analog Electronics"), ("MA202", "Mathematics-III (ECE)"),
                   ("EC205", "Digital Electronics"), ("EC207", "Network Theory"), ("HS202", "Economics (ECE)")],
}
# 4 groups (programme, batch, first ID number) x 8 students = 32 students.
# CODE decides the IDs: CSE 2023 gets S1001-S1008, CSE 2024 gets S1009-S1016, and so on.
GROUPS = [("B.Tech CSE", 2023, 1001), ("B.Tech CSE", 2024, 1009), ("B.Tech ECE", 2023, 1017), ("B.Tech ECE", 2024, 1025)]
PER_GROUP = 8
# current semester depends on the batch year (2023 batch is in semester 7, 2024 batch in semester 5)
SEMESTER = {2023: 7, 2024: 5}

# The prompt sent to the LLM. {programme}, {batch}, {n}, {courses} get filled in for each group.
# {{ and }} are written double so they come out as real { } in the JSON example.
PROMPT = """You generate SYNTHETIC student records for testing a university assistant. Names must be invented
(realistic Indian first + last names, no real public figures). Programme: {programme}. Admission batch: {batch}.
Create exactly {n} students. Courses (use exactly these codes, each exactly once per student): {courses}.
For each course give: classes_held (integer 36-48), classes_attended (integer, <= classes_held; most students
70-100% attendance, a few 55-75%), internal_marks (integer 0-50), external_marks (integer 0-50; most 18-45,
a few below 15). cgpa is a number 4.00-9.80 with 2 decimals, roughly consistent with the marks.
Reply ONLY with JSON: {{"students": [{{"full_name": "...", "cgpa": 7.12, "courses": [{{"course_code": "...",
"classes_held": 40, "classes_attended": 34, "internal_marks": 31, "external_marks": 28}}]}}]}}"""


# Pydantic validates the LLM output. These 3 classes describe the exact JSON shape we expect back.
# One course for one student: held 30-60, marks 0-50 each. Anything outside -> rejected.
class CourseRec(BaseModel):
    course_code: str
    classes_held: int = Field(ge=30, le=60)
    classes_attended: int = Field(ge=0)
    internal_marks: int = Field(ge=0, le=50)
    external_marks: int = Field(ge=0, le=50)

    # extra check: you can't attend more classes than were held (e.g. 42 of 40 -> rejected)
    @field_validator("classes_attended")
    @classmethod
    def attended_le_held(cls, v, info):
        if "classes_held" in info.data and v > info.data["classes_held"]:
            raise ValueError("attended > held")
        return v


# One student: a name (3-60 letters), CGPA 0-10, and a list of courses
class StudentRec(BaseModel):
    full_name: str = Field(min_length=3, max_length=60)
    cgpa: float = Field(ge=0, le=10)
    courses: list[CourseRec]


# The whole LLM reply: {"students": [...]}
class Batch(BaseModel):
    students: list[StudentRec]


# IN: nothing  ->  OUT: {rule name: number} from data/rules.csv, e.g. min_ese_pct 30, min_total_marks 35, floor 60
def rules() -> dict[str, float]:
    """Thresholds come from the rule registry CSV (the same numbers the tools use), never constants here.
    For generation we use the Regulations' rows (2019-07-01), i.e. the rules in force for the May-2026 exams."""
    rows = list(csv.DictReader(open(ROOT / "data" / "rules.csv", encoding="utf-8-sig")))
    pick = {}
    # keep only rows from the Regulations document (NSUT-BTECH-REG-2019), not the later circular or FAQ
    for r in rows:
        if r["source_doc_id"] == "NSUT-BTECH-REG-2019":
            pick[r["parameter"]] = float(r["value"])
    return pick


# IN: programme + batch + a log list  ->  OUT: 8 validated students (a Batch). Logs tokens/time of every call.
# Flow: fill prompt -> call LLM (Groq) -> Pydantic check + our extra checks -> good? return : retry (max 3 tries)
def ask_llm(programme: str, batch: int, calls: list) -> Batch:
    from groq import Groq
    # the course codes we expect, and the prompt filled in for this group (e.g. "CS201 Data Structures, ...")
    codes = [c for c, _ in COURSES[programme]]
    prompt = PROMPT.format(programme=programme, batch=batch, n=PER_GROUP,
                           courses=", ".join(f"{c} {n}" for c, n in COURSES[programme]))
    client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60)
    last_err = None
    # up to 3 tries
    for attempt in range(1, 4):
        # call the LLM and ask for a JSON reply only; time it
        t0 = time.perf_counter()
        r = client.chat.completions.create(model=MODEL, temperature=TEMPERATURE, max_tokens=6000,
                                           response_format={"type": "json_object"},
                                           messages=[{"role": "user", "content": prompt}])
        # write down this call (which group, which try, tokens used, seconds taken) for generation_log.json
        calls.append({"programme": programme, "batch": batch, "attempt": attempt, "tokens": r.usage.total_tokens,
                      "seconds": round(time.perf_counter() - t0, 1)})
        try:
            # Pydantic validates the LLM output: wrong shape or out-of-range numbers -> error
            b = Batch.model_validate_json(r.choices[0].message.content)
            # our extra checks: exactly 8 students
            if len(b.students) != PER_GROUP:
                raise ValueError(f"expected {PER_GROUP} students, got {len(b.students)}")
            # ...each student has exactly our 6 course codes, each once (compare sorted lists)
            for s in b.students:
                if sorted(c.course_code for c in s.courses) != sorted(codes):
                    raise ValueError(f"{s.full_name}: courses {[c.course_code for c in s.courses]} != {codes}")
            # ...and no two students share a name
            if len({s.full_name for s in b.students}) != PER_GROUP:
                raise ValueError("duplicate names")
            return b
        # any check failed: note why, print it, wait 2 seconds, try again
        except (ValidationError, ValueError) as e:
            last_err = e
            calls[-1]["rejected"] = str(e)[:200]
            print(f"  rejected attempt {attempt} for {programme} {batch}: {str(e)[:120]}")
            time.sleep(2)
    # 3 bad replies in a row -> stop the whole script loudly (never save unchecked data)
    raise SystemExit(f"LLM output failed validation 3 times for {programme} {batch}: {last_err}")


# IN: one course record (attendance + marks) + the rules  ->  OUT: "DETAINED", "ABSENT", "PASS" or "FAIL"
# CODE decides PASS/FAIL, never the LLM. Order: attendance floor first, then absent, then the 2 pass rules.
def derive_result(rec: dict, R: dict) -> str:
    # attendance below the 60% floor (ATT-FLOOR-01, 11.6) -> DETAINED (not allowed to sit the exam)
    pct_att = 100 * rec["classes_attended"] / rec["classes_held"]
    if pct_att < R["attendance_floor_pct"]:
        return "DETAINED"                                   # Regulations 11.6-11.7
    if rec["result"] == "ABSENT":
        return "ABSENT"
    # pass rule: ESE >= 30% (12.7) AND total >= 35 (Table 5). Example: S1006 ESE 14/50 = 28% -> FAIL
    ese_pct = 100 * rec["external_marks"] / 50              # ESE out of 50 (Regulations Table 1)
    return "PASS" if ese_pct >= R["min_ese_pct"] and rec["total_marks"] >= R["min_total_marks"] else "FAIL"


# IN: nothing  ->  OUT: writes students/courses/attendance/results CSVs + edge_cases.json + generation_log.json
def main() -> None:
    # load the rules, make sure output folders exist, and save the exact prompt used (for honesty / judges)
    R = rules()
    OUT.mkdir(parents=True, exist_ok=True)
    PROMPT_FILE.parent.mkdir(exist_ok=True)
    PROMPT_FILE.write_text(f"MODEL: {MODEL}\nTEMPERATURE: {TEMPERATURE}\nCALLS: one per programme x batch "
                           f"(4 groups), retried on validation failure\n\n--- PROMPT TEMPLATE (verbatim) ---\n{PROMPT}\n",
                           encoding="utf-8")
    calls: list = []
    students, attendance, results = [], [], []
    # for each of the 4 groups: ask the LLM for 8 students, then CODE gives each one an ID (S1001, S1002, ...)
    for programme, batch, start in GROUPS:
        print(f"LLM: {programme} {batch} ...")
        b = ask_llm(programme, batch, calls)
        for i, s in enumerate(b.students):
            sid = f"S{start + i}"
            # student row: name + CGPA from the LLM; ID, programme, batch, semester from code; backlogs filled in later
            students.append({"student_id": sid, "full_name": s.full_name, "programme": programme, "batch_year": batch,
                             "current_semester": SEMESTER[batch], "cgpa": round(s.cgpa, 2), "active_backlogs": 0})
            # one attendance row and one result row per course. total and result are left empty (None) on purpose:
            # code fills them in below, the LLM never decides them
            for c in s.courses:
                attendance.append({"student_id": sid, "course_code": c.course_code, "classes_held": c.classes_held,
                                   "classes_attended": c.classes_attended})
                results.append({"student_id": sid, "course_code": c.course_code, "exam_session": EXAM_SESSION,
                                "exam_type": "REGULAR", "internal_marks": c.internal_marks,
                                "external_marks": c.external_marks, "total_marks": None, "max_marks": 100, "result": None})

    # quick lookups by key, e.g. att[("S1002", "CS201")] -> that attendance row (so we can edit rows in place)
    att = {(a["student_id"], a["course_code"]): a for a in attendance}
    res = {(r["student_id"], r["course_code"]): r for r in results}
    stu = {s["student_id"]: s for s in students}

    # helper: overwrite held/attended for one student + course
    def set_att(sid, code, held, attended):
        att[(sid, code)].update(classes_held=held, classes_attended=attended)

    # helper: overwrite internal/external marks (and optionally force a result like "ABSENT")
    def set_marks(sid, code, internal, external, result=None):
        res[(sid, code)].update(internal_marks=internal, external_marks=external)
        if result:
            res[(sid, code)]["result"] = result

    # ---- deliberate edge cases (HCL 4.2), planted by CODE on fixed IDs ----
    # Each entry: which student is the tricky case, and why. Saved to edge_cases.json so tests and judges can see them.
    edge = {
        "S1001": "CS201 attendance exactly 80.0% (32/40) = AT the threshold in force from 2026-08-01 (circular)",
        "S1002": "CS201 attendance 77.5% (31/40) = one class below 80% (also HCL's 6.1 example numbers)",
        "S1003": "CS201 attendance exactly 75.0% (30/40) = AT Regulations 11.2 threshold (ask with as_of_date 2026-07-15)",
        "S1004": "CS201 attendance 72.5% (29/40) = one class below 75%",
        "S1005": "CS201 attendance 55% (22/40) = below the 60% floor -> DETAINED",
        "S1006": "CS201 ESE 14/50 = 28% (< 30%, clause 12.7) with internal 30 -> FAIL although total 44",
        "S1007": "CS201 total 34 (internal 15 + external 19) = one below 35 -> FAIL although ESE 38%",
        "S1008": "MA201 ABSENT in the end-semester exam",
        "S1009": "multiple backlogs: FAIL in CS201, CS203, MA201 -> active_backlogs 3",
        "S1010": "re-registration: CS203 FAIL in 2026-MAY, then REGULAR re-attempt 2026-JUL (summer, 12.5) PASS "
                 "(NSUT has no supplementary exams, 12.3)",
        "S1011": "CGPA exactly 5.00 = minimum for the degree (15.1)",
        "S1012": "CGPA exactly 8.50 = honours CGPA (7.9)",
        "S1017": "EC201 attendance exactly 80.0% (32/40) (ECE: the CSE FAQ's 65% must NOT apply)",
    }
    # now actually write those numbers into the data (overwriting what the LLM gave for these few rows)
    set_att("S1001", "CS201", 40, 32)
    set_att("S1002", "CS201", 40, 31)
    set_att("S1003", "CS201", 40, 30)
    set_att("S1004", "CS201", 40, 29)
    set_att("S1005", "CS201", 40, 22)
    set_marks("S1006", "CS201", 30, 14)
    set_marks("S1007", "CS201", 15, 19)
    set_marks("S1008", "MA201", res[("S1008", "MA201")]["internal_marks"], 0, result="ABSENT")
    for code in ("CS201", "CS203", "MA201"):
        set_marks("S1009", code, 12, 10)
    set_marks("S1010", "CS203", 14, 12)
    stu["S1011"]["cgpa"] = 5.00
    stu["S1012"]["cgpa"] = 8.50
    set_att("S1017", "EC201", 40, 32)
    # keep the other students away from the planted boundaries so tests stay unambiguous
    # (any other student with CS201/EC201 attendance between 60% and 85% is moved up to about 90%)
    for (sid, code), a in att.items():
        if sid in edge or code not in ("CS201", "EC201"):
            continue
        pct = 100 * a["classes_attended"] / a["classes_held"]
        if 60 <= pct < 85:
            a["classes_attended"] = min(a["classes_held"], round(0.9 * a["classes_held"]))

    # CODE works out every total (internal + external) and every result using the rules
    for key, r in res.items():
        r["total_marks"] = r["internal_marks"] + r["external_marks"]
        r["result"] = derive_result({**att[key], **r}, R)
        # a detained student did not sit the end-semester exam, so external marks become 0
        if r["result"] == "DETAINED":
            r["external_marks"], r["total_marks"] = 0, r["internal_marks"]          # not allowed to sit the ESE
    # add S1010's second attempt: CS203 re-taken in 2026-JUL and passed
    results = list(res.values())
    results.append({"student_id": "S1010", "course_code": "CS203", "exam_session": "2026-JUL", "exam_type": "REGULAR",
                    "internal_marks": 30, "external_marks": 27, "total_marks": 57, "max_marks": 100, "result": "PASS"})
    # CODE counts backlogs: sort results by (year, month), keep the latest result per course, count non-PASS ones.
    # Sorted as (year, month) because text sort put 2026-JUL before 2026-MAY (a bug a test caught).
    latest: dict = {}
    from app.tools import session_key                             # NOT plain string order: '2026-JUL' < '2026-MAY'
    for r in sorted(results, key=lambda r: session_key(r["exam_session"])):
        latest[(r["student_id"], r["course_code"])] = r["result"]
    for s in students:
        s["active_backlogs"] = sum(1 for (sid, _), v in latest.items() if sid == s["student_id"] and v != "PASS")

    # the course list comes from our fixed COURSES table (semester 3, 4 credits each)
    courses = [{"course_code": c, "course_name": n, "programme": p, "semester": 3, "credits": 4}
               for p, lst in COURSES.items() for c, n in lst]
    # write the 4 CSV files; column names come from the keys of the first row
    for name, rows in [("students", students), ("courses", courses), ("attendance", list(att.values())),
                       ("results", results)]:
        with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    # also save the edge-case list and a log of every LLM call (model, tokens, time, rejections)
    (OUT / "edge_cases.json").write_text(json.dumps(edge, indent=2), encoding="utf-8")
    (OUT / "generation_log.json").write_text(json.dumps({"model": MODEL, "temperature": TEMPERATURE, "calls": calls,
                                                         "students": len(students)}, indent=2), encoding="utf-8")
    print(f"wrote {len(students)} students, {len(courses)} courses, {len(att)} attendance rows, {len(results)} results "
          f"-> {OUT}  ({len(calls)} LLM calls, {sum(c.get('tokens', 0) for c in calls)} tokens)")


# run main() only when this file is started directly, not when imported
if __name__ == "__main__":
    main()
