"""
Unit & Integration Tests for Coback AI Compliance Engine.
Verifies that arbitrary unseen duties, document versions, overdue dates,
and silent corpora are evaluated dynamically without hardcoded rules.
"""
import json
from pathlib import Path
from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceState, ComponentStatus


def _create_synthetic_workspace(tmp_path: Path) -> Path:
    company_dir = tmp_path / "company_data"
    docs_dir = company_dir / "documents"
    docs_dir.mkdir(parents=True)

    (tmp_path / "NIS2_selected_duties.json").write_text(
        json.dumps(
            [
                {
                    "duty_id": "UNSEEN-01",
                    "statutory_ref": "§ 30 Abs. 2 Nr. 4 BSIG",
                    "duty_title": "Kryptografie und Verschlüsselung",
                    "description_de": "Konzept und regelmäßige Prüfung kryptografischer Verfahren.",
                },
                {
                    "duty_id": "UNSEEN-02",
                    "statutory_ref": "§ 30 Abs. 2 Nr. 5 BSIG",
                    "duty_title": "Lieferkettensicherheit",
                    "description_de": "Sicherheitsbewertung direkter IT-Dienstleister.",
                },
            ]
        ),
        encoding="utf-8",
    )

    (company_dir / "company_profile.json").write_text(
        json.dumps(
            {
                "company_name": "TestWerk GmbH",
                "entity_id": "ENT-DE-99",
                "certifications": ["ISO/IEC 27001:2022 (only Munich Lab)"],
                "sites": [{"name": "Munich Lab", "country": "DE"}, {"name": "Dresden Plant", "country": "DE"}],
            }
        ),
        encoding="utf-8",
    )

    (company_dir / "legal_entities.csv").write_text(
        "entity_id,cms_code,legal_name,country\nENT-DE-99,CMS-DE-99,TestWerk GmbH,DE\n",
        encoding="utf-8",
    )

    (tmp_path / "document_starters.csv").write_text(
        "file_path\n"
        "documents/DMS-00000001_KR-050_v1.0_de.txt\n"
        "documents/DMS-00000002_KR-050_v2.0_de.txt\n"
        "documents/REG_Legal_Obligations_CMS-DE-99.txt\n",
        encoding="utf-8",
    )

    (docs_dir / "DMS-00000001_KR-050_v1.0_de.txt").write_text(
        "Titel: Kryptografierichtlinie\nVersion: 1.0\nDatum: 2023-01-10\n\n"
        "Alte Regelung zur Verschlüsselung von Datenträgern.\n",
        encoding="utf-8",
    )

    (docs_dir / "DMS-00000002_KR-050_v2.0_de.txt").write_text(
        "Titel: Kryptografierichtlinie\nVersion: 2.0\nDatum: 2025-05-01\n\n"
        "Aktuelle Richtlinie für Kryptografie und Schlüsselverwaltung.\n",
        encoding="utf-8",
    )

    (docs_dir / "REG_Legal_Obligations_CMS-DE-99.txt").write_text(
        "# Obligations Register\n\n"
        "| Obligation | Legal area | Status | Next due |\n"
        "| --- | --- | --- | --- |\n"
        "| Prüfung kryptografischer Verfahren | Informationssicherheit | offen | 2026-01-15 |\n",
        encoding="utf-8",
    )

    return company_dir


def test_dynamic_unseen_duties_and_version_resolution(tmp_path: Path):
    company_dir = _create_synthetic_workspace(tmp_path)
    loader = DataLoader(company_dir)
    analyzer = ComplianceAnalyzer(loader, as_of_date="2026-11-18", target_entity="TestWerk GmbH", use_dense=False)
    report = analyzer.run_assessment()

    assert report.total_duties_assessed == 2
    by_id = {r.duty_id: r for r in report.results}

    # UNSEEN-01 has an active policy v2.0 (superseding v1.0) AND an overdue 'offen' obligation -> OPEN
    r1 = by_id["UNSEEN-01"]
    assert r1.state == ComplianceState.OPEN
    assert any(ex.source_id == "DMS-00000001" and ex.disposition == "historical_only" for ex in r1.exclusion_log)
    assert any(c.status == ComponentStatus.CONFIRMED_SHORTFALL for c in r1.components)

    # UNSEEN-02 has zero evidence in corpus -> EVIDENCE_MISSING (silence != shortfall) + generated question
    r2 = by_id["UNSEEN-02"]
    assert r2.state == ComplianceState.EVIDENCE_MISSING
    assert r2.actionable_request is not None
    assert "Lieferkettensicherheit" in r2.actionable_request.focused_question


def test_exact_passage_is_verbatim_substring(tmp_path: Path):
    company_dir = _create_synthetic_workspace(tmp_path)
    loader = DataLoader(company_dir)
    analyzer = ComplianceAnalyzer(loader, as_of_date="2026-11-18", target_entity="TestWerk GmbH", use_dense=False)
    report = analyzer.run_assessment()

    for res in report.results:
        for comp in res.components:
            for cit in comp.citations:
                if cit.file_path.endswith(".txt"):
                    _, lines = loader.load_text_with_lines(cit.file_path)
                    full_text = "".join(lines)
                    assert cit.exact_passage in full_text