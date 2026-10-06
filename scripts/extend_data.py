"""Add MORE synthetic students without touching the existing ones (S1001-S1032 and their planted edge cases).
Same LLM + Pydantic pipeline as scripts/generate_data.py; code still derives totals, PASS/FAIL and backlogs.
New groups: 2025 batch (semester 3, which matches the semester-3 courses), 16 per programme -> S1033-S1064.
Re-running replaces only the S1033+ rows, so it is safe to repeat.
Run: python -m scripts.extend_data && python -m scripts.validate_data --dir data/students_csv
     && python -m scripts.load_students --dir data/students_csv
"""
import csv
import json
import logging
import os
import time

import httpx
from pydantic import ValidationError

from app import config
from app.tools import session_key
from scripts.generate_data import COURSES, EXAM_SESSION, OUT, PROMPT, TEMPERATURE, Batch, ask_llm, derive_result, rules

log = logging.getLogger(__name__)

# (programme, batch, semester, first ID number); 16 students per group
NEW_GROUPS = [("B.Tech CSE", 2025, 3, 1033), ("B.Tech ECE", 2025, 3, 1049)]
PER_GROUP = 16
LOCAL_BATCH = 3          # short outputs: a 7B CPU model writes ~3 students of valid JSON in 1-2 min
FIRST_NEW = 1033


def ask_ollama(programme: str, batch: int, n: int, calls: list) -> Batch:
    """Same prompt and validation as generate_data.ask_llm, but on the local Ollama model (used when no Groq key)."""
    codes = sorted(c for c, _ in COURSES[programme])
    prompt = PROMPT.format(programme=programme, batch=batch, n=n,
                           courses=", ".join(f"{c} {nm}" for c, nm in COURSES[programme]))
    last_err = None
    for attempt in range(1, 5):
        t0 = time.perf_counter()
        try:  # same num_ctx as app/llm.py: a different value makes Ollama reload the model (minutes on CPU)
            r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=900, json={
                "model": config.OLLAMA_MODEL, "stream": False, "format": "json", "keep_alive": "4h",
                "options": {"temperature": TEMPERATURE, "num_predict": 3000, "num_ctx": 4096},
                "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
        except httpx.HTTPError as e:            # a slow or busy model is retried, not fatal
            last_err = e
            log.info("  attempt %d failed: %s", attempt, e)
            continue
        d = r.json()
        calls.append({"model": f"ollama:{config.OLLAMA_MODEL}", "programme": programme, "batch": batch,
                      "attempt": attempt, "tokens": d.get("prompt_eval_count", 0) + d.get("eval_count", 0),
                      "seconds": round(time.perf_counter() - t0, 1)})
        try:
            b = Batch.model_validate_json(d["message"]["content"])
            if len(b.students) != n:
                raise ValueError(f"expected {n} students, got {len(b.students)}")
            for s in b.students:
                if sorted(c.course_code for c in s.courses) != codes:
                    raise ValueError(f"{s.full_name}: wrong course list")
            return b
        except (ValidationError, ValueError) as e:      # nothing the LLM says is trusted unvalidated
            last_err = e
            calls[-1]["rejected"] = str(e)[:200]
            log.info("  rejected attempt %d: %s", attempt, str(e)[:120])
    raise SystemExit(f"LLM output failed validation 4 times for {programme} {batch}: {last_err}")


def generate(programme: str, batch: int, calls: list) -> Batch:
    if os.getenv("GROQ_API_KEY"):
        return ask_llm(programme, batch, calls)          # 8 per call on the cloud model
    return ask_ollama(programme, batch, LOCAL_BATCH, calls)


def read(name: str) -> list[dict]:
    return list(csv.DictReader(open(OUT / f"{name}.csv", encoding="utf-8-sig")))


def write(name: str, rows: list[dict]) -> None:
    with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")  # LF, like the committed CSVs
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    R = rules()
    # keep everything below S1033 exactly as it is; drop earlier extension rows so re-runs don't duplicate
    keep = lambda r: int(r["student_id"][1:]) < FIRST_NEW  # noqa: E731
    students = [r for r in read("students") if keep(r)]
    attendance = [r for r in read("attendance") if keep(r)]
    results = [r for r in read("results") if keep(r)]
    taken = {s["full_name"] for s in students}
    calls: list = []

    for programme, batch, sem, start in NEW_GROUPS:
        recs = []
        while len(recs) < PER_GROUP:
            log.info("LLM: %s %s (%d/%d) ...", programme, batch, len(recs), PER_GROUP)
            # names must stay unique: authorise() refuses questions that mention another student's name
            for s in generate(programme, batch, calls).students:
                if s.full_name not in taken and len(recs) < PER_GROUP:
                    taken.add(s.full_name)
                    recs.append(s)
        for i, s in enumerate(recs):
            sid = f"S{start + i}"
            new_res = []
            for c in s.courses:
                a = {"student_id": sid, "course_code": c.course_code, "classes_held": c.classes_held,
                     "classes_attended": c.classes_attended}
                r = {"student_id": sid, "course_code": c.course_code, "exam_session": EXAM_SESSION,
                     "exam_type": "REGULAR", "internal_marks": c.internal_marks, "external_marks": c.external_marks,
                     "total_marks": c.internal_marks + c.external_marks, "max_marks": 100, "result": None}
                # CODE decides the result from the rule thresholds, never the LLM
                r["result"] = derive_result({**a, **r}, R)
                if r["result"] == "DETAINED":
                    r["external_marks"], r["total_marks"] = 0, r["internal_marks"]
                attendance.append(a)
                new_res.append(r)
            results.extend(new_res)
            latest = {}
            for r in sorted(new_res, key=lambda r: session_key(r["exam_session"])):
                latest[r["course_code"]] = r["result"]
            students.append({"student_id": sid, "full_name": s.full_name, "programme": programme,
                             "batch_year": batch, "current_semester": sem, "cgpa": round(s.cgpa, 2),
                             "active_backlogs": sum(v != "PASS" for v in latest.values())})

    for name, rows in [("students", students), ("attendance", attendance), ("results", results)]:
        write(name, rows)
    # record the extension next to the original generation log, so the AI use stays auditable
    log_path = OUT / "generation_log.json"
    gl = json.loads(log_path.read_text(encoding="utf-8"))
    gl["extension"] = {"script": "scripts/extend_data.py", "groups": NEW_GROUPS, "calls": calls,
                       "students_added": len(students) - sum(1 for s in students if int(s["student_id"][1:]) < FIRST_NEW)}
    gl["students"] = len(students)
    log_path.write_text(json.dumps(gl, indent=2), encoding="utf-8")
    log.info("now %d students, %d attendance rows, %d results", len(students), len(attendance), len(results))


if __name__ == "__main__":
    main()
