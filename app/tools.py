"""Deterministic tools over SQLite. Thresholds ONLY from rule_registry. Owner: B. Shapes: CONTRACT.md."""
from app.db import connect


def get_student(student_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
    return dict(row) if row else None


def get_attendance(student_id: str, course_code: str) -> dict | None:
    raise NotImplementedError("B: build me")


def get_rule(parameter: str, as_of_date: str, programme: str, batch_year: int) -> dict | None:
    raise NotImplementedError("B: build me")


def check_exam_eligibility(student_id: str, course_code: str, as_of_date: str) -> dict:
    raise NotImplementedError("B: build me")
