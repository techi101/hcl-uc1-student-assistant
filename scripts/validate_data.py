"""Validate student CSVs (Annex C schema + logical constraints). Owner: Suryansh (part B).
Run: python -m scripts.validate_data --dir data/students_csv      (exit code 1 if any violation)
Checks: required columns; ID format S####; reserved IDs (S9000-S9999) / JDG course codes; ranges (semester 1-10,
cgpa 0-10, backlogs >= 0, held > 0, 0 <= attended <= held, marks within range); total = internal + external;
result consistent with marks + rules (rules read from data/rules.csv); referential integrity; duplicates."""
import argparse
import csv
import re
import sys
from pathlib import Path

REQUIRED = {
    "students": ["student_id", "full_name", "programme", "batch_year", "current_semester", "cgpa", "active_backlogs"],
    "courses": ["course_code", "course_name", "programme", "semester", "credits"],
    "attendance": ["student_id", "course_code", "classes_held", "classes_attended"],
    "results": ["student_id", "course_code", "exam_session", "exam_type", "internal_marks", "external_marks",
                "total_marks", "max_marks", "result"],
}


def read(d: Path, name: str) -> list[dict]:
    p = d / f"{name}.csv"
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if p.exists() else []


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def regulation_rules() -> dict[str, float]:
    p = Path(__file__).resolve().parent.parent / "data" / "rules.csv"
    return {r["parameter"]: float(r["value"]) for r in csv.DictReader(open(p, encoding="utf-8-sig"))
            if r["source_doc_id"] == "NSUT-BTECH-REG-2019"}


def validate(d: Path) -> list[str]:
    v: list[str] = []
    data = {n: read(d, n) for n in REQUIRED}
    for name, cols in REQUIRED.items():
        if data[name]:
            missing = [c for c in cols if c not in data[name][0]]
            if missing:
                v.append(f"{name}.csv: missing required columns {missing}")
    sids = {s["student_id"] for s in data["students"]}
    codes = {c["course_code"] for c in data["courses"]}
    progs = {s["programme"] for s in data["students"]}
    seen = set()
    for i, s in enumerate(data["students"], 2):
        sid = s.get("student_id", "")
        if not re.fullmatch(r"S\d{4}", sid):
            v.append(f"students row {i}: bad student_id {sid!r}")
        if sid in seen:
            v.append(f"students row {i}: DUPLICATE student_id {sid}")
        seen.add(sid)
        if re.fullmatch(r"S9\d{3}", sid) and d.name != "test_students":
            v.append(f"students row {i}: {sid} is reserved for judges (S9000-S9999)")
        sem, cg, bl = to_int(s.get("current_semester")), s.get("cgpa"), to_int(s.get("active_backlogs"))
        if sem is None or not 1 <= sem <= 10:
            v.append(f"students row {i}: current_semester {s.get('current_semester')!r} not in 1-10")
        try:
            if not 0 <= float(cg) <= 10:
                raise ValueError
        except (TypeError, ValueError):
            v.append(f"students row {i}: cgpa {cg!r} not in 0-10")
        if bl is None or bl < 0:
            v.append(f"students row {i}: active_backlogs {s.get('active_backlogs')!r} < 0")
    for i, c in enumerate(data["courses"], 2):
        if c["course_code"].upper().startswith("JDG") and d.name != "test_students":
            v.append(f"courses row {i}: JDG* course codes are reserved for judges")
        if c["programme"] not in progs:
            v.append(f"courses row {i}: programme {c['programme']!r} matches no student programme")
    for i, a in enumerate(data["attendance"], 2):
        held, att = to_int(a.get("classes_held")), to_int(a.get("classes_attended"))
        if a["student_id"] not in sids or a["course_code"] not in codes:
            v.append(f"attendance row {i}: unknown student/course {a['student_id']}/{a['course_code']}")
        if held is None or held <= 0:
            v.append(f"attendance row {i}: classes_held {a.get('classes_held')!r} must be > 0")
        elif att is None or not 0 <= att <= held:
            v.append(f"attendance row {i}: classes_attended {a.get('classes_attended')!r} not in 0..{held}")
    R = regulation_rules()
    for i, r in enumerate(data["results"], 2):
        if r["student_id"] not in sids or r["course_code"] not in codes:
            v.append(f"results row {i}: unknown student/course {r['student_id']}/{r['course_code']}")
        it, ex, tot, mx = (to_int(r.get(k)) for k in ("internal_marks", "external_marks", "total_marks", "max_marks"))
        if r.get("exam_type") not in ("REGULAR", "SUPPLEMENTARY"):
            v.append(f"results row {i}: exam_type {r.get('exam_type')!r}")
        if r.get("result") not in ("PASS", "FAIL", "ABSENT", "DETAINED"):
            v.append(f"results row {i}: result {r.get('result')!r}")
        if None in (it, ex, tot, mx):
            v.append(f"results row {i}: non-integer marks")
            continue
        if not (0 <= it <= mx and 0 <= ex <= mx and 0 <= tot <= mx):
            v.append(f"results row {i}: marks out of range 0..{mx}")
        if tot != it + ex:
            v.append(f"results row {i}: total_marks {tot} != internal {it} + external {ex}")
        if r.get("result") in ("PASS", "FAIL") and R:
            passed = 100 * ex / (mx / 2) >= R["min_ese_pct"] and tot >= R["min_total_marks"]
            if passed != (r["result"] == "PASS"):
                v.append(f"results row {i}: result {r['result']} inconsistent with marks (ESE {ex}/{mx // 2}, total {tot})")
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/students_csv")
    a = ap.parse_args()
    d = Path(a.dir)
    counts = {n: len(read(d, n)) for n in REQUIRED}
    v = validate(d)
    lines = [f"Validation of {d}: " + ", ".join(f"{n}={c}" for n, c in counts.items()),
             f"violations: {len(v)}"] + [f"  - {x}" for x in v]
    print("\n".join(lines))
    if d.resolve() == (Path(__file__).resolve().parent.parent / "data" / "students_csv").resolve():
        (d.parent / "validation_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if v else 0


if __name__ == "__main__":
    sys.exit(main())
