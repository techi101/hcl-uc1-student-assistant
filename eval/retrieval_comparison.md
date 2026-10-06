# Retrieval configuration comparison (no LLM), 6 Oct 2026

Run: `python -m eval.run_eval --retrieval-only --k {3,5}` with `EMBED_MODEL` = all-MiniLM-L6-v2 (default) or BAAI/bge-small-en-v1.5.
Test set: eval/testset.json (29 questions; 20 have an expected source doc + section). Hit = expected doc_id (+ section prefix) in the top-k chunks.

| Embedding model | k=3 | k=5 |
|---|---|---|
| **all-MiniLM-L6-v2** | **16/20 = 80%** | **16/20 = 80%** |
| BAAI/bge-small-en-v1.5 | 10/20 = 50% | 11/20 = 55% |

**Decision: keep all-MiniLM-L6-v2, k=5.** It beats bge-small by 25–30 points on our NSUT corpus. bge misses the synthetic circular (SYN-CIRC-ATT-2026 §1) on every eligibility question (Q04–Q07, Q29), which is the source the 80% answer depends on.

MiniLM misses (both k): Q08 (Regulations 11.2 asked as of 2026-07-15: the circular chunk outranks it), Q10 (12.7) and Q11 (9.5 / Table 5) for the question "Did I pass CS201?" (a short personal question; the pass decision comes from the tool + rule_registry, so the answer is still correct when the tool runs), Q22 (7.9 honours).
These are kept in the set on purpose; they show where hybrid (BM25 + dense) search would help next.
