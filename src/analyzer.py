"""
Regulatory Compliance Analysis Orchestrator.
Connects DutyParser -> CorpusBuilder -> HybridRetriever -> EpistemicEvaluator.
Records exact execution modes and diagnostics without silent fallbacks.
"""
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from src.corpus import CorpusBuilder
from src.duty_parser import DutyParser
from src.evaluator import EpistemicEvaluator
from src.loader import DataLoader
from src.models import ComplianceAssessmentReport, ComponentStatus, DutyComplianceResult
from src.retriever import HybridRetriever


class ComplianceAnalyzer:
    """End-to-end AI compliance gap analyzer."""

    def __init__(
        self,
        data_loader: DataLoader,
        as_of_date: str = "2026-11-18",
        target_entity: str = "Marenthal Chemie AG",
        full_corpus: bool = False,
        use_dense: bool = True,
        use_llm: bool = True,
        llm_client: Optional[Callable[[str], str]] = None,
        embedder: Optional[Any] = None,
        duty_file: Optional[str] = None,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.2",
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        default_subpath = data_loader.base_dir / "data" / "COBACK_Marenthal_Inputs" / "company_data"
        if default_subpath.is_dir():
            self.loader = DataLoader(default_subpath)
        else:
            self.loader = data_loader

        self.as_of_date = as_of_date
        self.target_entity = target_entity
        self.full_corpus = full_corpus
        self.use_dense = use_dense
        self.use_llm = use_llm
        self.llm_client = llm_client
        self.embedder = embedder
        self.duty_file = duty_file
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.progress_callback = progress_callback

    def _log(self, msg: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(msg)

    def run_assessment(self) -> ComplianceAssessmentReport:
        self._log("[1/4] Parsing legal duties and interpretation rules...")
        duty_parser = DutyParser(
            self.loader,
            llm_client=self.llm_client if self.use_llm else None,
        )
        duties = duty_parser.load_duties(duty_file=self.duty_file)

        self._log("[2/4] Building entity-scoped evidence corpus...")
        corpus_builder = CorpusBuilder(
            self.loader,
            target_entity_hint=self.target_entity,
            as_of_date=self.as_of_date,
        )
        entity = corpus_builder.load_entity_context()
        units = corpus_builder.build_corpus(entity=entity, full_corpus=self.full_corpus)

        self._log(f"[3/4] Indexing {len(units)} evidence units in hybrid retriever...")
        retriever = HybridRetriever(
            units=units,
            use_dense=self.use_dense,
            embedder=self.embedder,
        )

        evaluator = EpistemicEvaluator(
            retriever=retriever,
            entity=entity,
            as_of_date=self.as_of_date,
            use_llm=self.use_llm,
            llm_client=self.llm_client,
            ollama_url=self.ollama_url,
            ollama_model=self.ollama_model,
            progress_callback=self.progress_callback,
        )

        self._log(f"[4/4] Evaluating {len(duties)} duties ({evaluator.mode_label})...")
        results: List[DutyComplianceResult] = []
        for idx, d in enumerate(duties, start=1):
            self._log(f"Evaluating duty {idx}/{len(duties)}: {d.duty_id} ({d.title})...")
            results.append(evaluator.evaluate_duty(d))

        supported_gaps: List[Dict[str, Any]] = []
        for r in results:
            for c in r.components:
                if c.status == ComponentStatus.CONFIRMED_SHORTFALL:
                    supported_gaps.append(
                        {
                            "duty_id": r.duty_id,
                            "statutory_ref": r.statutory_ref,
                            "duty_title": r.duty_title,
                            "component_id": c.component_id,
                            "component_name": c.name,
                            "shortfall_description": c.rationale,
                            "citations": [cit.model_dump() for cit in c.citations],
                        }
                    )

        evidence_requests = [r.actionable_request for r in results if r.actionable_request is not None]

        return ComplianceAssessmentReport(
            assessment_entity=entity.entity_name,
            entity_id=entity.entity_id,
            entity_code=entity.entity_code,
            country=entity.country,
            as_of_date=self.as_of_date,
            analysis_date=date.today().isoformat(),
            evaluation_mode=evaluator.mode_label,
            retrieval_mode=retriever.retrieval_mode_label,
            diagnostics={
                "dense_embeddings_active": retriever.dense_enabled,
                "llm_evaluation_active": evaluator.use_llm,
                "total_evidence_units_indexed": len(units),
                "supporting_context_items": len(duty_parser.supporting_context),
            },
            total_duties_assessed=len(results),
            results=results,
            supported_gaps=supported_gaps,
            evidence_requests=evidence_requests,
            sources_reviewed_summary=sorted(corpus_builder.reviewed_files),
        )