# Evaluation report — config `all-MiniLM-L6-v2_k5` (29 questions, model groq:openai/gpt-oss-120b)

| Metric | Result |
|---|---|
| Answer correctness (type + exact numbers/dates) | 24/29 = 83% |
| Citation accuracy (expected doc + section cited) | 15/20 = 75% |
| Abstention accuracy | 27/29 = 93% |
| Tool-result correctness | 9/9 = 100% |
| Retrieval hit rate@5 | 16/20 = 80% |
| Latency p50 / p95 | 6833 ms / 35285 ms |
| LLM calls / tokens per question (mean) | 1.6206896551724137 / 1216 |

## Failures

- **Q04** (conflict): expected `retrieved_fact`, got `refused` — Please log in: personal questions need your student ID (X-Student-Id header).
- **Q16** (multi_step): expected `calculated`, got `not_found` — I could not find this information in the authorised university sources.
- **Q17** (multi_step): expected `retrieved_fact`, got `refused` — Please log in: personal questions need your student ID (X-Student-Id header).
- **Q22** (policy): expected `retrieved_fact`, got `retrieved_fact` — A CGPA of 8.00 or above is required for a B.Tech degree with honours (first division with distinction).
- **Q24** (scope): expected `retrieved_fact`, got `not_found` — I could not find this information in the authorised university sources.
