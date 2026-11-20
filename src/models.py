"""
Pydantic data models for Coback Compliance Analysis (NIS2 / BSIG).
Strictly separates:
- Target legal requirements (Soll)
- Actual company evidence (Ist)
- Compliance state (met | open | evidence_missing)
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ComplianceState(str, Enum):
    MET = "met"
    OPEN = "open"  # Confirmed gap / shortfall backed by reviewed evidence
    EVIDENCE_MISSING = "evidence_missing"  # Unresolved, silent, or missing operational proof


class EvidenceItem(BaseModel):
    source_id: str = Field(..., description="Document ID or file path")
    document_title: str
    version: Optional[str] = None
    date: Optional[str] = None
    status: Optional[str] = None
    exact_passage: str = Field(..., description="Exact verbatim quote from the evidence")
    location: str = Field(..., description="Line number, table row, or JSON path")
    demonstrates: str = Field(..., description="What this evidence actually demonstrates")


class SupportedGap(BaseModel):
    duty_id: str
    duty_title: str
    shortfall_description: str
    basis_of_finding: str
    evidence_citation: EvidenceItem


class EvidenceRequest(BaseModel):
    duty_id: str
    duty_title: str
    sources_reviewed: List[str]
    missing_fact: str
    focused_question: str


class DutyComplianceResult(BaseModel):
    duty_id: str
    statutory_ref: str
    duty_title: str
    state: ComplianceState
    reason: str
    supported_aspects: List[str] = Field(default_factory=list)
    shortfall_or_missing_aspects: List[str] = Field(default_factory=list)
    available_evidence: List[EvidenceItem] = Field(default_factory=list)
    actionable_request: Optional[EvidenceRequest] = None


class ComplianceAssessmentReport(BaseModel):
    assessment_entity: str
    entity_id: str
    data_snapshot_date: str
    analysis_date: str
    total_duties_assessed: int
    results: List[DutyComplianceResult]
    supported_gaps: List[SupportedGap]
    evidence_requests: List[EvidenceRequest]
    sources_reviewed_summary: List[str]