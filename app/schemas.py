"""Pydantic shapes for the HCL API contract (Section 6). Field names are fixed by HCL — do not rename."""
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

AnswerType = Literal["retrieved_fact", "calculated", "not_found",
                     "clarification_needed", "refused", "conflict_flagged"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of_date: date | None = None              # YYYY-MM-DD; None -> today


class Citation(BaseModel):
    doc_id: str
    title: str
    section: str | None = None
    page: int | None = None
    version: str | None = None
    effective_from: str | None = None


class ToolCall(BaseModel):
    tool: str
    input: dict[str, Any] = {}
    output: dict[str, Any] | list[Any] | None = None


class AppliedRule(BaseModel):
    rule_id: str
    value: str
    source_doc_id: str


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


class IngestResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    status: str


# Annex B fields = metadata JSON sent with POST /ingest
class SourceMeta(BaseModel):
    doc_id: str
    title: str
    issuer: str
    authority_level: int = Field(ge=1, le=5)
    doc_type: Literal["regulation", "circular", "notice", "faq", "handbook", "unofficial"]
    version: str = ""
    effective_from: str
    effective_to: str = ""
    supersedes: str = ""
    scope_programmes: str = "ALL"
    scope_batches: str = "ALL"
    provenance: str = ""
    retrieved_on: str = ""
    synthetic: Literal["Y", "N"] = "N"
