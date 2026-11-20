"""Pydantic data models for COBACK regulatory compliance gap analysis."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ComplianceState(str, Enum):
    MET = "met"
    OPEN = "open"
    EVIDENCE_MISSING = "evidence_missing"


class ComponentStatus(str, Enum):
    SUPPORTED = "supported"
    CONFIRMED_SHORTFALL = "confirmed_shortfall"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING = "conflicting_evidence"


class EvidenceCitation(BaseModel):
    source_id: str
    document_title: str
    file_path: str
    version: Optional[str] = None
    date: Optional[str] = None
    status: Optional[str] = None
    exact_passage: str
    location: str
    demonstrates: str
    retrieval_score: Optional[float] = None


class DutyComponent(BaseModel):
    component_id: str
    name: str
    clause_text: str
    status: ComponentStatus
    rationale: str
    citations: List[EvidenceCitation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ExclusionLogItem(BaseModel):
    source_id: str
    file_path: str
    disposition: str
    reason: str


class EvidenceRequest(BaseModel):
    duty_id: str
    duty_title: str
    sources_reviewed: List[str] = Field(default_factory=list)
    missing_fact: str
    focused_question: str


class DutyComplianceResult(BaseModel):
    duty_id: str
    statutory_ref: str
    duty_title: str
    state: ComplianceState
    reason: str
    components: List[DutyComponent] = Field(default_factory=list)
    exclusion_log: List[ExclusionLogItem] = Field(default_factory=list)
    actionable_request: Optional[EvidenceRequest] = None

    @property
    def available_evidence(self) -> List[EvidenceCitation]:
        return [cit for comp in self.components for cit in comp.citations]


class ComplianceAssessmentReport(BaseModel):
    assessment_entity: str
    entity_id: str
    entity_code: str
    as_of_date: str
    analysis_date: str
    evaluation_mode: str
    total_duties_assessed: int
    results: List[DutyComplianceResult] = Field(default_factory=list)
    supported_gaps: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_requests: List[EvidenceRequest] = Field(default_factory=list)
    sources_reviewed_summary: List[str] = Field(default_factory=list)