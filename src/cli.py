"""
CLI interface for Coback NIS2 Compliance Analysis.
Can output formatted tables to the terminal and generate JSON / Markdown reports.
"""
import argparse
import json
import sys
from pathlib import Path
from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceAssessmentReport


def generate_markdown(report: ComplianceAssessmentReport) -> str:
    md = []
    md.append(f"# Coback Compliance Analysis Report")
    md.append(f"**Entity:** {report.assessment_entity} (`{report.entity_id}`)")
    md.append(f"**Snapshot Date:** {report.data_snapshot_date} | **Analysis Date:** {report.analysis_date}")
    md.append(f"**Scope:** 4 Primary NIS2 / BSIG Duties (§ 30 BSIG)\n")

    md.append("## 1. Compliance Assessment Summary\n")
    md.append("| Duty ID | Statutory Ref | Duty Title | State | Summary Reason |")
    md.append("| :--- | :--- | :--- | :---: | :--- |")
    for r in report.results:
        state_badge = f"**`{r.state.value.upper()}`**"
        md.append(f"| `{r.duty_id}` | {r.statutory_ref} | {r.duty_title} | {state_badge} | {r.reason[:110]}... |")
    md.append("\n---\n")

    md.append("## 2. Detailed Findings by Duty\n")
    for r in report.results:
        md.append(f"### Duty `{r.duty_id}`: {r.duty_title} ({r.statutory_ref})")
        md.append(f"- **State:** `{r.state.value}`")
        md.append(f"- **Assessment Reasoning:** {r.reason}")
        if r.supported_aspects:
            md.append(f"- **Supported Aspects:**")
            for sa in r.supported_aspects:
                md.append(f"  - {sa}")
        if r.shortfall_or_missing_aspects:
            md.append(f"- **Shortfalls / Missing Aspects:**")
            for ma in r.shortfall_or_missing_aspects:
                md.append(f"  - {ma}")
        
        md.append(f"- **Reviewed Evidence Citations:**")
        for ev in r.available_evidence:
            md.append(f"  - **Source ID:** `{ev.source_id}` | **Title:** {ev.document_title} (Version: {ev.version or 'N/A'}, Date: {ev.date or 'N/A'})")
            md.append(f"    - **Location:** `{ev.location}`")
            md.append(f"    - **Demonstrates:** {ev.demonstrates}")
            md.append(f"    - **Exact Quote:**")
            md.append(f"      ```text\n      {ev.exact_passage}\n      ```")
        md.append("\n")

    md.append("---\n")
    md.append("## 3. Supported Gaps (Ready for Task Planning)\n")
    if report.supported_gaps:
        for g in report.supported_gaps:
            md.append(f"- **Duty `{g.duty_id}` ({g.duty_title})**")
            md.append(f"  - **Finding:** {g.shortfall_description}")
            md.append(f"  - **Evidence Basis:** {g.basis_of_finding}")
            md.append(f"  - **Exact Passage:** `\"{g.evidence_citation.exact_passage.strip()}\"`")
    else:
        md.append("No confirmed gaps identified.")

    md.append("\n---\n")
    md.append("## 4. Focused Evidence Requests (Unresolved Duties)\n")
    for req in report.evidence_requests:
        md.append(f"### Actionable Follow-up for `{req.duty_id}` ({req.duty_title})")
        md.append(f"- **Missing Fact:** {req.missing_fact}")
        md.append(f"- **Focused Question:** *\"{req.focused_question}\"*")
        md.append(f"- **Sources Reviewed:** {', '.join(req.sources_reviewed)}")
        md.append("\n")

    md.append("---\n")
    md.append("## 5. Reviewed Sources & Version Effects\n")
    for s in report.sources_reviewed_summary:
        md.append(f"- `{s}`")
    md.append("\n**Version & Register Status Notes:**")
    md.append("- Policy `DMS-00000420` (KR-009) is active at version 2.0; the older v1.1 was superseded.")
    md.append("- Policy `DMS-00000671` (KR-017) is active at version 2.0, but its scope is strictly EHS, leaving IT incident handling silent.")
    md.append("- Register `REG_Legal_Obligations_CMS-DE-01.txt` carries authoritative evidentiary weight for confirmed gaps where obligations are explicitly marked `offen`.")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="Coback NIS2 Compliance Analysis CLI")
    parser.add_argument("--data-dir", type=str, default=".", help="Root directory containing data / company_data")
    parser.add_argument("--json-out", type=str, default="outputs/compliance_report.json", help="Path to write JSON output")
    parser.add_argument("--md-out", type=str, default="outputs/compliance_report.md", help="Path to write Markdown output")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    loader = DataLoader(data_dir)
    analyzer = ComplianceAnalyzer(loader)

    print("\n" + "=" * 70)
    print("COBACK COMPLIANCE ANALYSIS ENGINE — NIS2 / BSIG (§ 30 BSIG)")
    print(f"Entity: {ComplianceAnalyzer.ENTITY_NAME} | Snapshot: {ComplianceAnalyzer.SNAPSHOT_DATE}")
    print("=" * 70 + "\n")

    report = analyzer.run_assessment()

    # Console display
    for r in report.results:
        color_code = "\033[92m" if r.state == "met" else ("\033[91m" if r.state == "open" else "\033[93m")
        reset_code = "\033[0m"
        print(f"[{color_code}{r.state.value.upper()}{reset_code}] {r.duty_id} - {r.duty_title} ({r.statutory_ref})")
        print(f"   Reason: {r.reason}")
        print(f"   Evidence cited: {len(r.available_evidence)} item(s)")
        print()

    print(f"Supported Gaps: {len(report.supported_gaps)}")
    print(f"Evidence Requests: {len(report.evidence_requests)}")
    print(f"Sources Reviewed: {len(report.sources_reviewed_summary)}")

    # Write files
    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)
    print(f"\n[OK] JSON report saved to: {json_path}")

    md_path = Path(args.md_out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown(report))
    print(f"[OK] Markdown report saved to: {md_path}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()