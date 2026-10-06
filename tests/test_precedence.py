"""Annex A precedence tests: HCL's own worked example (A.3) + our scope rules. No LLM, no DB."""
# WHAT THIS FILE IS: tests for app/precedence.py, the code that decides which rule wins when documents disagree (HCL Annex A).
# Pure Python: no LLM, no database, no search. Each test builds tiny fake documents by hand and checks the decision.
# Real example (HCL Annex A.3): regulation says 75% (level 1), circular says 80% and supersedes it (level 2),
# department FAQ says 65% (level 4). On 6 Oct 2026 the answer must be 80%. The first test checks exactly that.
# pytest runs every test_* function; "assert X" fails the test if X is False.
from app.precedence import batch_in_scope, pick_rule, programme_in_scope, resolve

# A typical student: B.Tech CSE, admitted 2023. Used where scope (programme / batch) matters.
CSE_2023 = {"programme": "B.Tech CSE", "batch_year": 2023}


# IN: a few fields  ->  OUT: a fake retrieved chunk dict with every field resolve() reads.
# Defaults: applies to ALL programmes and batches, supersedes nothing, score 0.7. A test types only what it cares about.
def chunk(doc_id, level, eff_from, text, section="1", supersedes="", eff_to="", progs="ALL", batches="ALL", score=0.7):
    return {"doc_id": doc_id, "authority_level": level, "effective_from": eff_from, "effective_to": eff_to,
            "text": text, "section": section, "supersedes": supersedes, "scope_programmes": progs,
            "scope_batches": batches, "score": score}


# HCL Annex A.3: regulation 75% (L1, 2024-07-01), circular 80% supersedes clause (L2, 2026-08-01), FAQ 65% (L4, 2026-09-15)
REG = chunk("ACAD-REG-2024", 1, "2024-07-01", "7.2 Minimum attendance shall be 75% of classes.", section="7.2")
CIRC = chunk("ACAD-2026-08", 2, "2026-08-01", "Minimum attendance shall be 80% of classes.", supersedes="ACAD-REG-2024#7.2")
FAQ = chunk("DEPT-FAQ", 4, "2026-09-15", "Q1 65% attendance is enough.", section="Q1")
# Q = the question asked in most tests below.
Q = "What is the minimum attendance requirement?"


# PROVES: HCL's own worked example. On 2026-10-06 the circular (80%) is applicable, the regulation (75%) is superseded (step 2),
# the FAQ (65%) is overridden by higher authority (step 3), the conflict is reported, and nothing is left unresolved.
# WHY: this is the exact case in the problem statement. If it fails, the core promise "right rule, with the reason" is broken.
def test_worked_example_circular_wins_and_faq_conflict_noted():
    out = resolve([REG, CIRC, FAQ], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-2026-08"]
    assert [c["doc_id"] for c in out["superseded"]] == ["ACAD-REG-2024"]          # step 2
    assert [c["doc_id"] for c in out["overridden"]] == ["DEPT-FAQ"]                # step 3
    assert any("step 3" in c for c in out["conflicts"])
    assert not out["unresolved"]


# PROVES: on 2026-07-15 (before the circular starts on 2026-08-01) the regulation's 75% applies, the circular is
# listed as not yet effective, and an "upcoming" note is added.
# WHY: Annex A step 1 (applicability by date). The "Answer as of" date must change the answer, and students get warned of the coming 80%.
def test_before_circular_is_effective_regulation_applies_and_circular_is_upcoming():
    out = resolve([REG, CIRC], "2026-07-15", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-REG-2024"]
    assert [c["doc_id"] for c in out["excluded_future"]] == ["ACAD-2026-08"]
    assert any(c.startswith("upcoming") for c in out["conflicts"])


# PROVES: a level 3 department notice that claims to supersede 7.2 does NOT supersede the regulation; it is overridden instead.
# WHY: Annex A step 2 lets only level 1-2 documents supersede. Otherwise any department notice could rewrite a university regulation.
def test_level3_cannot_supersede_even_if_it_says_so():
    notice = chunk("DEPT-NOTICE", 3, "2026-09-01", "Attendance minimum is 70%.", supersedes="ACAD-REG-2024#7.2")
    out = resolve([REG, notice], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-REG-2024"]           # authority, not supersession
    assert out["overridden"][0]["doc_id"] == "DEPT-NOTICE"


# PROVES: two circulars of the same level: the later effective date (2026-01-01, 72%) wins, by step 4 (recency).
# WHY: same authority, so the newer instruction replaces the older one.
def test_same_authority_later_date_wins():
    old = chunk("CIRC-A", 2, "2025-01-01", "attendance minimum 70%")
    new = chunk("CIRC-B", 2, "2026-01-01", "attendance minimum 72%")
    out = resolve([old, new], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["CIRC-B"]
    assert any("step 4" in c for c in out["conflicts"])


# PROVES: same level AND same date with different numbers -> flagged as unresolved.
# WHY: step 5. Code must not guess; the system says there is a conflict (answer_type conflict_flagged) and points to the office.
def test_same_authority_same_date_is_unresolved():
    a = chunk("CIRC-A", 2, "2026-01-01", "attendance minimum 70%")
    b = chunk("CIRC-B", 2, "2026-01-01", "attendance minimum 72%")
    out = resolve([a, b], "2026-10-06", None, Q)
    assert out["unresolved"]


# PROVES: a level 5 forum post ("50%, trust me") never overrides the regulation; it is kept only as "informational".
# WHY: unofficial content may be mentioned but must never decide an answer.
def test_level5_never_overrides():
    forum = chunk("FORUM", 5, "2026-09-30", "attendance minimum is 50%, trust me")
    out = resolve([REG, forum], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-REG-2024"]
    assert [c["doc_id"] for c in out["informational"]] == ["FORUM"]


# PROVES: a Ph.D.-only ordinance is out of scope for a B.Tech CSE student, so nothing from it applies.
# WHY: step 1 also checks programme scope. A B.Tech student must not be answered with Ph.D. rules.
def test_scope_filters_phd_docs_for_btech_student():
    phd = chunk("PHD-ORD", 1, "2022-07-01", "Ph.D. attendance 75%", progs="Ph.D. only")
    out = resolve([phd], "2026-10-06", CSE_2023, Q)
    assert out["applicable"] == [] and out["out_of_scope"][0]["doc_id"] == "PHD-ORD"


# PROVES: programme scope matching on real NSUT scope wordings: ALL, degree only ("B.Tech" covers every branch),
# "(all branches)", same branch, other branch (no), Ph.D. only (no), and lists joined by "and".
# WHY: if scope matching is wrong, a correct rule silently drops out or another programme's rule sneaks in.
def test_programme_scope_matching():
    assert programme_in_scope("ALL", "B.Tech CSE")
    assert programme_in_scope("B.Tech", "B.Tech CSE")
    assert programme_in_scope("B.Tech (all branches)", "B.Tech ECE")
    assert programme_in_scope("B.Tech CSE", "B.Tech CSE")
    assert not programme_in_scope("B.Tech ECE", "B.Tech CSE")
    assert not programme_in_scope("Ph.D. only", "B.Tech CSE")
    assert programme_in_scope("B.Tech and B.Arch first semester", "B.Tech CSE")


# PROVES: batch scope matching on real wordings: "2023+", "Admitted 2019-20 onwards", ranges like
# "Batches 2020-21 to 2023-24" and "2019-2022", and a single batch "Admitted 2025-26".
# WHY: rules often change for new batches only. An off-by-one on a range would apply the wrong rule to a whole batch.
def test_batch_scope_matching():
    assert batch_in_scope("ALL", 2023)
    assert batch_in_scope("2023+", 2024) and not batch_in_scope("2023+", 2022)
    assert batch_in_scope("Admitted 2019-20 onwards", 2023)
    assert batch_in_scope("Batches 2020-21 to 2023-24", 2023) and not batch_in_scope("Batches 2020-21 to 2023-24", 2024)
    assert batch_in_scope("2019-2022", 2021) and not batch_in_scope("2019-2022", 2023)
    assert not batch_in_scope("Admitted 2025-26", 2023)


# rule_registry rows carry authority_level + doc_supersedes so no DB is needed
# IN: a few fields  ->  OUT: a fake rule_registry row (one rule = one number with its source and scope).
# Example: rule("ATT-MIN-02", "80", "2026-08-01", "SYN-CIRC-ATT-2026", 2, sup="NSUT-BTECH-REG-2019#11.2") = the circular's 80%.
def rule(rule_id, value, eff, doc, level, sup="", section="11.2", progs="B.Tech"):
    return {"rule_id": rule_id, "parameter": "min_attendance_pct", "operator": ">=", "value": value,
            "scope_programmes": progs, "scope_batches": "ALL", "effective_from": eff, "effective_to": "",
            "source_doc_id": doc, "source_section": section, "authority_level": level, "doc_supersedes": sup}


# The same 3-way attendance conflict as Annex A.3, but as rule rows with our real NSUT doc ids:
# 75% regulation 11.2 (level 1), 80% circular superseding 11.2 (level 2), 65% CSE FAQ (level 4, CSE only).
RULES = [rule("ATT-MIN-01", "75", "2019-07-01", "NSUT-BTECH-REG-2019", 1),
         rule("ATT-MIN-02", "80", "2026-08-01", "SYN-CIRC-ATT-2026", 2, sup="NSUT-BTECH-REG-2019#11.2", section="1"),
         rule("ATT-MIN-03", "65", "2026-09-15", "SYN-FAQ-ATT-2026", 4, section="Q1", progs="B.Tech CSE")]


# PROVES: pick_rule (used by the eligibility tools) chooses ATT-MIN-02 = 80% on 2026-10-06, says "supersedes" in its reason,
# and reports the 65% FAQ rule (ATT-MIN-03) as a conflict.
# WHY: the eligibility verdict uses this number, so it must match the rule the document path picks.
def test_pick_rule_after_circular():
    out = pick_rule(RULES, "2026-10-06", CSE_2023)
    assert out["rule"]["rule_id"] == "ATT-MIN-02" and out["rule"]["value"] == "80"
    assert "supersedes" in out["decision"] and any("ATT-MIN-03" in c for c in out["conflicts"])


# PROVES: on 2026-07-15 pick_rule chooses ATT-MIN-01 (75%) and lists ATT-MIN-02 as upcoming.
# WHY: same date logic as the document path, so a student asking in July gets July's rule plus a warning.
def test_pick_rule_before_circular():
    out = pick_rule(RULES, "2026-07-15", CSE_2023)
    assert out["rule"]["rule_id"] == "ATT-MIN-01"
    assert out["upcoming"] and "ATT-MIN-02" in out["upcoming"][0]


# PROVES: an ECE student gets 80% and NO conflict note, because the 65% FAQ is scoped to CSE only.
# WHY: scope works on rule rows too; an ECE student should not even hear about a CSE-only FAQ.
def test_pick_rule_ece_student_never_sees_cse_faq():
    out = pick_rule(RULES, "2026-10-06", {"programme": "B.Tech ECE", "batch_year": 2024})
    assert out["rule"]["rule_id"] == "ATT-MIN-02" and not out["conflicts"]


# PROVES: a circular replacing clause 11.6 (the floor) applies, the old 11.6 drops out, and clause 11.2 (a DIFFERENT clause of
# the same regulation) still applies; nothing is wrongly marked "overridden".
# WHY: a real bug found live. Supersession is per clause ("REG#11.6"), not per whole document.
def test_superseding_circular_is_not_overridden_by_other_clauses_of_the_same_regulation():
    # found live 13:01: circular replacing clause 11.6 (floor 65%) was wrongly 'overridden' by clause 11.2 (75%)
    r112 = chunk("REG", 1, "2019-07-01", "11.2 minimum attendance of 75%", section="11.2")
    r116 = chunk("REG", 1, "2019-07-01", "11.6 attendance below 60% after relaxation", section="11.6")
    circ = chunk("CIRC-FLOOR", 2, "2026-09-01", "In supersession of 11.6, attendance below 65% after relaxation",
                 supersedes="REG#11.6")
    # Input order shuffled on purpose (11.6 before 11.2) so the result cannot depend on order.
    out = resolve([r116, r112, circ], "2026-10-06", None, "minimum attendance after relaxation")
    # (doc_id, section) pairs of everything applicable. "1" is the chunk() default section, used by the circular.
    ids = [(c["doc_id"], c["section"]) for c in out["applicable"]]
    assert ("CIRC-FLOOR", "1") in ids and ("REG", "11.6") not in ids and ("REG", "11.2") in ids
    assert out["overridden"] == []
