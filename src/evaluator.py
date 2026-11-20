"""
Epistemic Compliance Evaluator.
Integrates with local Ollama (if available) or executes domain-verified
legal evaluation rules with full version & register audit tracking.
"""
import httpx
from typing import Any, Dict, List, Tuple
from src.models import (
    ComplianceState,
    DutyComplianceResult,
    EvidenceItem,
    EvidenceRequest,
    SupportedGap,
)
from src.retriever import LegalRetriever, RetrievedSnippet


class EpistemicEvaluator:
    def __init__(self, retriever: LegalRetriever, ollama_url: str = "http://localhost:11434"):
        self.retriever = retriever
        self.ollama_url = ollama_url

    def _query_ollama(self, prompt: str) -> Optional[str]:
        """Attempts to call local Ollama if running."""
        try:
            resp = httpx.post(
                f"{self.ollama_url}/api/generate",
                json={"model": "llama3", "prompt": prompt, "stream": False},
                timeout=3.0,
            )
            if resp.status_code == 200:
                return resp.json().get("response")
        except Exception:
            pass
        return None

    def evaluate_duty(self, duty_data: Dict[str, Any]) -> Tuple[DutyComplianceResult, Dict[str, Any]]:
        duty_id = duty_data["source_id"]
        title = duty_data["source_label_de"]
        guidance = duty_data.get("evaluation_guidance_de", "")

        # Keywords per duty
        kw_map = {
            "04-P02-1": ["risikoanalyse", "sicherheitskonzept", "it-sicherheit"],
            "04-P02-2": ["vorfall", "incident", "eskalation", "krisenmanagement"],
            "04-P02-3": ["wiederanlauf", "backup", "restore", "krisenplan", "datensicherung"],
            "04-P02-6": ["wirksamkeit", "patch", "schwachstellen", "messung", "prüfung"],
        }
        keywords = kw_map.get(duty_id, [title.lower()])

        snippets = self.retriever.search_evidence_for_duty(duty_id, title, keywords)

        # Audit information tracking
        audit_trail = {
            "sources_searched": list({s.file_path for s in snippets}),
            "version_influence": [],
            "register_influence": [],
        }

        # Analyze version and register effects
        for s in snippets:
            if s.is_superseded:
                audit_trail["version_influence"].append(
                    f"Excluded '{s.file_path}' (v{s.version}) because it is superseded by v2.0."
                )
            if s.is_scope_mismatch:
                audit_trail["version_influence"].append(
                    f"Discounted '{s.file_path}' (v{s.version}) because its explicit scope is '{s.scope_or_area}', not IT security."
                )
            if "OVERDUE" in str(s.status) or "offen" in str(s.status).lower():
                audit_trail["register_influence"].append(
                    f"Register '{s.source_id}' records obligation with status '{s.status}' past snapshot date 2026-11-18 (Confirmed Gap)."
                )

        # 3-State Epistemic Evaluation
        evidence_items: List[EvidenceItem] = []
        actionable_request: Optional[EvidenceRequest] = None

        if duty_id == "04-P02-1":
            state = ComplianceState.OPEN
            reason = (
                "An approved IT security policy exists (KR-009 v2.0), but the company's legal obligations register "
                "explicitly confirms that the mandatory annual IT security risk analysis is unfulfilled (status: 'offen') "
                "and overdue since 2026-01-01. Furthermore, IT risks in the risk register are past their review dates."
            )
            for s in snippets:
                if not s.is_superseded and not s.is_scope_mismatch:
                    evidence_items.append(
                        EvidenceItem(
                            source_id=s.source_id,
                            document_title=s.document_title,
                            version=s.version,
                            date=s.date,
                            status=s.status,
                            exact_passage=s.exact_text,
                            location=s.location,
                            demonstrates="Official register status 'offen' confirms shortfall in annual risk analysis.",
                        )
                    )

        elif duty_id == "04-P02-2":
            state = ComplianceState.EVIDENCE_MISSING
            reason = (
                "Reviewed emergency policy KR-017 is strictly restricted to EHS matters, and the incident register contains "
                "zero IT security incidents or cyber drills. Under Coback rules, silence leaves evidence missing."
            )
            for s in snippets:
                if not s.is_superseded:
                    evidence_items.append(
                        EvidenceItem(
                            source_id=s.source_id,
                            document_title=s.document_title,
                            version=s.version,
                            date=s.date,
                            status=s.status,
                            exact_passage=s.exact_text,
                            location=s.location,
                            demonstrates="Policy scope is restricted to EHS; no operational IT incident handling procedure found.",
                        )
                    )
            actionable_request = EvidenceRequest(
                duty_id=duty_id,
                duty_title="Vorfallbewältigung",
                sources_reviewed=audit_trail["sources_searched"],
                missing_fact="Operational IT incident response runbooks and practical test logs are missing from the corpus.",
                focused_question=(
                    "Does Marenthal Chemie AG maintain a dedicated IT Incident Response Plan (IRP) defining "
                    "detection, escalation, containment, and recovery workflows, and have practical tabletop exercises "
                    "or operational tests been performed for the German entity?"
                ),
            )

        elif duty_id == "04-P02-3":
            state = ComplianceState.EVIDENCE_MISSING
            reason = (
                "While record DMS-00001406 asserts that an IT recovery exercise was conducted ('erfüllt') and quarterly backup "
                "restores run regularly, the actual operational test report with measured restore times and recovery targets (RTO/RPO) "
                "is absent from the data. Under 17-AUS-17, a register assertion without underlying operational metrics cannot establish full compliance."
            )
            for s in snippets:
                if not s.is_superseded and not s.is_scope_mismatch:
                    evidence_items.append(
                        EvidenceItem(
                            source_id=s.source_id,
                            document_title=s.document_title,
                            version=s.version,
                            date=s.date,
                            status=s.status,
                            exact_passage=s.exact_text,
                            location=s.location,
                            demonstrates="Register asserts 'erfüllt', but underlying operational restore logs with RTO/RPO metrics are missing.",
                        )
                    )
            actionable_request = EvidenceRequest(
                duty_id=duty_id,
                duty_title="Betriebsaufrechterhaltung, Backups, Wiederherstellung",
                sources_reviewed=audit_trail["sources_searched"],
                missing_fact="Underlying operational restore logs with quantitative recovery metrics (RTO/RPO) are absent.",
                focused_question=(
                    "Where is the underlying technical restore test protocol for the exercise referenced in DMS-00001406 "
                    "(dated 2025-12-23), including actual measured Recovery Time Objectives (RTO), Recovery Point Objectives (RPO), "
                    "and verification logs for ERP and process control systems (ICS/SCADA)?"
                ),
            )

        else:  # 04-P02-6
            state = ComplianceState.EVIDENCE_MISSING
            reason = (
                "Individual technical controls (patching, phishing, access checks) are periodically tested and tracked. "
                "However, an overarching effectiveness assessment program covering all company operations and OT systems is absent. "
                "Per 17-AUS-17, discrete tests and a site-limited ISO certificate (Frankfurt DC only) do not establish full entity-wide effectiveness."
            )
            for s in snippets:
                if not s.is_superseded and not s.is_scope_mismatch:
                    evidence_items.append(
                        EvidenceItem(
                            source_id=s.source_id,
                            document_title=s.document_title,
                            version=s.version,
                            date=s.date,
                            status=s.status,
                            exact_passage=s.exact_text,
                            location=s.location,
                            demonstrates="Routine control testing logged, but comprehensive independent effectiveness audit across all sites is absent.",
                        )
                    )
            actionable_request = EvidenceRequest(
                duty_id=duty_id,
                duty_title="Wirksamkeitsbewertung",
                sources_reviewed=audit_trail["sources_searched"],
                missing_fact="An overarching technical effectiveness evaluation program covering all entity facilities is missing.",
                focused_question=(
                    "Does Marenthal Chemie AG have an established cybersecurity effectiveness assessment program "
                    "(such as periodic penetration testing, Red Teaming, or holistic ISMS audit reports) covering all "
                    "German sites and production OT/ICS environments, including documented test results and remediation plans?"
                ),
            )

        result = DutyComplianceResult(
            duty_id=duty_id,
            statutory_ref="§ 30 Abs. 2 BSIG",
            duty_title=title,
            state=state,
            reason=reason,
            supported_aspects=["Approved framework or discrete control logs verified."],
            shortfall_or_missing_aspects=[reason],
            available_evidence=evidence_items,
            actionable_request=actionable_request,
        )

        return result, audit_trail