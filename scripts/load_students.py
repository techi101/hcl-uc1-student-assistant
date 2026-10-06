"""Judges' loader (HCL 4.2 / Section 6): load student CSVs in the Annex C schema into SQLite. Owner: Suryansh (B).
Run: python -m scripts.load_students --dir test_students/ [--rules data/rules.csv]
- reads whichever of students.csv, courses.csv, attendance.csv, results.csv (+ rule_registry.csv / rules.csv) exist
- loads in dependency order; INSERT OR REPLACE (re-running is safe); extra columns ignored; BOM/CRLF tolerated
- bad rows are NOT silently dropped: each is printed as  rejected: <file> row <n>: <reason>
- the SQLite CHECK constraints (app/db.py) are the last line of defence (attended <= held, ID format, ranges)
"""
# WHAT THIS FILE IS: the loader judges use to put THEIR OWN student CSVs into our database.
# Flow: folder of CSVs -> each file in order -> each row checked -> good rows saved, bad rows printed as "rejected"
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

# ROOT = project folder. Adding it to Python's search path lets this script import app.db when run on its own.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.db import connect, init_db  # noqa: E402

# The load order matters: students and courses FIRST, because attendance and results point at them
# (a result for S1002 CS201 needs student S1002 and course CS201 to exist already). Rule table last.
TABLES = [  # (file stem, table, columns)
    ("students", "students", ["student_id", "full_name", "programme", "batch_year", "current_semester", "cgpa", "active_backlogs"]),
    ("courses", "courses", ["course_code", "course_name", "programme", "semester", "credits"]),
    ("attendance", "attendance", ["student_id", "course_code", "classes_held", "classes_attended"]),
    ("results", "results", ["student_id", "course_code", "exam_session", "exam_type", "internal_marks", "external_marks",
                            "total_marks", "max_marks", "result"]),
    ("rule_registry", "rule_registry", ["rule_id", "description", "parameter", "operator", "value", "scope_programmes",
                                        "scope_batches", "effective_from", "effective_to", "source_doc_id", "source_section"]),
]


# IN: table name + one CSV row  ->  OUT: a reason text if the row is bad, or None if it is fine
# Only for results: total must equal internal + external (e.g. 30 + 14 = 44). The database can't check this itself.
def check_row(table: str, r: dict) -> str | None:
    """Logical checks the CHECK constraints can't express (total = internal + external)."""
    if table == "results":
        try:
            if int(float(r["total_marks"])) != int(float(r["internal_marks"])) + int(float(r["external_marks"])):
                return "total_marks != internal_marks + external_marks"
        except (TypeError, ValueError):
            return "marks are not numbers"
    return None


# IN: open database + CSV path + table name + column list  ->  OUT: (rows loaded, rows rejected)
# Flow: read CSV -> required columns present? -> for each row: our check -> INSERT -> database CHECK rules -> count
def load_file(con: sqlite3.Connection, path: Path, table: str, cols: list[str]) -> tuple[int, int]:
    # read all rows; "utf-8-sig" drops Excel's invisible BOM mark, newline="" handles Windows line endings
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", newline="")))
    # if a required column is missing, skip the whole file and say so (every row would be wrong anyway)
    if rows:
        missing = [c for c in cols if c not in rows[0]]
        if missing:
            print(f"rejected: {path.name}: missing required columns {missing} (whole file skipped)")
            return 0, len(rows)
    ok = bad = 0
    # loop over rows; n starts at 2 because CSV line 1 is the header, so n = the line number in the file
    for n, r in enumerate(rows, start=2):
        # take only our columns, in our order; trim spaces; empty cell -> None (NULL in the database)
        values = [(r.get(c) or "").strip() or None for c in cols]
        # our own check first; a bad row is printed and counted, never silently dropped
        reason = check_row(table, r)
        if reason:
            print(f"rejected: {path.name} row {n}: {reason}")
            bad += 1
            continue
        # SQL in words: "put this row into the table; if a row with the same key already exists, replace it".
        # So running the loader twice is safe (no duplicates). The "?" marks are filled safely with the values.
        try:
            con.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", values)
            ok += 1
        # the database's own rules (e.g. attended <= held, ID format) refuse bad rows -> print the reason
        except sqlite3.Error as e:            # CHECK / FOREIGN KEY / NOT NULL violations
            print(f"rejected: {path.name} row {n}: {e}")
            bad += 1
    return ok, bad


# IN: command line "--dir <folder>" (+ optional "--rules <csv>")  ->  OUT: prints a summary; exit 0 = all rows loaded
def main() -> int:
    # read the command line; stop with code 2 if the folder does not exist
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="folder with students.csv, courses.csv, attendance.csv, results.csv")
    ap.add_argument("--rules", help="optional rule registry CSV (e.g. data/rules.csv)")
    a = ap.parse_args()
    d = Path(a.dir)
    if not d.is_dir():
        print(f"folder not found: {d}")
        return 2
    # make sure all tables exist (creates them if the database is new)
    init_db()
    total_bad = 0
    with connect() as con:
        # go through the 5 tables in dependency order
        for stem, table, cols in TABLES:
            # which file to use: "<name>.csv"; for rules also accept "rules.csv"; "--rules" overrides both
            candidates = [d / f"{stem}.csv"] + ([d / "rules.csv"] if stem == "rule_registry" else [])
            if stem == "rule_registry" and a.rules:
                candidates = [Path(a.rules)]
            # take the first file that exists; if none, skip this table (judges may give only some files)
            path = next((p for p in candidates if p.exists()), None)
            if not path:
                continue
            ok, bad = load_file(con, path, table, cols)
            total_bad += bad
            print(f"{path.name:22s} -> {table:14s} loaded {ok}, rejected {bad}")
        # SQL in words: "how many rows are in each table now?" -- printed as the final summary
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for _, t, _ in TABLES}
    print("database now:", ", ".join(f"{t}={c}" for t, c in counts.items()))
    return 1 if total_bad else 0


# run main() only when this file is started directly, not when imported
if __name__ == "__main__":
    sys.exit(main())
