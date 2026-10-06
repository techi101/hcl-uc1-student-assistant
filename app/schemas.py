"""Pydantic shapes for the HCL API contract (Section 6). Field names are fixed by HCL — do not rename."""
# WHAT THIS FILE IS: the exact shape of every request and response, as HCL fixed it in Section 6.
# PYDANTIC = a library where you describe data as a class with typed fields. It then checks incoming data
# (wrong type or missing field -> HTTP status 422 = "invalid data") and converts values where it can ("2" -> 2).
# FastAPI also uses these classes to build the docs page at /docs.
# Real example: POST /ask body {"question": "What is my CGPA?", "as_of_date": "2026-10-06"} becomes an AskRequest,
# and the reply must fit AskResponse: {"trace_id": "3f9a1c2b", "answer": "...", "answer_type": "calculated", ...}.
# date = a calendar date type. Any = "any type allowed". Literal = "only these exact values allowed".
from datetime import date
from typing import Any, Literal

# BaseModel = the parent class every shape inherits from. Field = adds limits like min_length or ge/le.
from pydantic import BaseModel, Field

# The only 6 answer types HCL allows. Any other value would fail the response check.
# retrieved_fact = from a document; calculated = from a code tool; not_found = not in sources;
# clarification_needed = we must ask back (e.g. which course); refused = not allowed (another student's data);
# conflict_flagged = sources disagree and the precedence rules cannot settle it.
AnswerType = Literal["retrieved_fact", "calculated", "not_found",
                     "clarification_needed", "refused", "conflict_flagged"]


# ---------- request body of POST /ask ----------
# IN: {"question": "...", "as_of_date": "YYYY-MM-DD" or missing}
# question must be 1 to 2000 characters (empty or huge text -> 422). as_of_date lets judges ask
# "what was the rule on 2025-01-01?"; if missing, the graph uses today's date.
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of_date: date | None = None              # YYYY-MM-DD; None -> today


# ---------- one citation inside an answer ----------
# Points to the exact document part the answer came from.
# Example: {"doc_id": "SYN-CIRC-ATT-2026", "title": "Attendance circular", "section": "2", "page": 1,
#           "version": "1.0", "effective_from": "2026-08-01"}. "| None = None" means the field is optional.
class Citation(BaseModel):
    doc_id: str
    title: str
    section: str | None = None
    page: int | None = None
    version: str | None = None
    effective_from: str | None = None


# ---------- one code tool call shown in the answer ----------
# Example: {"tool": "get_attendance", "input": {"course_code": "CS201"}, "output": {"attendance_pct": 72.5}}
# output may be a dict, a list or nothing, because different tools return different shapes.
class ToolCall(BaseModel):
    tool: str
    input: dict[str, Any] = {}
    output: dict[str, Any] | list[Any] | None = None


# ---------- one rule from the rule_registry that the answer used ----------
# Example: {"rule_id": "ATT-MIN-01", "value": "75", "source_doc_id": "NSUT-BTECH-REG-2019"}
# value is text so any rule (a percent, a count, a yes/no) fits the same field.
class AppliedRule(BaseModel):
    rule_id: str
    value: str
    source_doc_id: str


# ---------- full response body of POST /ask ----------
# Only trace_id, answer, answer_type and as_of_date must always be set. Lists default to empty,
# so a refused answer can simply leave citations and tools empty.
class AskResponse(BaseModel):
    trace_id: str
    answer: str
    answer_type: AnswerType
    citations: list[Citation] = []
    tools_invoked: list[ToolCall] = []
    applied_rules: list[AppliedRule] = []
    conflicts_detected: list[str] = []
    explanation: str = ""
    as_of_date: str


# ---------- response body of POST /ingest ----------
# Example: {"doc_id": "SYN-CIRC-ATT-2026", "chunks_indexed": 3, "status": "indexed"}
class IngestResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    status: str


# Annex B fields = metadata JSON sent with POST /ingest.
# LENIENT on purpose: judges upload unseen docs live; a 422 on a slightly different value
# (e.g. doc_type "ordinance", authority_level "2", missing version) would fail the live test.
# Unknown values are kept as strings; only doc_id, title, authority_level, effective_from are required.
# Fields with "= something" have a default, so the judge may leave them out.
# authority_level 1 to 5: 1 = Regulations (strongest) ... 5 = unofficial (informational only). ge/le enforce 1..5.
# scope_programmes / scope_batches say who the document applies to; app/precedence.py reads them.
class SourceMeta(BaseModel):
    doc_id: str = Field(min_length=1)
    title: str
    issuer: str = ""
    authority_level: int = Field(ge=1, le=5)     # "2" is coerced to 2 by Pydantic
    doc_type: str = "unknown"
    version: str = ""
    effective_from: str                          # YYYY-MM-DD
    effective_to: str = ""
    supersedes: str = ""                         # "DOC-ID" or "DOC-ID#7.2", ';'-separated
    scope_programmes: str = "ALL"
    scope_batches: str = "ALL"
    provenance: str = ""
    retrieved_on: str = ""
    synthetic: str = "N"
