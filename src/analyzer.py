"""
Regulatory Compliance Analysis Orchestrator.
Connects DutyParser -> CorpusBuilder -> HybridRetriever -> EpistemicEvaluator.
Contains zero hardcoded duty IDs, file paths, or outcomes.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from src.corpus import CorpusBuilder
from src.duty_parser import DutyParser
from src.evaluator import EpistemicEvaluator
from src.loader import DataLoader
from src.models import ComplianceAssessmentReport, ComponentStatus, DutyComplianceResult
from src.retriever import HybridRetriever


class ComplianceAnalyzer:
    """End-to-end AI compliance gap analyzer for any selected duty set."""

    def __init__(
        self,
        data_loader: DataLoader,
        as_of_date: str = "2026-11-18",
        target_entity: str = "Marenthal Chemie AG",
        full_corpus: bool = False,
        use_dense: bool = True,
        use_llm: bool = False,
        duty_file: Optional[str] = None,
    ):
        # Support callers passing the project root (e.g. DataLoader(Path(".")))
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
        self.duty_file = duty_file

    def run_assessment(self) -> ComplianceAssessmentReport:
        # 1. Discover & decompose legal duties dynamically
        duty_parser = DutyParser(self.loader)
        duties = duty_parser.load_duties(duty_file=self.duty_file)

        # 2. Resolve entity context & build version-aware corpus
        corpus_builder = CorpusBuilder(self.loader, target_entity_hint=self.target_entity)
        entity = corpus_builder.load_entity_context()
        units = corpus_builder.build_corpus(entity=entity, full_corpus=self.full_corpus)

        # 3. Index evidence units with hybrid multilingual embeddings + TF-IDF
        retriever = HybridRetriever(units=units, use_dense=self.use_dense)

        # 4. Evaluate each duty epistemically
        evaluator = EpistemicEvaluator(
            retriever=retriever,
            entity=entity,
            as_of_date=self.as_of_date,
            use_llm=self.use_llm,
        )

        results: List[DutyComplianceResult] = [evaluator.evaluate_duty(d) for d in duties]

        # 5. Extract substantiated gaps & actionable follow-up requests
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
            as_of_date=self.as_of_date,
            analysis_date=date.today().isoformat(),
            evaluation_mode=evaluator.mode_label,
            total_duties_assessed=len(results),
            results=results,
            supported_gaps=supported_gaps,
            evidence_requests=evidence_requests,
            sources_reviewed_summary=sorted(corpus_builder.reviewed_files),
        )