"""
Neuro-Symbolic Epistemic Compliance Evaluator.
Evaluates decomposed requirement clauses against retrieved evidence using:
1. Legal-area / domain alignment (prevents EHS, GDPR, or export-control rows from triggering IT gaps)
2. Temporal deadline verification against as_of_date
3. Structured obligations register vs. risk register semantics
4. Epistemic proof-level checks (policy existence vs. operational execution/metrics)
5. Pure deterministic state aggregation (met | open | evidence_missing)
"""
from datetime import date
import json
import os
import re
from typing import List, Optional
import httpx

from src.corpus import EntityContext
from src.duty_parser import ParsedDuty, RequirementClause
from src.models import (
    ComplianceState,
    ComponentStatus,
    DutyComplianceResult,
    DutyComponent,
    EvidenceCitation,
    EvidenceRequest,
    ExclusionLogItem,
)
from src.retriever import HybridRetriever, ScoredEvidence, extract_specific_stems


def parse_flexible_date(raw: Optional[str]) -> Optional[date]:
    """Parse ISO (YYYY-MM-DD) or German (DD.MM.YYYY) dates safely."""
    if not raw:
        return None
    cleaned = raw.strip()
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", cleaned)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            return None
    de_match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", cleaned)
    if de_match:
        try:
            return date(int(de_match.group(3)), int(de_match.group(2)), int(de_match.group(1)))
        except ValueError:
            return None
    return None


def aggregate_duty_state(components: List[DutyComponent]) -> ComplianceState:
    """Pure deterministic state aggregation per Coback rules."""
    if not components:
        return ComplianceState.EVIDENCE_MISSING
    if any(c.status == ComponentStatus.CONFIRMED_SHORTFALL for c in components):
        return ComplianceState.OPEN
    if all(c.status == ComponentStatus.SUPPORTED for c in components):
        return ComplianceState.MET
    return ComplianceState.EVIDENCE_MISSING


class EpistemicEvaluator:
    """Evaluates duties dynamically without duty-specific hardcoding."""

    OPEN_STATUS_TOKENS = ("offen", "open", "nicht erfüllt", "overdue", "überfällig", "failed", "unfulfilled")
    PARTIAL_STATUS_TOKENS = ("teilweise", "partial", "in bearbeitung", "in progress", "eingeschränkt")
    FULFILLED_STATUS_TOKENS = ("erfüllt", "wirksam", "effective", "fulfilled", "completed", "done", "abgeschlossen")

    NON_IT_LEGAL_AREAS = (
        "immissionsschutz",
        "störfallrecht",
        "anlagensicherheit",
        "brand- und explosionsschutz",
        "brandschutz",
        "umwelt",
        "arbeitsschutz",
        "datenschutz",
        "sanktionen",
        "exportkontrolle",
        "arbeitsrecht",
        "steuer",
        "chemikalienrecht",
    )

    def __init__(
        self,
        retriever: HybridRetriever,
        entity: EntityContext,
        as_of_date: str = "2026-11-18",
        use_llm: bool = False,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3",
    ):
        self.retriever = retriever
        self.entity = entity
        self.as_of_str = as_of_date
        self.as_of = date.fromisoformat(as_of_date)
        self.use_llm = use_llm
        self.ollama_url = os.environ.get("OLLAMA_URL", ollama_url)
        self.ollama_model = os.environ.get("OLLAMA_MODEL", ollama_model)
        self.mode_label = (
            "Hybrid Neural-Lexical + LLM Epistemic Engine"
            if use_llm
            else "Hybrid Multilingual Neural-Lexical + Symbolic Epistemic Engine"
        )

    def _is_domain_compatible(self, duty: ParsedDuty, hit: ScoredEvidence) -> bool:
        """Ensure register rows belong to the same legal/operational domain as the duty."""
        if duty.domain != "informationssicherheit":
            return True
        area = (
            hit.unit.structured_fields.get("Legal area")
            or hit.unit.structured_fields.get("Category")
            or hit.unit.scope_or_area
            or ""
        ).lower()
        basis = (
            hit.unit.structured_fields.get("Basis")
            or hit.unit.structured_fields.get("Legal basis")
            or ""
        ).lower()

        if any(it_kw in f"{area} {basis}" for it_kw in ("informationssicherheit", "it-sicherheit", "bsi", "nis2", "iso/iec 27001")):
            return True
        if area and any(non_it in area for non_it in self.NON_IT_LEGAL_AREAS):
            return False
        return True

    def evaluate_duty(self, duty: ParsedDuty) -> DutyComplianceResult:
        components: List[DutyComponent] = []
        exclusion_map: dict[str, ExclusionLogItem] = {}
        reviewed_sources: List[str] = []

        for clause in duty.clauses:
            candidates = self.retriever.search(clause.text, top_k=10)

            active_hits: List[ScoredEvidence] = []
            for hit in candidates:
                u = hit.unit
                if u.file_path not in reviewed_sources:
                    reviewed_sources.append(u.file_path)

                if not self._is_domain_compatible(duty, hit):
                    continue

                if u.is_superseded and (hit.score >= 0.05 or hit.stem_overlap >= 1):
                    exclusion_map[u.source_id] = ExclusionLogItem(
                        source_id=u.source_id,
                        file_path=u.file_path,
                        disposition="historical_only",
                        reason=(
                            f"Document {u.source_id} (v{u.version}) was superseded by {u.superseded_by} "
                            f"prior to assessment date {self.as_of_str}."
                        ),
                    )
                    continue

                if u.is_scope_restricted and (hit.score >= 0.25 or hit.stem_overlap >= 1):
                    exclusion_map[u.source_id] = ExclusionLogItem(
                        source_id=u.source_id,
                        file_path=u.file_path,
                        disposition="limited_support",
                        reason=u.scope_restriction_reason or f"Restricted scope on {u.source_id}.",
                    )

                active_hits.append(hit)

            comp = self._evaluate_clause(duty, clause, active_hits)
            components.append(comp)

        state = aggregate_duty_state(components)
        reason = self._synthesize_duty_reason(duty, state, components)
        actionable_request = (
            self._build_evidence_request(duty, components, reviewed_sources)
            if state == ComplianceState.EVIDENCE_MISSING
            else None
        )

        return DutyComplianceResult(
            duty_id=duty.duty_id,
            statutory_ref=duty.statutory_ref,
            duty_title=duty.title,
            state=state,
            reason=reason,
            components=components,
            exclusion_log=list(exclusion_map.values()),
            actionable_request=actionable_request,
        )

    def _is_relevant_hit(self, hit: ScoredEvidence) -> bool:
        if self.retriever.dense_enabled:
            return hit.score >= 0.34 or (hit.score >= 0.24 and hit.stem_overlap >= 1)
        return hit.score >= 0.14 and hit.stem_overlap >= 1

    def _evaluate_clause(
        self,
        duty: ParsedDuty,
        clause: RequirementClause,
        hits: List[ScoredEvidence],
    ) -> DutyComponent:
        relevant = [h for h in hits if self._is_relevant_hit(h)]
        in_scope = [h for h in relevant if not h.unit.is_scope_restricted]
        clause_stems = extract_specific_stems(clause.text)

        # 1. Check for Confirmed Shortfalls on domain-matched Legal Obligations Register rows
        shortfall_citations: List[EvidenceCitation] = []
        shortfall_reasons: List[str] = []

        for h in in_scope[:4]:
            u = h.unit
            if u.unit_type != "register_row":
                continue
            # Risk Register rows represent active risks, not statutory obligation shortfalls
            if "risk_register" in u.source_id.lower() or "risikoregister" in u.document_title.lower():
                continue

            subject_text = (
                u.structured_fields.get("Obligation")
                or u.structured_fields.get("Control")
                or u.exact_passage
            )
            subject_overlap = len(clause_stems & extract_specific_stems(subject_text))
            if subject_overlap == 0 and h.dense_score < 0.52:
                continue

            status_val = (u.status or "").lower()
            due_raw = (
                u.structured_fields.get("Next due")
                or u.structured_fields.get("Due date")
                or u.structured_fields.get("Fällig")
            )
            due_dt = parse_flexible_date(due_raw)
            is_overdue = due_dt is not None and due_dt < self.as_of

            if any(tok in status_val for tok in self.OPEN_STATUS_TOKENS):
                overdue_note = (
                    f" and overdue since {due_dt.isoformat()} (as of {self.as_of_str})"
                    if is_overdue
                    else ""
                )
                msg = (
                    f"Register {u.source_id} explicitly records '{u.exact_passage}' with status "
                    f"'{u.status}'{overdue_note}."
                )
                shortfall_reasons.append(msg)
                shortfall_citations.append(
                    self._to_citation(
                        h,
                        demonstrates=f"Confirmed shortfall: status '{u.status}'{overdue_note}.",
                    )
                )

        if shortfall_citations:
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus.CONFIRMED_SHORTFALL,
                rationale=" ".join(shortfall_reasons),
                citations=shortfall_citations,
                limitations=["Active obligations register entry confirms an unfulfilled requirement."],
            )

        # 2. Check for Cross-Source Contradictions or Expired Review Deadlines
        fulfilled_hits: List[ScoredEvidence] = []
        partial_or_expired_hits: List[ScoredEvidence] = []

        for h in in_scope[:5]:
            u = h.unit
            status_lower = (u.status or "").lower()
            text_lower = u.exact_passage.lower()
            due_raw = (
                u.structured_fields.get("Next due")
                or u.structured_fields.get("Next review")
                or u.structured_fields.get("Nächste Prüfung")
            )
            due_dt = parse_flexible_date(due_raw)

            if any(tok in status_lower for tok in self.PARTIAL_STATUS_TOKENS):
                partial_or_expired_hits.append(h)
            elif due_dt is not None and due_dt < self.as_of:
                partial_or_expired_hits.append(h)
            elif any(tok in status_lower or tok in text_lower for tok in self.FULFILLED_STATUS_TOKENS):
                fulfilled_hits.append(h)

        if fulfilled_hits and partial_or_expired_hits:
            f_unit = fulfilled_hits[0].unit
            p_unit = partial_or_expired_hits[0].unit
            f_label = f"{f_unit.source_id} ({f_unit.location})" if f_unit.source_id == p_unit.source_id else f_unit.source_id
            p_label = f"{p_unit.source_id} ({p_unit.location})" if f_unit.source_id == p_unit.source_id else p_unit.source_id
            cits = [
                self._to_citation(fulfilled_hits[0], "Asserts fulfillment or active control execution."),
                self._to_citation(
                    partial_or_expired_hits[0],
                    f"Reports qualified status ('{p_unit.status}') or expired review deadline.",
                ),
            ]
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus.CONFLICTING,
                rationale=(
                    f"Conflicting evidence between {f_label} and "
                    f"{p_label} (status: '{p_unit.status}')."
                ),
                citations=cits,
                limitations=["Contradictory status or overdue review date requires reconciliation."],
            )
        
        # 3. Check Silence / Out-of-Scope Only / Blank Twin Answer
        if not in_scope:
            restricted_cits = [
                self._to_citation(h, h.unit.scope_restriction_reason or "Scope-restricted source.")
                for h in relevant[:2]
            ]
            limitation_msg = (
                "Only scope-restricted sources matched; no in-scope IT/entity evidence found."
                if restricted_cits
                else "No matching evidence found in reviewed corpus (silence is not a confirmed gap)."
            )
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus.INSUFFICIENT_EVIDENCE,
                rationale=limitation_msg,
                citations=restricted_cits,
                limitations=[limitation_msg],
            )

        top_hit = in_scope[0]
        if top_hit.unit.unit_type == "twin_qa" and not top_hit.unit.structured_fields.get("answer"):
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus.INSUFFICIENT_EVIDENCE,
                rationale="Digital twin questionnaire entry is blank/unanswered; blank fields do not establish compliance or shortfall.",
                citations=[self._to_citation(top_hit, "Unanswered digital twin question.")],
                limitations=["Blank field requires follow-up clarification."],
            )

        # 4. Optional LLM Epistemic NLI Check (when --use-llm is enabled)
        if self.use_llm:
            llm_verdict = self._llm_verify_clause(clause, in_scope[:4])
            if llm_verdict is not None:
                return llm_verdict

        # 5. Epistemic Proof-Level Verification (Policy vs. Operational Execution & Entity Scope)
        has_operational_record = any(
            h.unit.unit_type == "register_row"
            and any(tok in (h.unit.status or "").lower() for tok in ("active", "aktiv", "wirksam", "erfüllt", "done"))
            for h in in_scope[:3]
        )
        has_quantitative_metrics = any(
            re.search(r"\b(rto|rpo|messwert|minutes|minuten|hours|stunden|\d+\s*%)\b", h.unit.text.lower())
            for h in in_scope[:3]
        )

        if clause.requires_operational_proof and not (has_operational_record and has_quantitative_metrics):
            cits = [
                self._to_citation(
                    h,
                    "Shows policy/control entry, but lacks underlying operational test logs or quantitative metrics.",
                )
                for h in in_scope[:2]
            ]
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus.INSUFFICIENT_EVIDENCE,
                rationale=(
                    f"Retrieved {in_scope[0].unit.source_id} provides partial documentary/control context, "
                    "but operational execution logs, effectiveness proof, or measured metrics (e.g., RTO/RPO or test reports) are missing."
                ),
                citations=cits,
                limitations=["Documentary policy or register assertion alone does not establish operational effectiveness."],
            )

        if clause.requires_entity_wide_scope and any(h.unit.is_scope_restricted for h in relevant[:3]):
            cits = [
                self._to_citation(h, "Site-limited certification or partial control scope.")
                for h in relevant[:2]
            ]
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus.INSUFFICIENT_EVIDENCE,
                rationale=(
                    f"Available evidence is restricted in scope and does not verify all facilities of {self.entity.entity_name}."
                ),
                citations=cits,
                limitations=["Entity-wide coverage across all operational sites is not established."],
            )

        return DutyComponent(
            component_id=clause.clause_id,
            name=clause.name,
            clause_text=clause.text,
            status=ComponentStatus.SUPPORTED,
            rationale=(
                f"Supported by active, in-scope source {top_hit.unit.source_id} "
                f"(hybrid relevance score: {top_hit.score:.2f})."
            ),
            citations=[
                self._to_citation(h, "Directly supports requirement clause.")
                for h in in_scope[:2]
            ],
            limitations=[],
        )

    def _llm_verify_clause(
        self,
        clause: RequirementClause,
        hits: List[ScoredEvidence],
    ) -> Optional[DutyComponent]:
        """Optional local Ollama verifier with strict citation ID grounding."""
        evidence_block = "\n\n".join(
            f"[{i+1}] source_id={h.unit.source_id} | type={h.unit.unit_type} | status={h.unit.status} | date={h.unit.date}\n"
            f"Passage: {h.unit.exact_passage}"
            for i, h in enumerate(hits)
        )
        prompt = (
            "You are a strict legal compliance auditor. Compare the statutory requirement clause against ONLY the provided evidence.\n"
            "Rules:\n"
            "- Return valid JSON with keys: status ('supported' | 'confirmed_shortfall' | 'insufficient_evidence' | 'conflicting_evidence'), rationale, cited_index (1-based int).\n"
            "- A policy document alone does NOT prove operational execution or testing.\n"
            "- Silence or missing operational logs MUST be 'insufficient_evidence', NEVER 'confirmed_shortfall'.\n"
            f"Requirement: {clause.text}\n\nEvidence:\n{evidence_block}\n"
        )
        try:
            resp = httpx.post(
                f"{self.ollama_url}/api/generate",
                json={"model": self.ollama_model, "prompt": prompt, "format": "json", "stream": False},
                timeout=8.0,
            )
            if resp.status_code != 200:
                return None
            parsed = json.loads(resp.json().get("response", "{}"))
            raw_status = parsed.get("status")
            if raw_status not in {s.value for s in ComponentStatus}:
                return None
            idx = max(0, min(len(hits) - 1, int(parsed.get("cited_index", 1)) - 1))
            chosen = hits[idx]
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus(raw_status),
                rationale=str(parsed.get("rationale", "")),
                citations=[self._to_citation(chosen, "Verified via LLM epistemic check.")],
                limitations=[],
            )
        except Exception:
            return None

    @staticmethod
    def _to_citation(hit: ScoredEvidence, demonstrates: str) -> EvidenceCitation:
        u = hit.unit
        return EvidenceCitation(
            source_id=u.source_id,
            document_title=u.document_title,
            file_path=u.file_path,
            version=u.version,
            date=u.date,
            status=u.status,
            exact_passage=u.exact_passage,
            location=u.location,
            demonstrates=demonstrates,
            retrieval_score=round(hit.score, 4),
        )

    @staticmethod
    def _synthesize_duty_reason(
        duty: ParsedDuty,
        state: ComplianceState,
        components: List[DutyComponent],
    ) -> str:
        supported = [c.name for c in components if c.status == ComponentStatus.SUPPORTED]
        shortfalls = [c for c in components if c.status == ComponentStatus.CONFIRMED_SHORTFALL]
        missing = [c for c in components if c.status in (ComponentStatus.INSUFFICIENT_EVIDENCE, ComponentStatus.CONFLICTING)]

        if state == ComplianceState.OPEN:
            prefix = f"Supported aspects ({', '.join(supported)}) exist, however " if supported else ""
            details = "; ".join(c.rationale for c in shortfalls)
            return f"{prefix}confirmed shortfall identified: {details}"

        if state == ComplianceState.MET:
            return f"All {len(components)} decomposed requirements for '{duty.title}' are supported by active, in-scope evidence."

        prefix = f"Supported aspects ({', '.join(supported)}) verified, but full compliance cannot yet be established: " if supported else ""
        details = "; ".join(f"{c.name}: {c.rationale}" for c in missing[:2])
        return f"{prefix}{details}"

    def _build_evidence_request(
        self,
        duty: ParsedDuty,
        components: List[DutyComponent],
        reviewed_sources: List[str],
    ) -> EvidenceRequest:
        unresolved = [
            c for c in components
            if c.status in (ComponentStatus.INSUFFICIENT_EVIDENCE, ComponentStatus.CONFLICTING)
        ]
        missing_summary = "; ".join(f"{c.name} ({c.rationale})" for c in unresolved)
        clause_topics = ", ".join(c.name for c in unresolved)
        cited_ids = sorted({cit.source_id for c in unresolved for cit in c.citations})
        ref_note = f" (reconciling {', '.join(cited_ids)})" if cited_ids else ""

        question = (
            f"For {self.entity.entity_name} under {duty.statutory_ref} ({duty.title}), please provide verifiable "
            f"operational records, test logs, or scope-complete documentation covering: {clause_topics}{ref_note}."
        )
        return EvidenceRequest(
            duty_id=duty.duty_id,
            duty_title=duty.title,
            sources_reviewed=reviewed_sources,
            missing_fact=missing_summary,
            focused_question=question,
        )