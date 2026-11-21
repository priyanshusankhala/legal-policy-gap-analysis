"""
Controlled behavioral verification tests proving that changing evidence
changes conclusions appropriately across all critical legal/epistemic edge cases.
"""
import json
from pathlib import Path
import pytest

from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceState, ComponentStatus


def _write_synthetic_workspace(
    tmp_path: Path,
    duty_desc: str,
    doc_content: str,
    doc_filename: str = "DMS-00000100_KR-01_de_v1.txt",
    extra_docs: dict[str, str] | None = None,
    twin_rows: str = "question_id,entity_code,question_de,answer_de,status\n",
) -> Path:
    company_dir = tmp_path / "company_data"
    docs_dir = company_dir / "documents"
    docs_dir.mkdir(parents=True)

    (tmp_path / "NIS2_selected_duties.json").write_text(
        json.dumps(
            [
                {
                    "duty_id": "04-P02-1",
                    "statutory_ref": "§30 Abs.2 Nr.1 BSIG",
                    "duty_title": "Risikoanalyse und IT-Sicherheitskonzept",
                    "description_de": duty_desc,
                }
            ]
        ),
        encoding="utf-8",
    )

    (company_dir / "legal_entities.csv").write_text(
        "entity_id,cms_code,legal_name,country\nENT-DE-01,CMS-DE-01,Marenthal Chemie AG,DE\n",
        encoding="utf-8",
    )
    (company_dir / "company_profile.json").write_text(
        json.dumps({"company_name": "Marenthal Chemie AG", "country": "DE", "certifications": []}),
        encoding="utf-8",
    )
    (company_dir / "twin_questions.csv").write_text(twin_rows, encoding="utf-8")

    starter_lines = ["source_id,file_path\n", f"DMS-00000100,documents/{doc_filename}\n"]
    (docs_dir / doc_filename).write_text(doc_content, encoding="utf-8")

    if extra_docs:
        for fname, body in extra_docs.items():
            (docs_dir / fname).write_text(body, encoding="utf-8")
            starter_lines.append(f"{fname.split('_')[0]},documents/{fname}\n")

    (tmp_path / "document_starters.csv").write_text("".join(starter_lines), encoding="utf-8")
    return company_dir


def test_open_obligation_with_future_deadline_is_not_overdue(tmp_path: Path):
    """Edge Case 1: Open obligation with deadline in the future must NOT be called overdue or OPEN."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="Jährliche Risikoanalyse durchführen.",
        doc_filename="REG_Legal_Obligations_CMS-DE-01.txt",
        doc_content=(
            "| Obligation | Legal area | Next due | Status |\n"
            "| --- | --- | --- | --- |\n"
            "| Informationssicherheitsrisikoanalyse durchführen | Informationssicherheit | 2027-06-30 | offen |\n"
        ),
    )

    def faulty_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {"components": [{"name": "Risikoanalyse", "text": "Jährliche Risikoanalyse durchführen.", "exact_legal_quote": "Jährliche Risikoanalyse durchführen."}]}
            )
        return json.dumps(
            {
                "status": "confirmed_shortfall",
                "rationale": "Status is offen.",
                "cited_indices": [1],
                "limitations": [],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=faulty_llm,
    )
    report = analyzer.run_assessment()
    res = report.results[0]
    assert res.state != ComplianceState.OPEN
    assert res.state == ComplianceState.EVIDENCE_MISSING
    assert "not yet overdue" in res.components[0].rationale.lower()


def test_negated_effectiveness_never_treated_as_supported(tmp_path: Path):
    """Edge Case 2: 'Not effective' / 'nicht wirksam' must NEVER be treated as positive effectiveness."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="Wirksamkeit der Sicherheitsmaßnahmen überprüfen.",
        doc_content=(
            "Titel: Auditbericht\nDatum: 2026-10-01\nStatus: Active\n\n"
            "Die Überprüfung der Notfallmaßnahmen ergab: Die Kontrollen sind derzeit nicht wirksam (not effective).\n"
        ),
    )

    def faulty_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {"components": [{"name": "Wirksamkeit", "text": "Wirksamkeit überprüfen.", "exact_legal_quote": "Wirksamkeit der Sicherheitsmaßnahmen überprüfen."}]}
            )
        return json.dumps(
            {
                "status": "supported",
                "rationale": "Contains word wirksam/effective.",
                "cited_indices": [1],
                "limitations": [],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=faulty_llm,
    )
    report = analyzer.run_assessment()
    assert report.results[0].state != ComplianceState.MET
    assert report.results[0].components[0].status == ComponentStatus.INSUFFICIENT_EVIDENCE


def test_completed_exercise_with_weaknesses_distinguishes_execution_from_effectiveness(tmp_path: Path):
    """Edge Case 3: Completed exercise + exposed weaknesses is NOT a contradiction and NOT full effectiveness."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="Notfallübung durchführen und Wirksamkeit nachweisen.",
        doc_content=(
            "Titel: Krisenübung Q3 2026\nDatum: 2026-09-15\n\n"
            "The exercise was completed on schedule. However, the exercise exposed weaknesses in failover recovery.\n"
        ),
    )

    def grounded_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {
                    "components": [
                        {
                            "name": "Durchführung der Übung",
                            "text": "Notfallübung durchführen",
                            "exact_legal_quote": "Notfallübung durchführen",
                        },
                        {
                            "name": "Wirksamkeitsnachweis",
                            "text": "Wirksamkeit nachweisen",
                            "exact_legal_quote": "Wirksamkeit nachweisen",
                        },
                    ]
                }
            )
        if "Durchführung der Übung" in prompt:
            return json.dumps(
                {
                    "status": "supported",
                    "rationale": "The exercise was completed on 2026-09-15.",
                    "cited_indices": [1],
                    "limitations": [],
                }
            )
        return json.dumps(
            {
                "status": "insufficient_evidence",
                "rationale": "Exercise execution is confirmed, but exposed weaknesses mean effectiveness is not yet established.",
                "cited_indices": [1],
                "limitations": ["Remediation verification required."],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=grounded_llm,
    )
    report = analyzer.run_assessment()
    res = report.results[0]
    assert res.components[0].status == ComponentStatus.SUPPORTED
    assert res.components[1].status == ComponentStatus.INSUFFICIENT_EVIDENCE
    assert res.state == ComplianceState.EVIDENCE_MISSING


def test_blank_questionnaire_does_not_block_valid_supporting_record(tmp_path: Path):
    """Edge Case 4: Blank questionnaire + valid supporting record must evaluate the supporting record."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="IT-Sicherheitskonzept verabschieden.",
        doc_content=(
            "Titel: IT-Sicherheitskonzept\nGültig ab: 2026-01-15\nStatus: Erfüllt\n\n"
            "Das unternehmensweite IT-Sicherheitskonzept wurde vollständig umgesetzt und genehmigt.\n"
        ),
        twin_rows=(
            "question_id,entity_code,question_de,answer_de,status\n"
            "TQ-01,CMS-DE-01,Liegt ein IT-Sicherheitskonzept vor?,,blank\n"
        ),
    )

    def grounded_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {"components": [{"name": "IT-Sicherheitskonzept", "text": "IT-Sicherheitskonzept verabschieden.", "exact_legal_quote": "IT-Sicherheitskonzept verabschieden."}]}
            )
        return json.dumps(
            {
                "status": "supported",
                "rationale": "Although twin_questions.csv#TQ-01 is blank, DMS-00000100 confirms the IT-Sicherheitskonzept is implemented and approved.",
                "cited_indices": [1],
                "limitations": [],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=grounded_llm,
    )
    report = analyzer.run_assessment()
    assert report.results[0].state == ComplianceState.MET


def test_future_effective_policy_does_not_replace_current_policy(tmp_path: Path):
    """Edge Case 5: Newer policy effective AFTER as_of_date must not supersede or replace current policy."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="Backup-Richtlinie vorhalten.",
        doc_filename="DMS-00000101_KR-02_de_v1.txt",
        doc_content=(
            "Titel: Backup-Richtlinie v1\nGültig ab: 2025-03-01\nStatus: Erfüllt\n\n"
            "Die gültige Backup-Richtlinie ist für alle Systeme umgesetzt.\n"
        ),
        extra_docs={
            "DMS-00000202_KR-02_de_v2.txt": (
                "Titel: Backup-Richtlinie v2\nGültig ab: 2027-01-01\nStatus: Entwurf\n\n"
                "Neue zukünftige Backup-Richtlinie ab 2027.\n"
            )
        },
    )

    def grounded_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {"components": [{"name": "Backup-Richtlinie", "text": "Backup-Richtlinie vorhalten.", "exact_legal_quote": "Backup-Richtlinie vorhalten."}]}
            )
        assert "DMS-00000202" not in prompt
        assert "DMS-00000101" in prompt
        return json.dumps(
            {
                "status": "supported",
                "rationale": "DMS-00000101 (v1.0, effective 2025-03-01) is active as of 2026-11-18.",
                "cited_indices": [1],
                "limitations": [],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=grounded_llm,
    )
    report = analyzer.run_assessment()
    res = report.results[0]
    assert res.state == ComplianceState.MET
    assert any(ex.source_id == "DMS-00000202" and ex.disposition == "not_yet_effective" for ex in res.exclusion_log)


def test_future_plan_never_marked_supported(tmp_path: Path):
    """Edge Case 6: Relevant passage describing only a future plan must NEVER be marked SUPPORTED."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="Wiederherstellungsverfahren etablieren.",
        doc_content=(
            "Titel: IT-Roadmap\nDatum: 2026-10-10\n\n"
            "We plan to introduce a recovery procedure next year.\n"
        ),
    )

    def overoptimistic_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {"components": [{"name": "Recovery", "text": "Wiederherstellungsverfahren etablieren.", "exact_legal_quote": "Wiederherstellungsverfahren etablieren."}]}
            )
        return json.dumps(
            {
                "status": "supported",
                "rationale": "Mentions recovery procedure.",
                "cited_indices": [1],
                "limitations": [],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=overoptimistic_llm,
    )
    report = analyzer.run_assessment()
    assert report.results[0].state != ComplianceState.MET
    assert report.results[0].components[0].status == ComponentStatus.INSUFFICIENT_EVIDENCE


def test_invalid_citation_index_is_rejected_not_clamped(tmp_path: Path):
    """Edge Case 7: Out-of-range LLM citation index must raise ValueError rather than clamping."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="Risikoanalyse durchführen.",
        doc_content="Titel: Risikoanalyse\nDatum: 2026-05-01\n\nDokumentation vorhanden.\n",
    )

    def hallucinating_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {"components": [{"name": "Risikoanalyse", "text": "Risikoanalyse durchführen.", "exact_legal_quote": "Risikoanalyse durchführen."}]}
            )
        return json.dumps(
            {
                "status": "supported",
                "rationale": "Hallucinated citation index.",
                "cited_indices": [99],
                "limitations": [],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=hallucinating_llm,
    )
    with pytest.raises(ValueError, match="out-of-range evidence index"):
        analyzer.run_assessment()


def test_truncated_json_recovers_via_bounded_retry(tmp_path: Path):
    """Edge Case 8: Truncated LLM JSON recovers cleanly on retry without falling back to heuristics."""
    company_dir = _write_synthetic_workspace(
        tmp_path,
        duty_desc="Risikoanalyse durchführen.",
        doc_content="Titel: Risikoanalyse\nDatum: 2026-05-01\n\nJährliche Risikoanalyse dokumentiert.\n",
    )

    calls = {"eval": 0}

    def flaky_json_llm(prompt: str) -> str:
        if "Decompose the following legal duty" in prompt:
            return json.dumps(
                {"components": [{"name": "Risikoanalyse", "text": "Risikoanalyse durchführen.", "exact_legal_quote": "Risikoanalyse durchführen."}]}
            )
        calls["eval"] += 1
        if calls["eval"] == 1:
            return '{"status": "insufficient_evidence", "rationale": "Truncated output...'
        return json.dumps(
            {
                "status": "insufficient_evidence",
                "rationale": "Recovered on retry with valid compact JSON.",
                "cited_indices": [1],
                "limitations": ["Verification log missing."],
            }
        )

    analyzer = ComplianceAnalyzer(
        DataLoader(company_dir),
        as_of_date="2026-11-18",
        use_dense=False,
        use_llm=True,
        llm_client=flaky_json_llm,
    )
    report = analyzer.run_assessment()
    assert calls["eval"] == 2
    assert report.results[0].state == ComplianceState.EVIDENCE_MISSING