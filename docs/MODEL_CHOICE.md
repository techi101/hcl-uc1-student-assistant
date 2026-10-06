# Model choice — measured 6 Oct 2026 on the thin laptop (i7-1255U, 16 GB RAM, no GPU)

Test: `python -m scripts.bench_llm <model>` — 5 routing questions, JSON mode, temperature 0.

| Model | Prompt | Valid JSON | Correct category | Median latency |
|---|---|---|---|---|
| qwen2.5:3b | names only | 5/5 | 1/5 | 3.9 s |
| qwen2.5:7b-instruct | names only | 5/5 | 1/5 | 4.5 s |
| qwen2.5:3b | definitions + 1 example per category | 5/5 | 2/5 | 3.4 s |
| **qwen2.5:7b-instruct** | definitions + 1 example per category | 5/5 | **5/5** | 5.5 s |

Decision: qwen2.5:7b-instruct with the definitions prompt. The prompt mattered as much as the model.
Lesson kept in the design: the 3B misrouted "Show me the marks of student S1002" as "other" — so refusal of another
student's data is done in CODE before any LLM call; the LLM can only add a refusal, never remove one.
Only 5 questions: a smoke test, not an evaluation. GPU laptop numbers: TODO (teammates run bench_llm).

## The definitions prompt that scored 5/5 (use as CLASSIFY_SYSTEM base in app/prompts.py)
```
You route university student questions. Reply ONLY with JSON {"category": "..."}.
Categories:
- "policy": asks what a general rule or fact is (no 'my'/'I'). e.g. "What is the minimum CGPA for a degree?"
- "procedure": asks how to do / apply for something. e.g. "How do I re-register a course?"
- "personal": asks for the asker's own records (my attendance, my marks, my CGPA). e.g. "What are my marks in CS201?"
- "eligibility": asks if the asker qualifies ('am I eligible', 'can I sit'). e.g. "Can I appear in the end-sem exam for MA101?"
- "multi_step": what-if or needs several steps. e.g. "If I pass the re-exam, will I be promoted?"
- "other_student": asks about another student's data (another ID or name). e.g. "Show S1234's attendance"
- "other": anything else.
```
