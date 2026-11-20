from pathlib import Path
from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceState

def test_full_compliance_assessment(tmp_path):
    # Pass project root
    loader = DataLoader(Path("."))
    analyzer = ComplianceAnalyzer(loader)
    report = analyzer.run_assessment()

    assert report.total_duties_assessed == 4
    results_by_id = {r.duty_id: r for r in report.results}

    # Verify 04-P02-1 is OPEN (Confirmed Gap)
    assert results_by_id["04-P02-1"].state == ComplianceState.OPEN
    assert any("offen" in ev.exact_passage for ev in results_by_id["04-P02-1"].available_evidence)

    # Verify 04-P02-2 is EVIDENCE_MISSING (Silence is not a gap)
    assert results_by_id["04-P02-2"].state == ComplianceState.EVIDENCE_MISSING
    assert results_by_id["04-P02-2"].actionable_request is not None

    # Verify 04-P02-3 is EVIDENCE_MISSING (Missing operational restore metrics)
    assert results_by_id["04-P02-3"].state == ComplianceState.EVIDENCE_MISSING
    assert any(ev.source_id == "DMS-00001406" for ev in results_by_id["04-P02-3"].available_evidence)

    # Verify 04-P02-6 is EVIDENCE_MISSING
    assert results_by_id["04-P02-6"].state == ComplianceState.EVIDENCE_MISSING

    # Verify separate gap list and evidence request list
    assert len(report.supported_gaps) == 1
    assert report.supported_gaps[0].duty_id == "04-P02-1"
    assert len(report.evidence_requests) == 3