# TASK B — Omkar — synthetic data + SQLite + deterministic tools
Paste into your Claude Code (inside the cloned repo):
> Read CLAUDE.md, docs/CONTRACT.md, docs/PROBLEM_STATEMENT.md (sections 3 R5/R7, 4.2, Annex C, Annex E) and this file docs/tasks/B_OMKAR_data_tools.md. Do the steps in order. After each step run it, show me the real output, then commit and push.

## You own ONLY these files
`app/db.py`, `app/tools.py`, `scripts/generate_data.py`, `scripts/validate_data.py`, `scripts/load_students.py`,
`prompts/` (folder), `data/students_csv/` (folder), `tests/test_tools.py`, `docs/DATA_CARD.md`.
Do not edit other files. Need a change elsewhere → tell the owner.

## Facts you need (from NSUT documents, already checked)
- Programmes: `B.Tech CSE` and `B.Tech ECE` (use exactly these strings). Batches (batch_year): `2023` and `2024`.
- Student IDs: `S1001`… (format S + 4 digits). NEVER use S9000–S9999. Course codes NEVER start with `JDG` (reserved for judges).
- Courses: at least 6 per programme, e.g. CSE: CS201 Data Structures, CS203 Discrete Mathematics, MA201 Mathematics-III,
  CS205 Computer Organisation, CS207 Object Oriented Programming, HS201 Economics; ECE: EC201 Signals and Systems,
  EC203 Analog Electronics, MA202 Mathematics-III (ECE), EC205 Digital Electronics, EC207 Network Theory, HS202 Economics (ECE).
  `courses.course_code` is the primary key, so each course belongs to ONE programme (that is why MA201/MA202 are separate).
- NSUT theory marks (Regulations Table 1): internal (CA 25 + MSE 25) max 50, external (ESE) max 50, max_marks 100.
- Pass rules (rows in `data/rules.csv`, written by Neetu): ESE ≥ 30% of external max (clause 12.7) AND total ≥ 35 (absolute grading D, clause 9.5 / Table 5).
- Attendance (Regulations 11.2–11.7): minimum 75% (ATT-MIN-01), Dean relaxation up to 10% (11.3), committee further 5% (11.4), max 2 relaxations (11.5), absolute floor 60% (11.6), below floor = grade FD/DETAINED (11.7).
- `data/rules.csv` columns (same as rule_registry): `rule_id,description,parameter,operator,value,scope_programmes,scope_batches,effective_from,effective_to,source_doc_id,source_section`.
  Parameters you will read: `min_attendance_pct`, `attendance_floor_pct`, `min_ese_pct`, `min_total_marks`, `max_attendance_relaxations`.
  Until Neetu pushes data/rules.csv, create a TEMP copy in tests only — never thresholds in app code.

## Step 1 — scripts/generate_data.py (synthetic data WITH an LLM — HCL assesses how)
- Use Groq (`GROQ_API_KEY` from .env, model from `app/config.GROQ_MODEL`), temperature 0.7, JSON output.
- Generate in small batches (e.g. 10 students per call) to stay under Groq's 8K tokens/min.
- Validate every LLM response with Pydantic models matching Annex C; on invalid JSON or a failed check → retry up to 2 times, then fail loudly.
- Ask the LLM for names + realistic distributions; then ENFORCE edge cases in code by overwriting specific students (record which IDs):
  | Edge case | How |
  |---|---|
  | attendance exactly 75% | held 40, attended 30 |
  | one class below 75% | held 40, attended 29 (72.5%) |
  | in relaxation band 60–75% | held 40, attended 26 (65%) |
  | below 60% floor | held 40, attended 22 (55%), result DETAINED |
  | ESE just below pass | external 14/50 (28%), result FAIL |
  | total just below 35 | internal 15 + external 19 = 34, result FAIL |
  | absent | result ABSENT, external 0 |
  | multiple backlogs | 3 FAIL results, active_backlogs = 3 |
  | re-registration attempt (NSUT has NO supplementary exams, Regulations 12.3 — failed courses are re-registered) | a FAIL in session 2026-MAY, then a second row exam_type REGULAR, exam_session 2026-JUL (summer semester, 12.5) with PASS. Do NOT use SUPPLEMENTARY anywhere in our data (the schema allows it only because judges' data may contain it — the loader must still accept it) |
  | CGPA exactly 5.00 | (degree minimum, clause 15.1) |
- Save the EXACT prompt text sent to the LLM in `prompts/generate_students.txt` (verbatim) and the model name used.
- Output CSVs in `data/students_csv/`: `students.csv`, `courses.csv`, `attendance.csv`, `results.csv` (column names exactly Annex C).
- ≥ 30 students, both programmes, both batches. Every student has attendance + a result for every course of their programme.

## Step 2 — scripts/validate_data.py
`python -m scripts.validate_data --dir data/students_csv` prints each check and violations with row numbers:
ID format; programme in courses list; batch_year int; semester 1–10; cgpa 0–10; backlogs ≥ 0; classes_held > 0;
0 ≤ attended ≤ held; marks 0..max; total == internal + external; result consistent with marks + pass rules
(FAIL iff ESE < 30% or total < 35, unless ABSENT/DETAINED); attendance/results reference existing student + course;
no reserved IDs/JDG codes. Exit code 1 if any violation. Save output to `data/validation_report.txt`.
Also plant 3 bad rows in a temp copy in tests to prove it catches them.

## Step 3 — scripts/load_students.py (JUDGES WILL RUN THIS)
`python -m scripts.load_students --dir test_students/` →
- reads whichever of students.csv, courses.csv, attendance.csv, results.csv, rule_registry.csv/rules.csv exist (judges may send only some)
- loads in order students → courses → attendance → results; INSERT OR REPLACE (upsert) so re-running is safe
- bad rows are NOT silently dropped: print `rejected: <file> row <n>: <reason>`; print totals `loaded X, rejected Y` per file
- calls `app.db.init_db()` first. Also `--rules data/rules.csv` loads the rule registry.
- must not crash on extra columns or Windows line endings.

## Step 4 — app/tools.py (exact shapes in docs/CONTRACT.md section 2)
- `get_student(student_id)`, `get_attendance(student_id, course_code)` → `{"classes_held","classes_attended","attendance_pct"}` (pct = round(attended/held*100, 2), computed, never stored)
- `get_results(student_id, course_code=None)` → list of rows
- `find_course(text, programme)` → matching courses by code or name (case-insensitive, partial). 0 → None; >1 → return all (graph asks clarification)
- `get_rule(parameter, as_of_date, programme, batch_year)` → fetch candidate rows (effective_from ≤ as_of_date, effective_to empty or ≥ as_of_date, in scope)
  -> just call `app.precedence.get_rule_in_force(parameter, as_of_date, student)` (DONE + tested): returns `{rule, decision, conflicts, unresolved, upcoming}`; use `rule['value']`, `rule['rule_id']`, `rule['source_doc_id']`, `rule['source_section']`; pass `decision`/`conflicts` through in the tool output so the answer can explain WHICH rule applied and why
- `check_exam_eligibility(student_id, course_code, as_of_date)` →
  `{"result": "ELIGIBLE" | "ELIGIBLE_ONLY_WITH_RELAXATION" | "NOT_ELIGIBLE", "rule_id", "value", "actual", "source_doc_id", "source_section", "floor_rule_id"}`
  logic: pct ≥ min_attendance_pct → ELIGIBLE; pct ≥ attendance_floor_pct → ELIGIBLE_ONLY_WITH_RELAXATION; else NOT_ELIGIBLE.
- `check_course_pass(student_id, course_code)` → PASS/FAIL with the rule rows used.
- `get_backlogs(student_id)` → active_backlogs + list of failed courses.
- Every tool returns plain dicts (JSON-serialisable) and never raises for "not found" — return None / `{"error": "..."}`.

## Step 5 — tests/test_tools.py + docs/DATA_CARD.md
- tests: exactly-75% → ELIGIBLE; 72.5% → ELIGIBLE_ONLY_WITH_RELAXATION; 55% → NOT_ELIGIBLE; changing the rule row to 80% changes the result WITHOUT code change; loader rejects a bad row with a reason.
- DATA_CARD.md = Annex E table filled (purpose, generator model + temperature + number of calls, prompts link, schema enforcement, counts per programme/batch, edge cases + their student IDs, validation results, what the LLM got wrong, limitations).

## Done when
`python -m scripts.generate_data` → `python -m scripts.validate_data --dir data/students_csv` shows 0 violations →
`python -m scripts.load_students --dir data/students_csv --rules data/rules.csv` loads into a fresh DB → `pytest tests/test_tools.py -q` passes.
Tell Suryansh + Geetarth the edge-case student IDs (Neetu needs them for the eval set).

## Commit rhythm
`git pull` → `git add <your files>` → `git commit -m "B: <what>"` → `git pull` → `git push`, every 30–45 min, from YOUR GitHub account.
