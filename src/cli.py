"""Command-line interface for running the COBACK compliance gap analysis."""

import argparse
from pathlib import Path
from src.analyzer import ComplianceAnalyzer
from src.corpus import EntityContext
from src.evaluator import EpistemicEvaluator
from src.loader import DataLoader
from src.retriever import HybridRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description="COBACK AI Compliance Gap Analysis")
    parser.add_argument("--data-dir", type=Path, default=Path("."), help="Path to data root or company_data directory")
    parser.add_argument("--as-of-date", type=str, default="2026-11-18", help="Assessment reference date (YYYY-MM-DD)")
    parser.add_argument("--entity", type=str, default="Marenthal Chemie AG", help="Target legal entity name or code")
    parser.add_argument("--full-corpus", action="store_true", help="Index full documents_index.csv instead of bounded starter set")
    parser.add_argument("--no-dense", action="store_true", help="Explicitly disable dense embeddings (lexical-only TF-IDF)")
    parser.add_argument("--no-llm", action="store_true", help="Explicitly disable LLM semantic evaluator (conservative baseline)")
    parser.add_argument("--ollama-url", type=str, default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--ollama-model", type=str, default="llama3.2", help="Ollama model name (default: llama3.2)")
    parser.add_argument("--check-llm", action="store_true", help="Test Ollama connection standalone and exit")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"), help="Directory for JSON/Markdown reports")
    args = parser.parse_args()

    if args.check_llm:
        dummy_retriever = HybridRetriever(units=[], use_dense=False)
        dummy_entity = EntityContext("Check", "CHK", "CHK", "DE", [], [])
        probe = EpistemicEvaluator(
            retriever=dummy_retriever,
            entity=dummy_entity,
            use_llm=True,
            ollama_url=args.ollama_url,
            ollama_model=args.ollama_model,
        )
        active = probe.verify_ollama_connection()
        print(f"[OK] Connected to Ollama at {args.ollama_url} using model '{active}'.")
        return

    loader = DataLoader(args.data_dir)
    analyzer = ComplianceAnalyzer(
        data_loader=loader,
        as_of_date=args.as_of_date,
        target_entity=args.entity,
        full_corpus=args.full_corpus,
        use_dense=not args.no_dense,
        use_llm=not args.no_llm,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
        progress_callback=lambda msg: print(msg, flush=True),
    )
    report = analyzer.run_assessment()

    print("\n" + "=" * 72)
    print(f"COBACK AI COMPLIANCE ANALYSIS — {report.assessment_entity} (As of {report.as_of_date})")
    print(f"Evaluator : {report.evaluation_mode}")
    print(f"Retriever : {report.retrieval_mode}")
    print("=" * 72 + "\n")

    for res in report.results:
        print(f"[{res.state.value.upper()}] {res.duty_id} — {res.duty_title} ({res.statutory_ref})")
        print(f"  Reason: {res.reason}")
        for comp in res.components:
            print(f"  - {comp.component_id} [{comp.status.value}]: {comp.rationale}")
        if res.actionable_request:
            print(f"  -> Follow-up: {res.actionable_request.focused_question}")
        print()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "compliance_report.json"
    md_path = args.output_dir / "compliance_report.md"

    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    md_lines = [
        f"# COBACK Compliance Assessment — {report.assessment_entity}",
        f"- **As-of Date**: {report.as_of_date}",
        f"- **Evaluation Mode**: {report.evaluation_mode}",
        f"- **Retrieval Mode**: {report.retrieval_mode}",
        f"- **Total Duties Assessed**: {report.total_duties_assessed}\n",
    ]
    for res in report.results:
        md_lines.append(f"## [{res.state.value.upper()}] {res.duty_id}: {res.duty_title} ({res.statutory_ref})")
        md_lines.append(f"{res.reason}\n")
        for comp in res.components:
            md_lines.append(f"- **{comp.component_id}** (`{comp.status.value}`): {comp.rationale}")
            for cit in comp.citations:
                md_lines.append(f"  - Citation: `{cit.source_id}` ({cit.location}): `{cit.exact_passage}`")
        if res.actionable_request:
            md_lines.append(f"\n> **Actionable Evidence Request**: {res.actionable_request.focused_question}\n")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[OK] JSON report written to: {json_path}")
    print(f"[OK] Markdown report written to: {md_path}")


if __name__ == "__main__":
    main()