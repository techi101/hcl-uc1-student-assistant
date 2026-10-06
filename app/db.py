"""SQLite: Annex C tables exactly as HCL fixed them (+ audit_log). Owner: B."""
import sqlite3

from app.config import SQLITE_PATH, STORAGE

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
  student_id TEXT PRIMARY KEY CHECK (student_id GLOB 'S[0-9][0-9][0-9][0-9]'),
  full_name TEXT NOT NULL,
  programme TEXT NOT NULL,
  batch_year INTEGER NOT NULL,
  current_semester INTEGER NOT NULL CHECK (current_semester BETWEEN 1 AND 10),
  cgpa REAL NOT NULL CHECK (cgpa BETWEEN 0 AND 10),
  active_backlogs INTEGER NOT NULL CHECK (active_backlogs >= 0)
);
CREATE TABLE IF NOT EXISTS courses (
  course_code TEXT PRIMARY KEY,
  course_name TEXT NOT NULL,
  programme TEXT NOT NULL,
  semester INTEGER,
  credits INTEGER
);
CREATE TABLE IF NOT EXISTS attendance (
  student_id TEXT NOT NULL REFERENCES students(student_id),
  course_code TEXT NOT NULL REFERENCES courses(course_code),
  classes_held INTEGER NOT NULL CHECK (classes_held > 0),
  classes_attended INTEGER NOT NULL CHECK (classes_attended >= 0 AND classes_attended <= classes_held),
  PRIMARY KEY (student_id, course_code)
);
CREATE TABLE IF NOT EXISTS results (
  student_id TEXT NOT NULL REFERENCES students(student_id),
  course_code TEXT NOT NULL REFERENCES courses(course_code),
  exam_session TEXT NOT NULL,
  exam_type TEXT NOT NULL CHECK (exam_type IN ('REGULAR','SUPPLEMENTARY')),
  internal_marks INTEGER,
  external_marks INTEGER,
  total_marks INTEGER,
  max_marks INTEGER,
  result TEXT NOT NULL CHECK (result IN ('PASS','FAIL','ABSENT','DETAINED')),
  PRIMARY KEY (student_id, course_code, exam_session, exam_type)   -- our assumption, in README
);
CREATE TABLE IF NOT EXISTS rule_registry (
  rule_id TEXT PRIMARY KEY,
  description TEXT,
  parameter TEXT NOT NULL,
  operator TEXT NOT NULL,
  value TEXT NOT NULL,
  scope_programmes TEXT DEFAULT 'ALL',
  scope_batches TEXT DEFAULT 'ALL',
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  source_doc_id TEXT NOT NULL,
  source_section TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  trace_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  record_json TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    STORAGE.mkdir(exist_ok=True)
    con = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


if __name__ == "__main__":
    init_db()
    print("tables created at", SQLITE_PATH)
