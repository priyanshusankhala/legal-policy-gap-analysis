import json
from pathlib import Path
from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceState


def _create_synthetic_workspace(tmp_path: Path) -> Path:
    """Create a synthetic workspace with unseen duties and document versions."""
    company_dir = tmp_path / "company_data"
    docs_dir = company_dir / "documents"
    docs_dir.mkdir(parents=True)

    duties_payload = [
        {
            "duty_id": "99-NEW-1",
            "statutory_ref": "§ 30 Abs. 2 Nr. 8 BSIG",
            "duty_title": "Kryptografie und Verschlüsselung",
            "description_de": "Konzepte und Verfahren für den Einsatz von Kryptografie und Verschlüsselung.",
        },
        {
            "duty_id": "99-NEW-2",
            "statutory_ref": "§ 30 Abs. 2 Nr. 9 BSIG",
            "duty_title": "Sicherheit des Personals und Zugriffskontrolle",
            "description_de": "Konzepte für die Sicherheit des Personals und Zugriffskontrolle.",
        },
    ]
    (tmp_path / "NIS2_selected_duties.json").write_text(json.dumps(duties_payload), encoding="utf-8")

    (company_dir / "legal_entities.csv").write_text(
        "entity_id,cms_code,legal_name,country\nENT-DE-99,CMS-DE-99,TestWerk GmbH,DE\n",
        encoding="utf-8",
    )
    (company_dir / "company_profile.json").write_text(
        json.dumps(
            {
                "company_name": "TestWerk GmbH",
                "country": "DE",
                "certifications": ["ISO 27001 (Only Site Munich)"],
            }
        ),
        encoding="utf-8",
    )
    (company_dir / "twin_questions.csv").write_text(
        "question_id,entity_code,question_de,answer_de,status\nTQ-99,CMS-DE-99,Gibt es ein Zugriffskonzept?,,blank\n",
        encoding="utf-8",
    )

    # Superseded v1 vs active v2 policy
    (docs_dir / "DMS-00009001_VA-SEC-01_de_v1.txt").write_text(
        "Titel: Kryptografie-Richtlinie v1\nVersion: 1.0\nDatum: 2024-01-01\nStatus: Active\n\nVeraltete v1 Richtlinie.\n",
        encoding="utf-8",
    )
    (docs_dir / "DMS-00009002_VA-SEC-01_de_v2.txt").write_text(
        "Titel: Kryptografie-Richtlinie v2\nVersion: 2.0\nDatum: 2026-06-01\nStatus: Active\n\nAktuelle v2 Richtlinie für Kryptografie.\n",
        encoding="utf-8",
    )
    (docs_dir / "REG_Legal_Obligations_CMS-DE-99.txt").write_text(
        "| Obligation | Legal area | Status | Next due |\n"
        "| --- | --- | --- | --- |\n"
        "| Prüfung kryptografischer Verfahren | Informationssicherheit | offen | 2026-01-15 |\n",
        encoding="utf-8",
    )

    (tmp_path / "document_starters.csv").write_text(
        "source_id,file_path\n"
        "DMS-00009001,documents/DMS-00009001_VA-SEC-01_de_v1.txt\n"
        "DMS-00009002,documents/DMS-00009002_VA-SEC-01_de_v2.txt\n"
        "REG_Legal_Obligations_CMS-DE-99,documents/REG_Legal_Obligations_CMS-DE-99.txt\n",
        encoding="utf-8",
    )
    return company_dir


def _mock_grounded_llm(prompt: str) -> str:
    if "Decompose the following legal duty" in prompt:
        if "99-NEW-1" in prompt:
            return json.dumps(
                {
                    "components": [
                        {
                            "name": "Kryptografie",
                            "text": "Konzepte und Verfahren für den Einsatz von Kryptografie und Verschlüsselung.",
                            "exact_legal_quote": "Konzepte und Verfahren für den Einsatz von Kryptografie und Verschlüsselung.",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "components": [
                    {
                        "name": "Zugriffskontrolle",
                        "text": "Konzepte für die Sicherheit des Personals und Zugriffskontrolle.",
                        "exact_legal_quote": "Konzepte für die Sicherheit des Personals und Zugriffskontrolle.",
                    }
                ]
            }
        )

    if "99-NEW-1" in prompt:
        return json.dumps(
            {
                "status": "confirmed_shortfall",
                "rationale": "REG_Legal_Obligations_CMS-DE-99 explicitly records 'Prüfung kryptografischer Verfahren' as offen and overdue since 2026-01-15.",
                "cited_indices": [1],
                "limitations": [],
            }
        )

    return json.dumps(
        {
            "status": "insufficient_evidence",
            "rationale": "Digital twin questionnaire TQ-99 is blank and no supporting access-control policy is present.",
            "cited_indices": [1],
            "limitations": ["Missing access-control documentation."],
        }
    )


def test_dynamic_unseen_duties_and_version_resolution(tmp_path: Path):
    company_dir = _create_synthetic_workspace(tmp_path)
    loader = DataLoader(company_dir)
    analyzer = ComplianceAnalyzer(
        loader,
        as_of_date="2026-11-18",
        target_entity="TestWerk GmbH",
        use_dense=False,
        use_llm=True,
        llm_client=_mock_grounded_llm,
    )
    report = analyzer.run_assessment()

    assert report.total_duties_assessed == 2
    by_id = {r.duty_id: r for r in report.results}

    assert by_id["99-NEW-1"].state == ComplianceState.OPEN
    assert any(ex.source_id == "DMS-00009001" for ex in by_id["99-NEW-1"].exclusion_log)
    assert by_id["99-NEW-2"].state == ComplianceState.EVIDENCE_MISSING
    assert by_id["99-NEW-2"].actionable_request is not None


def test_exact_passage_is_verbatim_substring(tmp_path: Path):
    company_dir = _create_synthetic_workspace(tmp_path)
    loader = DataLoader(company_dir)
    analyzer = ComplianceAnalyzer(
        loader,
        as_of_date="2026-11-18",
        target_entity="TestWerk GmbH",
        use_dense=False,
        use_llm=True,
        llm_client=_mock_grounded_llm,
    )
    report = analyzer.run_assessment()

    for res in report.results:
        for ev in res.available_evidence:
            full_text = Path(company_dir / ev.file_path).read_text(encoding="utf-8")
            assert ev.exact_passage in full_text