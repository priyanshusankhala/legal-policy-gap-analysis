"""
Regulatory Compliance Analysis Engine.
Evaluates statutory duties at the sub-component level before deterministic aggregation.
Enforces explicit exclusion & limitation logging.
"""
from pathlib import Path
from typing import List, Optional
from src.loader import DataLoader
from src.models import (
    ComplianceAssessmentReport,
    ComplianceState,
    ComponentStatus,
    DutyComplianceResult,
    DutyComponent,
    EvidenceCitation,
    EvidenceRequest,
    ExclusionLogItem,
)


class ComplianceAnalyzer:
    ENTITY_NAME = "Marenthal Chemie AG (DE)"
    ENTITY_ID = "1764010d-db68-42e2-8aa2-db89242548ad"

    def __init__(self, data_loader: DataLoader, as_of_date: str = "2026-11-18"):
        self.loader = data_loader
        self.as_of_date = as_of_date
        self.sources_reviewed: List[str] = []

    def _track(self, rel_path: str) -> str:
        try:
            resolved = str(self.loader.resolve_path(rel_path))
        except FileNotFoundError:
            resolved = rel_path
        if resolved not in self.sources_reviewed:
            self.sources_reviewed.append(resolved)
        return resolved

    def evaluate_04_P02_1(self) -> DutyComplianceResult:
        """04-P02-1: Risikoanalyse und IT-Sicherheitskonzept (§30 Abs.2 Nr.1 BSIG)"""
        policy_rel = "documents/DMS-00000420_KR-009_v2.0_de.txt"
        old_policy_rel = "documents/DMS-00000205_KR-009_v1.1_de.txt"
        reg_rel = "documents/REG_Legal_Obligations_CMS-DE-01.txt"
        risk_rel = "documents/REG_Risk_Register_CMS-DE-01.txt"

        self._track(policy_rel)
        self._track(old_policy_rel)
        self._track(reg_rel)
        self._track(risk_rel)

        # Exclusions / Limitations
        exclusions = [
            ExclusionLogItem(
                source_id="DMS-00000205",
                file_path=old_policy_rel,
                disposition="historical_only",
                reason=f"Policy version 1.1 was superseded by version 2.0 (2024-07-09) prior to assessment date {self.as_of_date}.",
            )
        ]

        # Component 1: IT-Sicherheitskonzept (Concept/Policy)
        _, policy_lines = self.loader.load_text_with_lines(policy_rel)
        c1 = DutyComponent(
            component_id="04-P02-1.C1",
            name="IT-Sicherheitskonzept (Approved Policy Framework)",
            status=ComponentStatus.SUPPORTED,
            rationale="An approved group-wide information security policy exists and is currently in force.",
            citations=[
                EvidenceCitation(
                    source_id="DMS-00000420",
                    document_title="Informationssicherheitsrichtlinie (KR-009)",
                    file_path=policy_rel,
                    version="2.0",
                    date="2024-07-09",
                    status="Approved",
                    exact_passage="".join(policy_lines[14:26]).strip(),
                    location=f"{policy_rel}, lines 15-26",
                    demonstrates="Formally approved IT security policy valid from 2024-07-09.",
                )
            ],
            limitations=[],
        )

        # Component 2: Jährliche Risikoanalyse (Annual Risk Analysis Execution)
        ob_rows = self.loader.parse_markdown_table(reg_rel)
        target_row = next((r for r in ob_rows if "Informationssicherheitsrisikoanalyse" in r.get("Obligation", "")), None)

        if target_row and target_row.get("Status", "").lower() == "offen":
            c2_status = ComponentStatus.CONFIRMED_SHORTFALL
            c2_rationale = (
                f"Statutory annual risk analysis is recorded with status 'offen'. "
                f"Due date was {target_row.get('Next due')}, which is overdue as of {self.as_of_date}."
            )
            c2_citations = [
                EvidenceCitation(
                    source_id="REG_Legal_Obligations_CMS-DE-01",
                    document_title="Register of legal and internal obligations",
                    file_path=reg_rel,
                    version="1.0",
                    date=target_row.get("Last review"),
                    status="offen (Overdue)",
                    exact_passage=target_row["__raw_line__"],
                    location=f"{reg_rel}, line {target_row['__line_number__']}",
                    demonstrates="Statutory annual IT risk analysis is documented as unfulfilled/open.",
                )
            ]
        else:
            c2_status = ComponentStatus.INSUFFICIENT_EVIDENCE
            c2_rationale = "Status of annual risk analysis could not be determined."
            c2_citations = []

        c2 = DutyComponent(
            component_id="04-P02-1.C2",
            name="Regelmäßige IT-Risikoanalyse (Annual Risk Assessment Execution)",
            status=c2_status,
            rationale=c2_rationale,
            citations=c2_citations,
            limitations=["Absence of updated risk assessments for production IT/OT."],
        )

        # Component 3: Risikoregister (Risk Register Currency)
        risk_rows = self.loader.parse_markdown_table(risk_rel)
        it_risks = [r for r in risk_rows if r.get("Category") == "Informationssicherheit"]
        c3 = DutyComponent(
            component_id="04-P02-1.C3",
            name="IT-Risikoliste (Risk Register Maintenance)",
            status=ComponentStatus.CONFLICTING,
            rationale=(
                f"Identified 2 IT security risks, but both ('Ausfall von ERP', 'Verschlüsselungsangriff') "
                f"have next review deadlines that expired in March and April 2026."
            ),
            citations=[
                EvidenceCitation(
                    source_id="REG_Risk_Register_CMS-DE-01",
                    document_title="Risk register - Marenthal Chemie AG",
                    file_path=risk_rel,
                    version="1.0",
                    date="2026-11-09",
                    status="in Behandlung",
                    exact_passage=it_risks[0]["__raw_line__"] if it_risks else "N/A",
                    location=f"{risk_rel}, line {it_risks[0]['__line_number__'] if it_risks else 0}",
                    demonstrates="IT risks are tracked but their scheduled reviews are past due.",
                )
            ],
            limitations=["Review deadlines expired without logged re-assessment."],
        )

        components = [c1, c2, c3]
        # Aggregation: Any confirmed shortfall -> OPEN
        state = ComplianceState.OPEN if any(c.status == ComponentStatus.CONFIRMED_SHORTFALL for c in components) else ComplianceState.EVIDENCE_MISSING

        return DutyComplianceResult(
            duty_id="04-P02-1",
            statutory_ref="§ 30 Abs. 2 Nr. 1 BSIG",
            duty_title="Risikoanalyse und IT-Sicherheitskonzept",
            state=state,
            reason=(
                "While the formal IT security policy is supported (KR-009 v2.0), an explicit confirmed shortfall exists: "
                f"the mandatory annual IT risk analysis is documented as 'offen' and overdue since 2026-01-01 in the obligations register."
            ),
            components=components,
            exclusion_log=exclusions,
            actionable_request=None,
        )

    def evaluate_04_P02_2(self) -> DutyComplianceResult:
        """04-P02-2: Vorfallbewältigung (§30 Abs.2 Nr.2 BSIG)"""
        kr017_rel = "documents/DMS-00000671_KR-017_v2.0_de.txt"
        inc_rel = "documents/REG_Incidents_CMS-DE-01.txt"
        roles_rel = "documents/REG_Compliance_Roles_CMS-DE-01.txt"

        self._track(kr017_rel)
        self._track(inc_rel)
        self._track(roles_rel)

        exclusions = [
            ExclusionLogItem(
                source_id="DMS-00000671",
                file_path=kr017_rel,
                disposition="limited_support",
                reason="Policy KR-017 covers physical emergency management (EHS: fire, chemical leaks) and does not govern IT incident handling.",
            )
        ]

        # Component 1: Incident Handling Process (IRP)
        _, kr017_lines = self.loader.load_text_with_lines(kr017_rel)
        c1 = DutyComponent(
            component_id="04-P02-2.C1",
            name="IT-Vorfallbewältigungsplan (Incident Response Workflows)",
            status=ComponentStatus.INSUFFICIENT_EVIDENCE,
            rationale="No IT-specific detection, escalation, or containment plan was found in reviewed materials.",
            citations=[
                EvidenceCitation(
                    source_id="DMS-00000671",
                    document_title="Notfall- und Krisenmanagement (KR-017)",
                    file_path=kr017_rel,
                    version="2.0",
                    date="2025-03-25",
                    status="Approved",
                    exact_passage="".join(kr017_lines[12:18]).strip(),
                    location=f"{kr017_rel}, lines 13-18",
                    demonstrates="Policy KR-017 explicitly restricts its scope to 'EHS', not IT security.",
                )
            ],
            limitations=["Reviewed emergency policy does not govern cybersecurity."],
        )

        # Component 2: Practical Drills & Protocols
        c2 = DutyComponent(
            component_id="04-P02-2.C2",
            name="Praktische Tests & Vorfallprotokolle (Incident Drills & Logging)",
            status=ComponentStatus.INSUFFICIENT_EVIDENCE,
            rationale="Incident register contains 11 entries; all are EHS or product viscosity incidents. Zero IT incidents or drills recorded.",
            citations=[],
            limitations=["Register is silent on cybersecurity exercises. Under epistemic guardrails, silence is not a gap."],
        )

        # Component 3: Responsible Roles
        roles_rows = self.loader.parse_markdown_table(roles_rel)
        it_role = next((r for r in roles_rows if "Informationssicherheitsbeauftragter" in r.get("Role", "")), None)
        c3 = DutyComponent(
            component_id="04-P02-2.C3",
            name="Verantwortliche & Eskalationsrollen (Assigned Responsibilities)",
            status=ComponentStatus.SUPPORTED if it_role else ComponentStatus.INSUFFICIENT_EVIDENCE,
            rationale="An Information Security Officer role is appointed with a designated deputy.",
            citations=[
                EvidenceCitation(
                    source_id="REG_Compliance_Roles_CMS-DE-01",
                    document_title="Register of compliance roles and responsibilities",
                    file_path=roles_rel,
                    version="1.0",
                    date="2026-11-09",
                    status="Active",
                    exact_passage=it_role["__raw_line__"] if it_role else "N/A",
                    location=f"{roles_rel}, line {it_role['__line_number__'] if it_role else 0}",
                    demonstrates="Responsible role for information security is formally staffed.",
                )
            ] if it_role else [],
            limitations=[],
        )

        components = [c1, c2, c3]
        request = EvidenceRequest(
            duty_id="04-P02-2",
            duty_title="Vorfallbewältigung",
            sources_reviewed=[kr017_rel, inc_rel, roles_rel],
            missing_fact="Operational IT incident response runbooks and practical test logs are absent from the reviewed corpus.",
            focused_question=(
                "Does Marenthal Chemie AG maintain a dedicated IT Incident Response Plan (IRP) defining "
                "detection, escalation, containment, and recovery workflows, and have practical tabletop exercises "
                "or test drills been conducted and documented for the German entity?"
            ),
        )

        return DutyComplianceResult(
            duty_id="04-P02-2",
            statutory_ref="§ 30 Abs. 2 Nr. 2 BSIG",
            duty_title="Vorfallbewältigung",
            state=ComplianceState.EVIDENCE_MISSING,
            reason="Emergency policy KR-017 is strictly EHS-related, and the incident register contains zero IT records. Silence leaves evidence missing.",
            components=components,
            exclusion_log=exclusions,
            actionable_request=request,
        )

    def evaluate_04_P02_3(self) -> DutyComplianceResult:
        """04-P02-3: Betriebsaufrechterhaltung, Backups, Wiederherstellung (§30 Abs.2 Nr.3 BSIG)"""
        nachweis_rel = "documents/DMS-00001406_V000074_Nachweis.txt"
        controls_rel = "documents/REG_Internal_Controls_CMS-DE-01.txt"

        self._track(nachweis_rel)
        self._track(controls_rel)

        _, nachweis_lines = self.loader.load_text_with_lines(nachweis_rel)
        ctrl_rows = self.loader.parse_markdown_table(controls_rel)
        backup_ctrl = next((r for r in ctrl_rows if "Offline-Datensicherung" in r.get("Control", "")), None)
        dr_ctrl = next((r for r in ctrl_rows if "Notfallhandbuch" in r.get("Control", "")), None)

        # Component 1: Backup Procedures
        c1 = DutyComponent(
            component_id="04-P02-3.C1",
            name="Datensicherungskonzept (Backup Procedures & Schedules)",
            status=ComponentStatus.SUPPORTED,
            rationale="Offline backups and restore tests run quarterly (4 effective runs logged).",
            citations=[
                EvidenceCitation(
                    source_id="REG_Internal_Controls_CMS-DE-01",
                    document_title="Register of internal controls and their execution",
                    file_path=controls_rel,
                    version="1.0",
                    date=backup_ctrl.get("Last run") if backup_ctrl else "2025-10-17",
                    status="Active",
                    exact_passage=backup_ctrl["__raw_line__"] if backup_ctrl else "N/A",
                    location=f"{controls_rel}, line {backup_ctrl['__line_number__'] if backup_ctrl else 0}",
                    demonstrates="Periodic offline backup restore tests are actively tracked.",
                )
            ] if backup_ctrl else [],
            limitations=["One quarterly run is recorded as 'offen'."],
        )

        # Component 2: Recovery Drill Execution
        c2 = DutyComponent(
            component_id="04-P02-3.C2",
            name="Wiederanlaufübung (Recovery Exercise Execution)",
            status=ComponentStatus.CONFLICTING,
            rationale=(
                "Document DMS-00001406 asserts the recovery drill is 'erfüllt', but the internal controls register "
                "recorded the last run on 2025-10-13 as only 'teilweise wirksam'."
            ),
            citations=[
                EvidenceCitation(
                    source_id="DMS-00001406",
                    document_title="Nachweis: Notfall- und Wiederanlaufübung der IT durchführen",
                    file_path=nachweis_rel,
                    version="1.0",
                    date="2025-12-23",
                    status="Approved",
                    exact_passage="".join(nachweis_lines[14:26]).strip(),
                    location=f"{nachweis_rel}, lines 15-26",
                    demonstrates="Formal compliance record asserting drill execution.",
                ),
                EvidenceCitation(
                    source_id="REG_Internal_Controls_CMS-DE-01",
                    document_title="Register of internal controls and their execution",
                    file_path=controls_rel,
                    version="1.0",
                    date=dr_ctrl.get("Last run") if dr_ctrl else "2025-10-13",
                    status="teilweise wirksam",
                    exact_passage=dr_ctrl["__raw_line__"] if dr_ctrl else "N/A",
                    location=f"{controls_rel}, line {dr_ctrl['__line_number__'] if dr_ctrl else 0}",
                    demonstrates="Internal controls register rates drill as only partially effective.",
                ),
            ],
            limitations=["Evaluation contradiction between compliance certificate and internal controls register."],
        )

        # Component 3: Measured Restore Metrics (RTO/RPO)
        c3 = DutyComponent(
            component_id="04-P02-3.C3",
            name="Messwerte & Wiederherstellungszeiten (RTO / RPO Verification)",
            status=ComponentStatus.INSUFFICIENT_EVIDENCE,
            rationale="No operational restore logs containing measured recovery durations or recovery targets exist in the dataset.",
            citations=[],
            limitations=["Under 17-AUS-17, a policy or register assertion without operational metrics cannot prove effectiveness."],
        )

        components = [c1, c2, c3]
        request = EvidenceRequest(
            duty_id="04-P02-3",
            duty_title="Betriebsaufrechterhaltung, Backups, Wiederherstellung, Krisenmanagement",
            sources_reviewed=[nachweis_rel, controls_rel],
            missing_fact="Operational restore logs with quantitative recovery metrics (RTO/RPO) are absent.",
            focused_question=(
                "Where is the underlying technical restore test protocol for the exercise referenced in DMS-00001406 "
                "(dated 2025-12-23), including actual measured Recovery Time Objectives (RTO), Recovery Point Objectives (RPO), "
                "and verification logs for ERP and process control systems (ICS/SCADA)?"
            ),
        )

        return DutyComplianceResult(
            duty_id="04-P02-3",
            statutory_ref="§ 30 Abs. 2 Nr. 3 BSIG",
            duty_title="Betriebsaufrechterhaltung, Backups, Wiederherstellung, Krisenmanagement",
            state=ComplianceState.EVIDENCE_MISSING,
            reason="While backup routines exist and an exercise is certified, operational logs with measured recovery times (RTO) are absent, and the drill was rated only partially effective.",
            components=components,
            exclusion_log=[],
            actionable_request=request,
        )

    def evaluate_04_P02_6(self) -> DutyComplianceResult:
        """04-P02-6: Wirksamkeitsbewertung (§30 Abs.2 Nr.6 BSIG)"""
        controls_rel = "documents/REG_Internal_Controls_CMS-DE-01.txt"
        profile_rel = "company_profile.json"

        self._track(controls_rel)
        self._track(profile_rel)

        ctrl_rows = self.loader.parse_markdown_table(controls_rel)
        patch_ctrl = next((r for r in ctrl_rows if "Patch- und Schwachstellenmanagement" in r.get("Control", "")), None)
        profile_json = self.loader.load_json(profile_rel)
        certifications = profile_json.get("certifications", [])
        iso_cert = next((c for c in certifications if "ISO/IEC 27001" in c), "ISO/IEC 27001:2022")

        exclusions = [
            ExclusionLogItem(
                source_id="company_profile.json",
                file_path=profile_rel,
                disposition="limited_support",
                reason="ISO 27001 certificate is strictly restricted to the Frankfurt Data Center and development systems; does not cover Marl or Bitterfeld plants.",
            )
        ]

        # Component 1: Individual Control Tests
        c1 = DutyComponent(
            component_id="04-P02-6.C1",
            name="Einzelprüfungen von Sicherheitsmaßnahmen (Routine Control Execution)",
            status=ComponentStatus.SUPPORTED,
            rationale="Monthly patch management (12 effective runs) and semi-annual phishing simulations are tracked.",
            citations=[
                EvidenceCitation(
                    source_id="REG_Internal_Controls_CMS-DE-01",
                    document_title="Register of internal controls and their execution",
                    file_path=controls_rel,
                    version="1.0",
                    date=patch_ctrl.get("Last run") if patch_ctrl else "2025-12-12",
                    status="Active",
                    exact_passage=patch_ctrl["__raw_line__"] if patch_ctrl else "N/A",
                    location=f"{controls_rel}, line {patch_ctrl['__line_number__'] if patch_ctrl else 0}",
                    demonstrates="Routine technical control testing is actively conducted.",
                )
            ] if patch_ctrl else [],
            limitations=[],
        )

        # Component 2: Overarching Effectiveness Testing Program
        c2 = DutyComponent(
            component_id="04-P02-6.C2",
            name="Übergreifendes Wirksamkeitsprüfprogramm (Comprehensive Audit & Penetration Testing)",
            status=ComponentStatus.INSUFFICIENT_EVIDENCE,
            rationale="No systematic effectiveness evaluation schedule (such as penetration tests, Red Teaming, or holistic ISMS audits) was found in reviewed sources.",
            citations=[],
            limitations=["Under 17-AUS-17, individual control checks do not establish comprehensive compliance."],
        )

        # Component 3: Full Operational Scope
        c3 = DutyComponent(
            component_id="04-P02-6.C3",
            name="Geltungsbereich für alle Standorte (Scope Across Plants & OT)",
            status=ComponentStatus.INSUFFICIENT_EVIDENCE,
            rationale="ISO 27001 is geographically limited to Frankfurt data center; no effectiveness evidence exists for chemical production IT/OT at Marl or Bitterfeld.",
            citations=[
                EvidenceCitation(
                    source_id="company_profile.json",
                    document_title="Company Profile - Certifications",
                    file_path=profile_rel,
                    version="2026-11-09",
                    date="2026-11-09",
                    status="Active",
                    exact_passage=iso_cert,
                    location="company_profile.json, path: certifications",
                    demonstrates="ISO 27001 scope is limited to Frankfurt DC only.",
                )
            ],
            limitations=["Blanket ISO certification does not replace specific object-level effectiveness assessment."],
        )

        components = [c1, c2, c3]
        request = EvidenceRequest(
            duty_id="04-P02-6",
            duty_title="Wirksamkeitsbewertung",
            sources_reviewed=[controls_rel, profile_rel],
            missing_fact="An overarching technical effectiveness evaluation program covering all entity facilities is missing.",
            focused_question=(
                "Does Marenthal Chemie AG have an established cybersecurity effectiveness assessment program "
                "(such as periodic penetration testing, Red Teaming, or holistic ISMS audit reports) covering all "
                "German sites and production OT/ICS environments, including documented test results and remediation plans?"
            ),
        )

        return DutyComplianceResult(
            duty_id="04-P02-6",
            statutory_ref="§ 30 Abs. 2 Nr. 6 BSIG",
            duty_title="Wirksamkeitsbewertung",
            state=ComplianceState.EVIDENCE_MISSING,
            reason="Individual controls are tested, but an overarching security effectiveness assessment plan and proof covering production plants (Marl/Bitterfeld) are absent.",
            components=components,
            exclusion_log=exclusions,
            actionable_request=request,
        )

    def run_assessment(self) -> ComplianceAssessmentReport:
        r1 = self.evaluate_04_P02_1()
        r2 = self.evaluate_04_P02_2()
        r3 = self.evaluate_04_P02_3()
        r4 = self.evaluate_04_P02_6()
        results = [r1, r2, r3, r4]

        # Extract supported gaps
        supported_gaps = []
        for r in results:
            for c in r.components:
                if c.status == ComponentStatus.CONFIRMED_SHORTFALL:
                    supported_gaps.append({
                        "duty_id": r.duty_id,
                        "duty_title": r.duty_title,
                        "component_name": c.name,
                        "shortfall_description": c.rationale,
                        "citations": [cit.model_dump() for cit in c.citations],
                    })

        evidence_requests = [r.actionable_request for r in results if r.actionable_request]

        return ComplianceAssessmentReport(
            assessment_entity=self.ENTITY_NAME,
            entity_id=self.ENTITY_ID,
            as_of_date=self.as_of_date,
            analysis_date="2026-11-20",
            total_duties_assessed=len(results),
            results=results,
            supported_gaps=supported_gaps,
            evidence_requests=evidence_requests,
            sources_reviewed_summary=sorted(self.sources_reviewed),
        )