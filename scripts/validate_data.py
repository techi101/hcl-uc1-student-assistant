"""Validate student CSVs (Annex C schema + logical constraints). Owner: Suryansh (part B).
Run: python -m scripts.validate_data --dir data/students_csv      (exit code 1 if any violation)
Checks: required columns; ID format S####; reserved IDs (S9000-S9999) / JDG course codes; ranges (semester 1-10,
cgpa 0-10, backlogs >= 0, held > 0, 0 <= attended <= held, marks within range); total = internal + external;
result consistent with marks + rules (rules read from data/rules.csv); referential integrity; duplicates."""
# WHAT THIS FILE IS: a "checker" for the 4 student CSV files, run BEFORE loading them into the database.
# Flow: read 4 CSVs -> check columns -> check each row (IDs, ranges, totals, PASS/FAIL vs rules) -> list of problems
# It only reports problems; it never fixes or changes the data.
import argparse
import csv
import re
import sys
from pathlib import Path

# The fixed Annex C schema: for each CSV file, the columns that MUST be there
REQUIRED = {
    "students": ["student_id", "full_name", "programme", "batch_year", "current_semester", "cgpa", "active_backlogs"],
    "courses": ["course_code", "course_name", "programme", "semester", "credits"],
    "attendance": ["student_id", "course_code", "classes_held", "classes_attended"],
    "results": ["student_id", "course_code", "exam_session", "exam_type", "internal_marks", "external_marks",
                "total_marks", "max_marks", "result"],
}


# IN: folder + file name (e.g. "students")  ->  OUT: list of rows (each row a dict), or [] if the file is missing
# "utf-8-sig" quietly removes the invisible BOM mark that Excel adds at the start of CSV files
def read(d: Path, name: str) -> list[dict]:
    p = d / f"{name}.csv"
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if p.exists() else []


# IN: any value ("40", "40.0", "abc", None)  ->  OUT: a whole number (40), or None if it is not a number
def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# IN: nothing  ->  OUT: {rule name: number}, e.g. {"min_ese_pct": 30, "min_total_marks": 35, ...}
# WHY: pass marks come from data/rules.csv (the same numbers the app uses), never typed into code.
# Only the Regulations' rows (NSUT-BTECH-REG-2019) are used, because those were in force for the May-2026 exams.
def regulation_rules() -> dict[str, float]:
    p = Path(__file__).resolve().parent.parent / "data" / "rules.csv"
    return {r["parameter"]: float(r["value"]) for r in csv.DictReader(open(p, encoding="utf-8-sig"))
            if r["source_doc_id"] == "NSUT-BTECH-REG-2019"}


# IN: folder with the CSVs  ->  OUT: list of problem messages (empty list = data is clean)
def validate(d: Path) -> list[str]:
    # v collects every problem found; data holds all 4 files
    v: list[str] = []
    data = {n: read(d, n) for n in REQUIRED}
    # Check 1: every file has all its required columns (looks at the first row's column names)
    for name, cols in REQUIRED.items():
        if data[name]:
            missing = [c for c in cols if c not in data[name][0]]
            if missing:
                v.append(f"{name}.csv: missing required columns {missing}")
    # sets of known student ids, course codes and programmes, used later to catch rows pointing at nothing
    sids = {s["student_id"] for s in data["students"]}
    codes = {c["course_code"] for c in data["courses"]}
    progs = {s["programme"] for s in data["students"]}
    seen = set()
    # Check 2: each student row. i starts at 2 because row 1 of the CSV is the header (so i = real line number)
    for i, s in enumerate(data["students"], 2):
        sid = s.get("student_id", "")
        # regex in words: "S followed by exactly 4 digits, nothing else" (S1002 ok, S12 or X1002 bad)
        if not re.fullmatch(r"S\d{4}", sid):
            v.append(f"students row {i}: bad student_id {sid!r}")
        # same id twice = duplicate
        if sid in seen:
            v.append(f"students row {i}: DUPLICATE student_id {sid}")
        seen.add(sid)
        # regex in words: "S9 then 3 digits" = S9000-S9999, reserved for judges (allowed only in the judges' test folder)
        if re.fullmatch(r"S9\d{3}", sid) and d.name != "test_students":
            v.append(f"students row {i}: {sid} is reserved for judges (S9000-S9999)")
        # range checks: semester 1-10, CGPA 0-10, backlogs not negative
        sem, cg, bl = to_int(s.get("current_semester")), s.get("cgpa"), to_int(s.get("active_backlogs"))
        if sem is None or not 1 <= sem <= 10:
            v.append(f"students row {i}: current_semester {s.get('current_semester')!r} not in 1-10")
        # CGPA: not a number, or outside 0-10 -> both end up in the same "not in 0-10" message
        try:
            if not 0 <= float(cg) <= 10:
                raise ValueError
        except (TypeError, ValueError):
            v.append(f"students row {i}: cgpa {cg!r} not in 0-10")
        if bl is None or bl < 0:
            v.append(f"students row {i}: active_backlogs {s.get('active_backlogs')!r} < 0")
    # Check 3: each course row. JDG* codes are reserved for judges; programme must belong to some student
    for i, c in enumerate(data["courses"], 2):
        if c["course_code"].upper().startswith("JDG") and d.name != "test_students":
            v.append(f"courses row {i}: JDG* course codes are reserved for judges")
        if c["programme"] not in progs:
            v.append(f"courses row {i}: programme {c['programme']!r} matches no student programme")
    # Check 4: each attendance row. Student and course must exist; held > 0; attended between 0 and held
    # (e.g. 31 attended of 40 held is fine; 42 of 40 is impossible)
    for i, a in enumerate(data["attendance"], 2):
        held, att = to_int(a.get("classes_held")), to_int(a.get("classes_attended"))
        if a["student_id"] not in sids or a["course_code"] not in codes:
            v.append(f"attendance row {i}: unknown student/course {a['student_id']}/{a['course_code']}")
        if held is None or held <= 0:
            v.append(f"attendance row {i}: classes_held {a.get('classes_held')!r} must be > 0")
        elif att is None or not 0 <= att <= held:
            v.append(f"attendance row {i}: classes_attended {a.get('classes_attended')!r} not in 0..{held}")
    # Check 5: each result row. Load the pass rules once from rules.csv first.
    R = regulation_rules()
    for i, r in enumerate(data["results"], 2):
        # student and course must exist
        if r["student_id"] not in sids or r["course_code"] not in codes:
            v.append(f"results row {i}: unknown student/course {r['student_id']}/{r['course_code']}")
        # turn the 4 marks columns into whole numbers (None if not a number)
        it, ex, tot, mx = (to_int(r.get(k)) for k in ("internal_marks", "external_marks", "total_marks", "max_marks"))
        # only allowed words in exam_type and result
        if r.get("exam_type") not in ("REGULAR", "SUPPLEMENTARY"):
            v.append(f"results row {i}: exam_type {r.get('exam_type')!r}")
        if r.get("result") not in ("PASS", "FAIL", "ABSENT", "DETAINED"):
            v.append(f"results row {i}: result {r.get('result')!r}")
        # if any mark is not a number, report it and skip the maths checks for this row
        if None in (it, ex, tot, mx):
            v.append(f"results row {i}: non-integer marks")
            continue
        # every mark must be between 0 and max marks
        if not (0 <= it <= mx and 0 <= ex <= mx and 0 <= tot <= mx):
            v.append(f"results row {i}: marks out of range 0..{mx}")
        # total must equal internal + external (e.g. 30 + 14 = 44)
        if tot != it + ex:
            v.append(f"results row {i}: total_marks {tot} != internal {it} + external {ex}")
        # PASS/FAIL written in the file must match the rules: ESE >= 30% (12.7) AND total >= 35 (Table 5).
        # ESE is out of half the max marks (50 of 100). Example: S1006 ESE 14/50 = 28% -> must be FAIL.
        if r.get("result") in ("PASS", "FAIL") and R:
            passed = 100 * ex / (mx / 2) >= R["min_ese_pct"] and tot >= R["min_total_marks"]
            if passed != (r["result"] == "PASS"):
                v.append(f"results row {i}: result {r['result']} inconsistent with marks (ESE {ex}/{mx // 2}, total {tot})")
    return v


# IN: command line "--dir <folder>"  ->  OUT: prints a report; exit code 0 = clean, 1 = problems found
# Flow: read folder name -> count rows per file -> validate -> print -> (for our own data) save validation_report.txt
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/students_csv")
    a = ap.parse_args()
    d = Path(a.dir)
    counts = {n: len(read(d, n)) for n in REQUIRED}
    v = validate(d)
    # the report: one summary line, the number of problems, then one line per problem
    lines = [f"Validation of {d}: " + ", ".join(f"{n}={c}" for n, c in counts.items()),
             f"violations: {len(v)}"] + [f"  - {x}" for x in v]
    print("\n".join(lines))
    # save the report to a file only when checking our own data/students_csv folder (not the judges' folder)
    if d.resolve() == (Path(__file__).resolve().parent.parent / "data" / "students_csv").resolve():
        (d.parent / "validation_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if v else 0


# run main() only when this file is started directly (python -m scripts.validate_data), not when imported
if __name__ == "__main__":
    sys.exit(main())
