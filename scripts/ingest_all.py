"""Ingest every document listed in the Source Register (once; unchanged files are skipped).
Run: python -m scripts.ingest_all            (uses data/source_register.csv, else the PROPOSED one)
"""
# WHAT THIS FILE IS: the one-time setup script that loads ALL our university documents into the search index.
# It reads data/source_register.csv (the list of every document with its id, file name, authority level,
# effective dates and scope) and indexes each file: split into chunks, embed, store in Chroma.
# Real example: the row for "SYN-CIRC-ATT-2026" points to its file in data/docs/; after this script runs,
# a question about attendance can find that circular's paragraph 1.
# extract_rules=False: our OWN documents do not go through the AI rule extractor, because our rules were
# typed and checked by a human in data/rules.csv. The extractor is only for NEW documents uploaded live.
# csv = reads spreadsheet-like .csv files row by row.
import csv
# logging = log settings; sys = lets us return an exit code; time = a stopwatch for each file.
import logging
import sys
import time

# config = our settings (folders, file paths); retrieval = the code that indexes and searches documents.
from app import config, retrieval

# Show only WARNING and worse from the app, so the screen shows our clean progress lines, not every info message.
logging.basicConfig(level=logging.WARNING)


# IN: nothing  ->  OUT: exit code 0 (every file found) or 1 (at least one file was missing).
# Example output line (format only, numbers invented): "  indexed          SYN-CIRC-ATT-2026        chunks=   3    0.8s"
# On a second run unchanged files print "already_indexed" and are skipped (ingest_file compares file hashes).
def main() -> int:
    # Use the final register (data/source_register.csv) if it exists, else the draft
    # "source_register_PROPOSED.csv" in the same folder.
    reg = config.SOURCE_REGISTER if config.SOURCE_REGISTER.exists() else config.SOURCE_REGISTER.with_name(
        "source_register_PROPOSED.csv")
    # Read every row as a dict keyed by column name, e.g. {"doc_id": "...", "filename": "...", ...}.
    # "utf-8-sig" also removes the invisible BOM mark that Excel adds at the start of CSV files.
    rows = list(csv.DictReader(open(reg, encoding="utf-8-sig")))
    print(f"register: {reg.name} ({len(rows)} rows)")
    # failed = how many listed files we could not find.
    failed = 0
    for row in rows:
        # The file name column may be called "filename" or "file_name"; accept either.
        fname = row.get("filename") or row.get("file_name") or ""
        path = config.DOCS_DIR / fname
        # No file name, or the file is not in data/docs/: report it, count it, move on to the next row.
        if not fname or not path.exists():
            print(f"  SKIP {row['doc_id']}: file not found ({fname})")
            failed += 1
            continue
        # Start the stopwatch, index the file, then print status, doc id, chunk count and seconds taken.
        # perf_counter = a precise clock for measuring how long something takes.
        # The ":16s", ":24s", ":4d", ":5.1f" parts pad the values so the columns line up neatly.
        t0 = time.perf_counter()
        out = retrieval.ingest_file(str(path), row, extract_rules=False)
        print(f"  {out['status']:16s} {row['doc_id']:24s} chunks={out['chunks_indexed']:4d}  {time.perf_counter() - t0:5.1f}s")
    # Final check: total number of chunk vectors now stored in Chroma (our vector database).
    print(f"vectors in Chroma: {retrieval.vector_count()}")
    # Exit code 1 tells a script or CI that something was missing; 0 means all good.
    return 1 if failed else 0


# Run main() only when this file is started directly (python -m scripts.ingest_all), not when imported.
# sys.exit passes main()'s 0 or 1 back to the terminal.
if __name__ == "__main__":
    sys.exit(main())
