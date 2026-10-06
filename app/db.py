"""SQLite: Annex C tables exactly as HCL fixed them (+ audit_log). Owner: B."""
# WHAT THIS FILE IS: sets up our database. SQLite = a small database stored as ONE file on disk (no server needed).
# sqlite3 = Python's built-in library to talk to SQLite.
import sqlite3

# SQLITE_PATH = where the database file lives; STORAGE = the folder it lives in (both set in app/config.py).
from app.config import SQLITE_PATH, STORAGE

# SCHEMA = the SQL commands that create our 6 tables (the table layouts HCL gave in Annex C, plus audit_log).
# "IF NOT EXISTS" = safe to run many times; it never wipes existing data.
# "CHECK (...)" = the database itself refuses bad data (e.g. cgpa must be 0-10, attended <= held).
# The tables:
#   students      - one row per student, e.g. S1002 (id must look like "S" + 4 digits).
#   courses       - one row per course, e.g. CS201.
#   attendance    - classes held vs attended per student per course (S1002 in CS201: 31 of 40 = 77.5%).
#   results       - marks and PASS/FAIL per student, course and exam session.
#   rule_registry - the rules as clean numbers, e.g. ATT-MIN-01 = 75 (Regulations 11.2),
#                   ATT-MIN-02 = 80 from 2026-08-01 (circular SYN-CIRC-ATT-2026). app/precedence.py picks the winner.
#   audit_log     - a saved record of every answer we gave (trace_id + time + full details as JSON).
# "REFERENCES" = the value must already exist in the other table (no attendance for an unknown student).
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


# IN: nothing  ->  OUT: an open connection to the database file.
# flow: make storage folder -> open file -> rows act like dicts -> switch on foreign-key checks -> return
def connect() -> sqlite3.Connection:
    # Create the storage folder if it is missing (SQLite needs the folder to exist).
    STORAGE.mkdir(exist_ok=True)
    # Open the database. check_same_thread=False lets the web server use it from different threads.
    con = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    # Rows come back like dictionaries, so code can write row["student_id"] instead of row[0].
    con.row_factory = sqlite3.Row
    # SQLite does NOT check "REFERENCES" links unless we switch it on, once per connection.
    con.execute("PRAGMA foreign_keys = ON")
    return con


# IN: nothing  ->  OUT: nothing (creates all tables in the database file if they are not there yet).
def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


# Runs only when you type "python -m app.db" yourself (not when another file imports this one):
# creates the tables and prints where the database file is.
if __name__ == "__main__":
    init_db()
    print("tables created at", SQLITE_PATH)
