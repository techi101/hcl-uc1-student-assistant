"""Load data/rules.csv into rule_registry (upsert). Rejects rows whose source_doc_id is not in the Source Register.
Run: python -m scripts.load_rules [path]"""
# WHAT THIS FILE IS: copies the rules from a spreadsheet file (data/rules.csv) into the rule_registry table.
# "upsert" = insert a new rule, or replace it if a rule with the same rule_id is already there.
# csv = Python's built-in library to read CSV (comma-separated) files. sys = to read command-line arguments.
import csv
import sys

# config = project settings (e.g. where the Source Register file is); connect/init_db = open/create the database.
from app import config
from app.db import connect, init_db

# The 11 columns of the rule_registry table, in order. Each CSV row must give these.
# Example row: ATT-MIN-02, "Minimum attendance raised to 80%", min_attendance_pct, >=, 80, B.Tech, ALL,
#              2026-08-01, (no end date), SYN-CIRC-ATT-2026, section 1.
COLS = ["rule_id", "description", "parameter", "operator", "value", "scope_programmes", "scope_batches",
        "effective_from", "effective_to", "source_doc_id", "source_section"]


# IN: path of the rules CSV (default data/rules.csv)  ->  OUT: nothing; rules saved in the database + a summary printed.
# flow: create tables -> read list of known documents -> for each CSV row: known source? -> save it : reject it
def main(path: str = "data/rules.csv") -> None:
    # Make sure the tables exist before we write into them.
    init_db()
    # known = the set of every doc_id in the Source Register (our list of approved documents).
    # WHY: every rule must point to a real, registered document, so each answer can cite its source.
    # "utf-8-sig" = read the file even if Excel saved it with a hidden marker at the start.
    known = {r["doc_id"] for r in csv.DictReader(open(config.SOURCE_REGISTER, encoding="utf-8-sig"))}
    # Counters: how many rows were saved (ok) and how many were refused (bad).
    ok, bad = 0, 0
    with connect() as con:
        # Go through the CSV one row at a time. start=2 because row 1 of the file is the header,
        # so the printed row number matches what you see in Excel.
        for i, r in enumerate(csv.DictReader(open(path, encoding="utf-8-sig")), start=2):
            # Reject a rule whose source document is not in the Source Register (we cannot cite it).
            if r["source_doc_id"] not in known:
                print(f"rejected: row {i} {r['rule_id']}: source_doc_id {r['source_doc_id']} not in Source Register")
                bad += 1
                continue
            # Save the row. "INSERT OR REPLACE" = add it, or overwrite the old row with the same rule_id.
            # The "?" marks are filled safely with the row's values (a missing column becomes "").
            con.execute(f"INSERT OR REPLACE INTO rule_registry ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                        [r.get(c, "") for c in COLS])
            ok += 1
    # Print a summary, e.g. "rule_registry: loaded 10, rejected 0".
    print(f"rule_registry: loaded {ok}, rejected {bad}")


# Runs only when started from the command line: "python -m scripts.load_rules" (optionally + a CSV path).
if __name__ == "__main__":
    main(*sys.argv[1:])
