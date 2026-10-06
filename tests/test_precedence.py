"""Annex A precedence tests: HCL's own worked example (A.3) + our scope rules. No LLM, no DB."""
from app.precedence import batch_in_scope, pick_rule, programme_in_scope, resolve

CSE_2023 = {"programme": "B.Tech CSE", "batch_year": 2023}


def chunk(doc_id, level, eff_from, text, section="1", supersedes="", eff_to="", progs="ALL", batches="ALL", score=0.7):
    return {"doc_id": doc_id, "authority_level": level, "effective_from": eff_from, "effective_to": eff_to,
            "text": text, "section": section, "supersedes": supersedes, "scope_programmes": progs,
            "scope_batches": batches, "score": score}


# HCL Annex A.3: regulation 75% (L1, 2024-07-01), circular 80% supersedes clause (L2, 2026-08-01), FAQ 65% (L4, 2026-09-15)
REG = chunk("ACAD-REG-2024", 1, "2024-07-01", "7.2 Minimum attendance shall be 75% of classes.", section="7.2")
CIRC = chunk("ACAD-2026-08", 2, "2026-08-01", "Minimum attendance shall be 80% of classes.", supersedes="ACAD-REG-2024#7.2")
FAQ = chunk("DEPT-FAQ", 4, "2026-09-15", "Q1 65% attendance is enough.", section="Q1")
Q = "What is the minimum attendance requirement?"


def test_worked_example_circular_wins_and_faq_conflict_noted():
    out = resolve([REG, CIRC, FAQ], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-2026-08"]
    assert [c["doc_id"] for c in out["superseded"]] == ["ACAD-REG-2024"]          # step 2
    assert [c["doc_id"] for c in out["overridden"]] == ["DEPT-FAQ"]                # step 3
    assert any("step 3" in c for c in out["conflicts"])
    assert not out["unresolved"]


def test_before_circular_is_effective_regulation_applies_and_circular_is_upcoming():
    out = resolve([REG, CIRC], "2026-07-15", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-REG-2024"]
    assert [c["doc_id"] for c in out["excluded_future"]] == ["ACAD-2026-08"]
    assert any(c.startswith("upcoming") for c in out["conflicts"])


def test_level3_cannot_supersede_even_if_it_says_so():
    notice = chunk("DEPT-NOTICE", 3, "2026-09-01", "Attendance minimum is 70%.", supersedes="ACAD-REG-2024#7.2")
    out = resolve([REG, notice], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-REG-2024"]           # authority, not supersession
    assert out["overridden"][0]["doc_id"] == "DEPT-NOTICE"


def test_same_authority_later_date_wins():
    old = chunk("CIRC-A", 2, "2025-01-01", "attendance minimum 70%")
    new = chunk("CIRC-B", 2, "2026-01-01", "attendance minimum 72%")
    out = resolve([old, new], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["CIRC-B"]
    assert any("step 4" in c for c in out["conflicts"])


def test_same_authority_same_date_is_unresolved():
    a = chunk("CIRC-A", 2, "2026-01-01", "attendance minimum 70%")
    b = chunk("CIRC-B", 2, "2026-01-01", "attendance minimum 72%")
    out = resolve([a, b], "2026-10-06", None, Q)
    assert out["unresolved"]


def test_level5_never_overrides():
    forum = chunk("FORUM", 5, "2026-09-30", "attendance minimum is 50%, trust me")
    out = resolve([REG, forum], "2026-10-06", None, Q)
    assert [c["doc_id"] for c in out["applicable"]] == ["ACAD-REG-2024"]
    assert [c["doc_id"] for c in out["informational"]] == ["FORUM"]


def test_scope_filters_phd_docs_for_btech_student():
    phd = chunk("PHD-ORD", 1, "2022-07-01", "Ph.D. attendance 75%", progs="Ph.D. only")
    out = resolve([phd], "2026-10-06", CSE_2023, Q)
    assert out["applicable"] == [] and out["out_of_scope"][0]["doc_id"] == "PHD-ORD"


def test_programme_scope_matching():
    assert programme_in_scope("ALL", "B.Tech CSE")
    assert programme_in_scope("B.Tech", "B.Tech CSE")
    assert programme_in_scope("B.Tech (all branches)", "B.Tech ECE")
    assert programme_in_scope("B.Tech CSE", "B.Tech CSE")
    assert not programme_in_scope("B.Tech ECE", "B.Tech CSE")
    assert not programme_in_scope("Ph.D. only", "B.Tech CSE")
    assert programme_in_scope("B.Tech and B.Arch first semester", "B.Tech CSE")


def test_batch_scope_matching():
    assert batch_in_scope("ALL", 2023)
    assert batch_in_scope("2023+", 2024) and not batch_in_scope("2023+", 2022)
    assert batch_in_scope("Admitted 2019-20 onwards", 2023)
    assert batch_in_scope("Batches 2020-21 to 2023-24", 2023) and not batch_in_scope("Batches 2020-21 to 2023-24", 2024)
    assert batch_in_scope("2019-2022", 2021) and not batch_in_scope("2019-2022", 2023)
    assert not batch_in_scope("Admitted 2025-26", 2023)


# rule_registry rows carry authority_level + doc_supersedes so no DB is needed
def rule(rule_id, value, eff, doc, level, sup="", section="11.2", progs="B.Tech"):
    return {"rule_id": rule_id, "parameter": "min_attendance_pct", "operator": ">=", "value": value,
            "scope_programmes": progs, "scope_batches": "ALL", "effective_from": eff, "effective_to": "",
            "source_doc_id": doc, "source_section": section, "authority_level": level, "doc_supersedes": sup}


RULES = [rule("ATT-MIN-01", "75", "2019-07-01", "NSUT-BTECH-REG-2019", 1),
         rule("ATT-MIN-02", "80", "2026-08-01", "SYN-CIRC-ATT-2026", 2, sup="NSUT-BTECH-REG-2019#11.2", section="1"),
         rule("ATT-MIN-03", "65", "2026-09-15", "SYN-FAQ-ATT-2026", 4, section="Q1", progs="B.Tech CSE")]


def test_pick_rule_after_circular():
    out = pick_rule(RULES, "2026-10-06", CSE_2023)
    assert out["rule"]["rule_id"] == "ATT-MIN-02" and out["rule"]["value"] == "80"
    assert "supersedes" in out["decision"] and any("ATT-MIN-03" in c for c in out["conflicts"])


def test_pick_rule_before_circular():
    out = pick_rule(RULES, "2026-07-15", CSE_2023)
    assert out["rule"]["rule_id"] == "ATT-MIN-01"
    assert out["upcoming"] and "ATT-MIN-02" in out["upcoming"][0]


def test_pick_rule_ece_student_never_sees_cse_faq():
    out = pick_rule(RULES, "2026-10-06", {"programme": "B.Tech ECE", "batch_year": 2024})
    assert out["rule"]["rule_id"] == "ATT-MIN-02" and not out["conflicts"]


def test_superseding_circular_is_not_overridden_by_other_clauses_of_the_same_regulation():
    # found live 13:01: circular replacing clause 11.6 (floor 65%) was wrongly 'overridden' by clause 11.2 (75%)
    r112 = chunk("REG", 1, "2019-07-01", "11.2 minimum attendance of 75%", section="11.2")
    r116 = chunk("REG", 1, "2019-07-01", "11.6 attendance below 60% after relaxation", section="11.6")
    circ = chunk("CIRC-FLOOR", 2, "2026-09-01", "In supersession of 11.6, attendance below 65% after relaxation",
                 supersedes="REG#11.6")
    out = resolve([r116, r112, circ], "2026-10-06", None, "minimum attendance after relaxation")
    ids = [(c["doc_id"], c["section"]) for c in out["applicable"]]
    assert ("CIRC-FLOOR", "1") in ids and ("REG", "11.6") not in ids and ("REG", "11.2") in ids
    assert out["overridden"] == []
