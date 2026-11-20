"""
CLI interface for Coback NIS2 Compliance Analysis.
Runs the dynamic AI compliance pipeline and writes JSON & Markdown deliverables.
"""
import argparse
import json
from pathlib import Path
from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceAssessmentReport


def generate_markdown(report: ComplianceAssessmentReport) -> str:
    md = [
        "# Coback Compliance Analysis Report",
        f"**Entity:** {report.assessment_entity} (`{report.entity_code}` / `{report.entity_id}`)",
        f"**As-of Date:** {report.as_of_date} | **Analysis Date:** {report.analysis_date}",
        f"**Engine:** {report.evaluation_mode}\n",
        "## 1. Compliance Assessment Summary\n",
        "| Duty ID | Statutory Ref | Duty Title | State | Summary Reason |",
        "| :--- | :--- | :--- | :---: | :--- |",
    ]
    for r in report.results:
        summary = r.reason.replace("\n", " ")
        if len(summary) > 130:
            summary = summary[:127] + "..."
        md.append(
            f"| `{r.duty_id}` | {r.statutory_ref} | {r.duty_title} | **`{r.state.value.upper()}`** | {summary} |"
        )

    md.append("\n---\n## 2. Detailed Findings by Duty\n")
    for r in report.results:
        md.append(f"### Duty `{r.duty_id}`: {r.duty_title} ({r.statutory_ref})")
        md.append(f"- **State:** `{r.state.value}`")
        md.append(f"- **Reason:** {r.reason}")
        for comp in r.components:
            md.append(f"- **Component `{comp.component_id}` — {comp.name}:** `{comp.status.value}`")
            md.append(f"  - *Rationale:* {comp.rationale}")
            for cit in comp.citations:
                md.append(
                    f"  - *Citation:* `{cit.source_id}` ({cit.location}, v{cit.version or 'N/A'}, status: `{cit.status or 'N/A'}`) — {cit.demonstrates}"
                )
                md.append(f"    ```text\n    {cit.exact_passage}\n    ```")
        if r.exclusion_log:
            md.append("- **Version & Scope Limitations:**")
            for ex in r.exclusion_log:
                md.append(f"  - `{ex.source_id}` (`{ex.disposition}`): {ex.reason}")
        md.append("")

    md.append("---\n## 3. Supported Gaps (Confirmed Shortfalls)\n")
    if report.supported_gaps:
        for g in report.supported_gaps:
            md.append(f"- **Duty `{g['duty_id']}` — {g['component_name']}**: {g['shortfall_description']}")
    else:
        md.append("No confirmed shortfalls identified.")

    md.append("\n---\n## 4. Focused Evidence Requests (Unresolved Duties)\n")
    if report.evidence_requests:
        for req in report.evidence_requests:
            md.append(f"### `{req.duty_id}` — {req.duty_title}")
            md.append(f"- **Missing Proof / Contradiction:** {req.missing_fact}")
            md.append(f"- **Focused Question:** *\"{req.focused_question}\"*")
            md.append(f"- **Sources Reviewed:** {', '.join(req.sources_reviewed)}\n")
    else:
        md.append("All assessed duties are resolved.\n")

    md.append("---\n## 5. Reviewed Sources Summary\n")
    for src in report.sources_reviewed_summary:
        md.append(f"- `{src}`")

    return "\n".join(md)


def main() -> None:
    parser = argparse.ArgumentParser(description="Coback NIS2 Compliance Analysis CLI")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/COBACK_Marenthal_Inputs/company_data",
        help="Path to company_data or COBACK_Marenthal_Inputs directory",
    )
    parser.add_argument("--as-of", type=str, default="2026-11-18", help="Assessment snapshot date (YYYY-MM-DD)")
    parser.add_argument("--entity", type=str, default="Marenthal Chemie AG", help="Target legal entity name")
    parser.add_argument("--full-corpus", action="store_true", help="Index full entity index beyond starter list")
    parser.add_argument("--use-llm", action="store_true", help="Enable local Ollama epistemic verification")
    parser.add_argument("--no-dense", action="store_true", help="Disable SentenceTransformer embeddings (TF-IDF only)")
    parser.add_argument("--json-out", type=str, default="outputs/compliance_report.json", help="JSON output path")
    parser.add_argument("--md-out", type=str, default="outputs/compliance_report.md", help="Markdown output path")
    args = parser.parse_args()

    loader = DataLoader(Path(args.data_dir))
    analyzer = ComplianceAnalyzer(
        data_loader=loader,
        as_of_date=args.as_of,
        target_entity=args.entity,
        full_corpus=args.full_corpus,
        use_dense=not args.no_dense,
        use_llm=args.use_llm,
    )
    report = analyzer.run_assessment()

    print("\n" + "=" * 72)
    print(f"COBACK AI COMPLIANCE ANALYSIS — {report.assessment_entity} (As of {report.as_of_date})")
    print(f"Engine: {report.evaluation_mode}")
    print("=" * 72 + "\n")

    for r in report.results:
        print(f"[{r.state.value.upper()}] {r.duty_id} — {r.duty_title} ({r.statutory_ref})")
        print(f"  Reason: {r.reason}")
        for comp in r.components:
            print(f"   • {comp.component_id} [{comp.status.value}]: {comp.rationale}")
        print()

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = Path(args.md_out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(generate_markdown(report), encoding="utf-8")

    print(f"[OK] JSON report written to: {json_path}")
    print(f"[OK] Markdown report written to: {md_path}\n")


if __name__ == "__main__":
    main()