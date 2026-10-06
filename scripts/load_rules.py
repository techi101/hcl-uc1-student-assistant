"""Load data/rules.csv into rule_registry (upsert). Rejects rows whose source_doc_id is not in the Source Register.
Run: python -m scripts.load_rules [path]"""
import csv
import sys

from app import config
from app.db import connect, init_db

COLS = ["rule_id", "description", "parameter", "operator", "value", "scope_programmes", "scope_batches",
        "effective_from", "effective_to", "source_doc_id", "source_section"]


def main(path: str = "data/rules.csv") -> None:
    init_db()
    known = {r["doc_id"] for r in csv.DictReader(open(config.SOURCE_REGISTER, encoding="utf-8-sig"))}
    ok, bad = 0, 0
    with connect() as con:
        for i, r in enumerate(csv.DictReader(open(path, encoding="utf-8-sig")), start=2):
            if r["source_doc_id"] not in known:
                print(f"rejected: row {i} {r['rule_id']}: source_doc_id {r['source_doc_id']} not in Source Register")
                bad += 1
                continue
            con.execute(f"INSERT OR REPLACE INTO rule_registry ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                        [r.get(c, "") for c in COLS])
            ok += 1
    print(f"rule_registry: loaded {ok}, rejected {bad}")


if __name__ == "__main__":
    main(*sys.argv[1:])
