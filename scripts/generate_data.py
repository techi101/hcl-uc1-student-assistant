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
import csv
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "students_csv"
PROMPT_FILE = ROOT / "prompts" / "generate_students.txt"
load_dotenv(ROOT / ".env")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
TEMPERATURE = 0.7
EXAM_SESSION = "2026-MAY"

COURSES = {  # course_code PK -> one programme (Annex C), NSUT-style semester-3 courses, 4 credits each
    "B.Tech CSE": [("CS201", "Data Structures"), ("CS203", "Discrete Mathematics"), ("MA201", "Mathematics-III"),
                   ("CS205", "Computer Organisation"), ("CS207", "Object Oriented Programming"), ("HS201", "Economics")],
    "B.Tech ECE": [("EC201", "Signals and Systems"), ("EC203", "Analog Electronics"), ("MA202", "Mathematics-III (ECE)"),
                   ("EC205", "Digital Electronics"), ("EC207", "Network Theory"), ("HS202", "Economics (ECE)")],
}
GROUPS = [("B.Tech CSE", 2023, 1001), ("B.Tech CSE", 2024, 1009), ("B.Tech ECE", 2023, 1017), ("B.Tech ECE", 2024, 1025)]
PER_GROUP = 8
SEMESTER = {2023: 7, 2024: 5}

PROMPT = """You generate SYNTHETIC student records for testing a university assistant. Names must be invented
(realistic Indian first + last names, no real public figures). Programme: {programme}. Admission batch: {batch}.
Create exactly {n} students. Courses (use exactly these codes, each exactly once per student): {courses}.
For each course give: classes_held (integer 36-48), classes_attended (integer, <= classes_held; most students
70-100% attendance, a few 55-75%), internal_marks (integer 0-50), external_marks (integer 0-50; most 18-45,
a few below 15). cgpa is a number 4.00-9.80 with 2 decimals, roughly consistent with the marks.
Reply ONLY with JSON: {{"students": [{{"full_name": "...", "cgpa": 7.12, "courses": [{{"course_code": "...",
"classes_held": 40, "classes_attended": 34, "internal_marks": 31, "external_marks": 28}}]}}]}}"""


class CourseRec(BaseModel):
    course_code: str
    classes_held: int = Field(ge=30, le=60)
    classes_attended: int = Field(ge=0)
    internal_marks: int = Field(ge=0, le=50)
    external_marks: int = Field(ge=0, le=50)

    @field_validator("classes_attended")
    @classmethod
    def attended_le_held(cls, v, info):
        if "classes_held" in info.data and v > info.data["classes_held"]:
            raise ValueError("attended > held")
        return v


class StudentRec(BaseModel):
    full_name: str = Field(min_length=3, max_length=60)
    cgpa: float = Field(ge=0, le=10)
    courses: list[CourseRec]


class Batch(BaseModel):
    students: list[StudentRec]


def rules() -> dict[str, float]:
    """Thresholds come from the rule registry CSV (the same numbers the tools use), never constants here.
    For generation we use the Regulations' rows (2019-07-01), i.e. the rules in force for the May-2026 exams."""
    rows = list(csv.DictReader(open(ROOT / "data" / "rules.csv", encoding="utf-8-sig")))
    pick = {}
    for r in rows:
        if r["source_doc_id"] == "NSUT-BTECH-REG-2019":
            pick[r["parameter"]] = float(r["value"])
    return pick


def ask_llm(programme: str, batch: int, calls: list) -> Batch:
    from groq import Groq
    codes = [c for c, _ in COURSES[programme]]
    prompt = PROMPT.format(programme=programme, batch=batch, n=PER_GROUP,
                           courses=", ".join(f"{c} {n}" for c, n in COURSES[programme]))
    client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60)
    last_err = None
    for attempt in range(1, 4):
        t0 = time.perf_counter()
        r = client.chat.completions.create(model=MODEL, temperature=TEMPERATURE, max_tokens=6000,
                                           response_format={"type": "json_object"},
                                           messages=[{"role": "user", "content": prompt}])
        calls.append({"programme": programme, "batch": batch, "attempt": attempt, "tokens": r.usage.total_tokens,
                      "seconds": round(time.perf_counter() - t0, 1)})
        try:
            b = Batch.model_validate_json(r.choices[0].message.content)
            if len(b.students) != PER_GROUP:
                raise ValueError(f"expected {PER_GROUP} students, got {len(b.students)}")
            for s in b.students:
                if sorted(c.course_code for c in s.courses) != sorted(codes):
                    raise ValueError(f"{s.full_name}: courses {[c.course_code for c in s.courses]} != {codes}")
            if len({s.full_name for s in b.students}) != PER_GROUP:
                raise ValueError("duplicate names")
            return b
        except (ValidationError, ValueError) as e:
            last_err = e
            calls[-1]["rejected"] = str(e)[:200]
            print(f"  rejected attempt {attempt} for {programme} {batch}: {str(e)[:120]}")
            time.sleep(2)
    raise SystemExit(f"LLM output failed validation 3 times for {programme} {batch}: {last_err}")


def derive_result(rec: dict, R: dict) -> str:
    pct_att = 100 * rec["classes_attended"] / rec["classes_held"]
    if pct_att < R["attendance_floor_pct"]:
        return "DETAINED"                                   # Regulations 11.6-11.7
    if rec["result"] == "ABSENT":
        return "ABSENT"
    ese_pct = 100 * rec["external_marks"] / 50              # ESE out of 50 (Regulations Table 1)
    return "PASS" if ese_pct >= R["min_ese_pct"] and rec["total_marks"] >= R["min_total_marks"] else "FAIL"


def main() -> None:
    R = rules()
    OUT.mkdir(parents=True, exist_ok=True)
    PROMPT_FILE.parent.mkdir(exist_ok=True)
    PROMPT_FILE.write_text(f"MODEL: {MODEL}\nTEMPERATURE: {TEMPERATURE}\nCALLS: one per programme x batch "
                           f"(4 groups), retried on validation failure\n\n--- PROMPT TEMPLATE (verbatim) ---\n{PROMPT}\n",
                           encoding="utf-8")
    calls: list = []
    students, attendance, results = [], [], []
    for programme, batch, start in GROUPS:
        print(f"LLM: {programme} {batch} ...")
        b = ask_llm(programme, batch, calls)
        for i, s in enumerate(b.students):
            sid = f"S{start + i}"
            students.append({"student_id": sid, "full_name": s.full_name, "programme": programme, "batch_year": batch,
                             "current_semester": SEMESTER[batch], "cgpa": round(s.cgpa, 2), "active_backlogs": 0})
            for c in s.courses:
                attendance.append({"student_id": sid, "course_code": c.course_code, "classes_held": c.classes_held,
                                   "classes_attended": c.classes_attended})
                results.append({"student_id": sid, "course_code": c.course_code, "exam_session": EXAM_SESSION,
                                "exam_type": "REGULAR", "internal_marks": c.internal_marks,
                                "external_marks": c.external_marks, "total_marks": None, "max_marks": 100, "result": None})

    att = {(a["student_id"], a["course_code"]): a for a in attendance}
    res = {(r["student_id"], r["course_code"]): r for r in results}
    stu = {s["student_id"]: s for s in students}

    def set_att(sid, code, held, attended):
        att[(sid, code)].update(classes_held=held, classes_attended=attended)

    def set_marks(sid, code, internal, external, result=None):
        res[(sid, code)].update(internal_marks=internal, external_marks=external)
        if result:
            res[(sid, code)]["result"] = result

    # ---- deliberate edge cases (HCL 4.2), planted by CODE on fixed IDs ----
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
    for (sid, code), a in att.items():
        if sid in edge or code not in ("CS201", "EC201"):
            continue
        pct = 100 * a["classes_attended"] / a["classes_held"]
        if 60 <= pct < 85:
            a["classes_attended"] = min(a["classes_held"], round(0.9 * a["classes_held"]))

    for key, r in res.items():
        r["total_marks"] = r["internal_marks"] + r["external_marks"]
        r["result"] = derive_result({**att[key], **r}, R)
        if r["result"] == "DETAINED":
            r["external_marks"], r["total_marks"] = 0, r["internal_marks"]          # not allowed to sit the ESE
    results = list(res.values())
    results.append({"student_id": "S1010", "course_code": "CS203", "exam_session": "2026-JUL", "exam_type": "REGULAR",
                    "internal_marks": 30, "external_marks": 27, "total_marks": 57, "max_marks": 100, "result": "PASS"})
    latest: dict = {}
    from app.tools import session_key                             # NOT plain string order: '2026-JUL' < '2026-MAY'
    for r in sorted(results, key=lambda r: session_key(r["exam_session"])):
        latest[(r["student_id"], r["course_code"])] = r["result"]
    for s in students:
        s["active_backlogs"] = sum(1 for (sid, _), v in latest.items() if sid == s["student_id"] and v != "PASS")

    courses = [{"course_code": c, "course_name": n, "programme": p, "semester": 3, "credits": 4}
               for p, lst in COURSES.items() for c, n in lst]
    for name, rows in [("students", students), ("courses", courses), ("attendance", list(att.values())),
                       ("results", results)]:
        with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    (OUT / "edge_cases.json").write_text(json.dumps(edge, indent=2), encoding="utf-8")
    (OUT / "generation_log.json").write_text(json.dumps({"model": MODEL, "temperature": TEMPERATURE, "calls": calls,
                                                         "students": len(students)}, indent=2), encoding="utf-8")
    print(f"wrote {len(students)} students, {len(courses)} courses, {len(att)} attendance rows, {len(results)} results "
          f"-> {OUT}  ({len(calls)} LLM calls, {sum(c.get('tokens', 0) for c in calls)} tokens)")


if __name__ == "__main__":
    main()
