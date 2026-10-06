# Sample audit records (HCL deliverable: three sample audit records for different answer types)
Generated 6 Oct 2026 from real `POST /ask` calls (then `GET /audit/{trace_id}`) on this repo's API,
LLM provider = Groq fallback (`openai/gpt-oss-120b`, see `model` in each record). Each file = request + response + audit record.
| File | answer_type | What it shows |
|---|---|---|
| 1_retrieved_fact_cited_policy.json | retrieved_fact | 80% from the circular (supersedes Regulations 11.2, Annex A step 2); FAQ 65% flagged (step 3) |
| 2_calculated_eligibility.json | calculated | S1002: 31/40 = 77.5% computed by a tool; rule ATT-MIN-02 (80%) + floor ATT-FLOOR-01 (60%) → eligible only with relaxation |
| 3_refused_other_student.json | refused | S1001 asks for S1002's marks → refused by code before any LLM call (model "none", 0 tokens) |
| 4_not_found.json | not_found | no evidence above the score floor → exact not_found message |
The audit record stores the question category, not the question text or names (R7: no personal data that isn't needed).
