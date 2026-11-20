from pathlib import Path
from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceState, ComponentStatus


def test_full_compliance_assessment():
    loader = DataLoader(Path("."))
    analyzer = ComplianceAnalyzer(loader)
    report = analyzer.run_assessment()

    assert report.total_duties_assessed == 4
    results_by_id = {r.duty_id: r for r in report.results}

    assert results_by_id["04-P02-1"].state == ComplianceState.OPEN
    assert any("offen" in ev.exact_passage for ev in results_by_id["04-P02-1"].available_evidence)
    assert any(c.status == ComponentStatus.CONFIRMED_SHORTFALL for c in results_by_id["04-P02-1"].components)

    for duty_id in ("04-P02-2", "04-P02-3", "04-P02-6"):
        assert results_by_id[duty_id].state == ComplianceState.EVIDENCE_MISSING
        assert results_by_id[duty_id].actionable_request is not None

    assert len(report.supported_gaps) >= 1
    assert len(report.evidence_requests) == 3