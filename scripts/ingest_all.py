"""Ingest every document listed in the Source Register (once; unchanged files are skipped).
Run: python -m scripts.ingest_all            (uses data/source_register.csv, else the PROPOSED one)
"""
import csv
import logging
import sys
import time

from app import config, retrieval

logging.basicConfig(level=logging.WARNING)


def main() -> int:
    reg = config.SOURCE_REGISTER if config.SOURCE_REGISTER.exists() else config.SOURCE_REGISTER.with_name(
        "source_register_PROPOSED.csv")
    rows = list(csv.DictReader(open(reg, encoding="utf-8-sig")))
    print(f"register: {reg.name} ({len(rows)} rows)")
    failed = 0
    for row in rows:
        fname = row.get("filename") or row.get("file_name") or ""
        path = config.DOCS_DIR / fname
        if not fname or not path.exists():
            print(f"  SKIP {row['doc_id']}: file not found ({fname})")
            failed += 1
            continue
        t0 = time.perf_counter()
        out = retrieval.ingest_file(str(path), row)
        print(f"  {out['status']:16s} {row['doc_id']:24s} chunks={out['chunks_indexed']:4d}  {time.perf_counter() - t0:5.1f}s")
    print(f"vectors in Chroma: {retrieval.vector_count()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
