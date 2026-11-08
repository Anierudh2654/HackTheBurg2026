"""Track-local copy of Track B's Doc 00 models and route contracts."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class B(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


Task = Literal["research", "review", "draft"]
Tri = Literal["true", "false", "unknown"]
NodeType = Literal["Provision", "Case", "Holding", "Court", "TransactionType", "ActorClass", "ProcessFact", "Standard", "Source", "Element"]
EdgeType = Literal["cites", "interprets", "follows", "distinguishes", "limits", "overrules", "superseded_by_statute", "applies_to", "binds", "satisfies", "published_by", "addresses", "next_version", "amends"]
Origin = Literal["registry", "llm_extracted", "human", "seed"]
DOC_ID_PATTERN = r"^sha256:[0-9a-f]{64}$"


class Span(B):
    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str | None = Field(default=None, max_length=500)
    pincite: str | None = None


class MatterFact(B):
    key: str
    value: Any = None
    status: Literal["known", "unknown", "conflicting"] = "unknown"
    spans: list[Span] = Field(default_factory=list)
    extracted_by: Origin = "llm_extracted"
    confidence: float | None = Field(default=None, ge=0, le=1)
    reported_date: date | None = None


class ScopeFrame(B):
    addressee_classes: list[str] = Field(default_factory=list)
    transaction_types: list[str] = Field(default_factory=list)
    applies_when: dict[str, Any] | None = None
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
    non_application: dict[str, Any] | None = None
    defined_terms: dict[str, Span | None] = Field(default_factory=dict)
    jurisdiction: str = "US-DE"
    valid_from: date
    valid_to: date | None = None
    source_spans: list[Span] = Field(default_factory=list)
    audited: bool = False


class Node(B):
    node_id: str
    node_type: NodeType
    label: str
    props: dict[str, Any] = Field(default_factory=dict)
    scope_frame: ScopeFrame | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    known_from: date
    source_ids: list[str] = Field(default_factory=list)
    origin: Origin
    audited: bool = False


class Edge(B):
    edge_id: str
    src: str
    dst: str
    edge_type: EdgeType
    condition: dict[str, Any] | None = None
    props: dict[str, Any] = Field(default_factory=dict)
    valid_from: date | None = None
    valid_to: date | None = None
    known_from: date
    source_span: Span | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    origin: Origin
    audited: bool = False


class SourceRecord(B):
    source_id: str
    url: str
    registry_entry_id: str | None = None
    retrieved_at: datetime
    session_id: str | None = None
    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    media_type: str
    byte_length: int
    http_status: int | None = None
    fetch_method: Literal["api", "bulk", "adapter", "operator", "human"]
    retrieved_by: str
    expected_doc_type: str | None = None
    version_label: str | None = None
    canon_version: str | None = None


class TreatmentEvent(B):
    edge: Edge
    effective_date: date
    by_node_id: str


class ValidityResult(B):
    node_id: str
    as_of: date
    in_force: Tri
    good_law_unconditional: Literal["good", "superseded", "overruled", "limited", "unknown"]
    treatments: list[TreatmentEvent]
    reasons: list[str]


class RuleCandidate(B):
    node: Node
    score: float
    spans: list[Span] = Field(default_factory=list)


class ConditionStatus(B):
    condition_id: str
    label: str
    status: Literal["met", "unmet", "unknown"]
    fact_keys: list[str]
    spans: list[Span] = Field(default_factory=list)
    reason: str


class StandardOfReview(B):
    value: Literal["business_judgment", "entire_fairness", "unknown"]
    safe_harbor: Tri
    basis: list[str]
    readings: list[dict[str, Any]] = Field(default_factory=list)


class DocHit(B):
    doc_id: str
    source_id: str
    title: str
    doc_type: str
    doc_date: date | None
    score: float
    spans: list[Span]


class DocMeta(B):
    doc_id: str
    source: SourceRecord
    title: str | None
    doc_type: str | None
    doc_date: date | None
    canon_version: str
    char_length: int
    page_markers: list[dict[str, Any]]
    node_ids: list[str] = Field(default_factory=list)


class ScopeFrameReq(B):
    node_id: str
    as_of: date


class ScopeFrameResp(B):
    node_id: str
    frame: ScopeFrame | None


class EdgeList(B):
    items: list[Edge]


class ValidityReq(B):
    node_id: str
    as_of: date


class RuleCandidatesReq(B):
    query: str
    as_of: date
    top_k: int = 10
    node_types: list[NodeType] = Field(default_factory=lambda: ["Provision", "Holding"])
    facts: dict[str, MatterFact] = Field(default_factory=dict)


class RuleCandidatesResp(B):
    items: list[RuleCandidate]


class StandardReq(B):
    as_of: date
    facts: dict[str, MatterFact]


class StandardResp(B):
    standard: StandardOfReview
    conditions: list[ConditionStatus]


class DocSearchReq(B):
    query: str
    as_of: date
    top_k: int = 10
    registry_entry_ids: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)


class DocSearchResp(B):
    items: list[DocHit]


class RegisterDocReq(B):
    source: SourceRecord


class ExtractResp(B):
    job_id: str


class ExtractReq(B):
    doc_ids: list[str]
    fact_keys: list[str] = Field(default_factory=list)
    as_of: date


class JobStatus(B):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    result: list[MatterFact] | None = None
    error: str | None = None


class EdgeProbe(B):
    src: str
    dst: str
    edge_type: EdgeType


class ScoreEdgesReq(B):
    as_of: date
    edges: list[EdgeProbe]


class EdgeScore(B):
    src: str
    dst: str
    edge_type: EdgeType
    score_raw: float
    score_calibrated: float
    flag: bool


class ScoreEdgesResp(B):
    model_version: str
    scores: list[EdgeScore]


class PredictMissingReq(B):
    as_of: date
    anchor_node_ids: list[str]
    exclude_node_ids: list[str] = Field(default_factory=list)
    top_k: int = 10


class MissingPrediction(B):
    node_id: str
    score: float
    anchor_links: list[EdgeProbe]


class PredictMissingResp(B):
    model_version: str
    items: list[MissingPrediction]
