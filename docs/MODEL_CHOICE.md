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
