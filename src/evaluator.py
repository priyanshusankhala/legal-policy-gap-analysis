"""
Grounded Neuro-Symbolic Epistemic Compliance Evaluator.
Architecture:
1. Retrieves ranked candidates AND ensures full batch coverage of active starter DMS policy/evidence
   documents while filtering high-volume register rows and catalog facts by semantic/lexical relevance.
2. Filters out superseded, future-dated (effective_date > as_of_date), and non-matching domain/jurisdiction
   rows with explicit exclusion log entries.
3. Calls the contextual LLM interpreter FIRST on candidate evidence (never pre-empted by keyword
   shortcuts, and never halting on a blank twin_questions row when valid records exist).
4. Includes bounded retry on truncated/malformed JSON while failing loudly on out-of-range
   citations or persistent LLM failures.
5. Deterministic validator checks citation indices, negations ('nicht wirksam', 'not effective'),
   future plans ('plan to...'), overdue open obligations ('offen' with due_date <= as_of_date),
   future deadlines ('offen' with due_date > as_of_date), execution vs. effectiveness, and scope coverage.
6. Records per-duty searched sources ranked by actual retrieval relevance score and an explicit trace
   of how document versions and register statuses influenced the final verdict.
"""
from datetime import date
import json
import os
import re
import time
from typing import Callable, List, Optional
import httpx

from src.corpus import EntityContext, parse_iso_or_de_date
from src.duty_parser import ParsedDuty, RequirementClause
from src.models import (
    ComplianceState,
    ComponentStatus,
    DutyComplianceResult,
    DutyComponent,
    EvidenceCitation,
    EvidenceRequest,
    ExclusionLogItem,
)
from src.retriever import HybridRetriever, ScoredEvidence, extract_specific_stems


def aggregate_duty_state(components: List[DutyComponent]) -> ComplianceState:
    """Pure deterministic state aggregation per Coback rules."""
    if not components:
        return ComplianceState.EVIDENCE_MISSING
    if any(c.status == ComponentStatus.CONFIRMED_SHORTFALL for c in components):
        return ComplianceState.OPEN
    if all(c.status == ComponentStatus.SUPPORTED for c in components):
        return ComplianceState.MET
    return ComplianceState.EVIDENCE_MISSING


def parse_llm_json_response(raw_text: str) -> dict:
    """Parse JSON from LLM output, stripping optional markdown code fences if present."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


class TextPolarityAnalyzer:
    """Negation-aware and future-plan-aware polarity detector for German and English evidence."""

    NEGATED_PATTERNS = re.compile(
        r"\b("
        r"nicht\s+erfüllt|nicht\s+wirksam|unwirksam|nicht\s+umgesetzt|nicht\s+vorhanden|"
        r"nicht\s+durchgeführt|keine\s+nachweise|mangelhaft|fehlgeschlagen|"
        r"not\s+effective|ineffective|not\s+fulfilled|unfulfilled|not\s+implemented|"
        r"not\s+completed|failed|non-compliant|deficient"
        r")\b",
        re.IGNORECASE,
    )

    FUTURE_PLAN_PATTERNS = re.compile(
        r"\b("
        r"plan\s+to|planned\s+for|will\s+introduce|will\s+implement|next\s+year|"
        r"in\s+future|to\s+be\s+established|roadmap|"
        r"planen|geplant|beabsichtigt|soll\s+eingeführt|wird\s+eingeführt|"
        r"nächstes\s+jahr|zukünftig|in\s+vorbereitung|in\s+planung"
        r")\b",
        re.IGNORECASE,
    )

    AFFIRMATIVE_PATTERNS = re.compile(
        r"\b("
        r"erfüllt|wirksam|umgesetzt|abgeschlossen|bestanden|nachgewiesen|genehmigt|in\s+kraft|"
        r"fulfilled|effective|implemented|completed|passed|verified|approved|operational"
        r")\b",
        re.IGNORECASE,
    )

    @classmethod
    def has_negation(cls, text: str) -> bool:
        return bool(cls.NEGATED_PATTERNS.search(text))

    @classmethod
    def is_future_plan_only(cls, text: str) -> bool:
        return bool(cls.FUTURE_PLAN_PATTERNS.search(text))

    @classmethod
    def is_affirmatively_supported(cls, text: str) -> bool:
        if cls.has_negation(text) or cls.is_future_plan_only(text):
            return False
        return bool(cls.AFFIRMATIVE_PATTERNS.search(text))


class EpistemicEvaluator:
    """Grounded LLM + Deterministic Validation Compliance Evaluator."""

    OPEN_STATUS_TOKENS = ("offen", "open", "nicht erfüllt", "overdue", "überfällig", "failed", "unfulfilled")

    NON_IT_LEGAL_AREAS = (
        "immissionsschutz",
        "störfallrecht",
        "anlagensicherheit",
        "betriebssicherheit",
        "druckgeräte",
        "brand- und explosionsschutz",
        "brandschutz",
        "umwelt",
        "arbeitsschutz",
        "datenschutz",
        "sanktionen",
        "exportkontrolle",
        "arbeitsrecht",
        "steuer",
        "chemikalienrecht",
        "gefahrgutrecht",
        "gefahrstoffe",
        "produktsicherheit",
    )

    NON_COMPLIANCE_DOC_MARKERS = ("_sdb-", "_tdb-", "produkte", "gesellschaften")

    def __init__(
        self,
        retriever: HybridRetriever,
        entity: EntityContext,
        as_of_date: str = "2026-11-18",
        use_llm: bool = True,
        llm_client: Optional[Callable[[str], str]] = None,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.2",
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.retriever = retriever
        self.entity = entity
        self.as_of_str = as_of_date
        self.as_of = date.fromisoformat(as_of_date)
        self.use_llm = use_llm
        self.llm_client = llm_client
        self.ollama_url = os.environ.get("OLLAMA_URL", ollama_url).rstrip("/")
        self.ollama_model = os.environ.get("OLLAMA_MODEL", ollama_model)
        self._resolved_ollama_model: Optional[str] = None
        self.progress_callback = progress_callback

        if self.use_llm and self.llm_client is None:
            self.llm_client = self._default_ollama_client

    def _log_progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)

    @property
    def mode_label(self) -> str:
        if self.use_llm:
            if self.llm_client != self._default_ollama_client:
                backend = "Custom/Injected LLM"
            else:
                active_model = self._resolved_ollama_model or self.ollama_model
                backend = f"Ollama ({active_model})"
            return f"Grounded LLM Epistemic Engine ({backend}) + Deterministic Validator"
        return "Conservative Symbolic Baseline (LLM Disabled — Unverified Passages Never Default to Supported)"

    def _discover_local_ollama_model(self) -> Optional[str]:
        """Inspect GET /api/tags to verify or select an installed Ollama model."""
        try:
            tags_resp = httpx.get(f"{self.ollama_url}/api/tags", timeout=5.0)
            tags_resp.raise_for_status()
            models = [
                str(m.get("name"))
                for m in tags_resp.json().get("models", [])
                if isinstance(m, dict) and m.get("name")
            ]
            if not models:
                return None

            requested_lower = self.ollama_model.lower()
            for name in models:
                if name.lower() == requested_lower or name.lower() == f"{requested_lower}:latest":
                    return name
            for name in models:
                if name.lower().startswith(requested_lower) and "embed" not in name.lower():
                    return name
            for preferred_prefix in ("llama3.2", "llama3", "qwen", "mistral", "gemma", "phi", "deepseek"):
                for name in models:
                    if name.lower().startswith(preferred_prefix) and "embed" not in name.lower():
                        return name
            non_embed = [m for m in models if "embed" not in m.lower()]
            return non_embed[0] if non_embed else models[0]
        except Exception:
            return None

    def verify_ollama_connection(self) -> str:
        """Standalone connectivity check against Ollama; returns active model name or raises RuntimeError."""
        discovered = self._discover_local_ollama_model()
        if discovered:
            self._resolved_ollama_model = discovered
        target = self._resolved_ollama_model or self.ollama_model
        raw = self._default_ollama_client('Respond with valid JSON only: {"status": "ok"}')
        parsed = parse_llm_json_response(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Unexpected non-JSON response from Ollama ({target}): {raw}")
        return target

    def _default_ollama_client(self, prompt: str) -> str:
        if self._resolved_ollama_model is None:
            discovered = self._discover_local_ollama_model()
            if discovered:
                self._resolved_ollama_model = discovered

        target_model = self._resolved_ollama_model or self.ollama_model
        payload = {
            "model": target_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0.0,
                "num_ctx": 4096,
                "num_predict": 1024,
                "repeat_penalty": 1.18,
            },
        }
        timeout_cfg = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        try:
            resp = httpx.post(f"{self.ollama_url}/api/generate", json=payload, timeout=timeout_cfg)
            resp.raise_for_status()
            return str(resp.json().get("response", ""))
        except Exception as exc:
            raise RuntimeError(
                f"LLM evaluation is enabled (use_llm=True), but the LLM endpoint at '{self.ollama_url}' "
                f"(model '{target_model}') failed: {exc}. "
                "Refusing to silently fall back to heuristic rules. "
                "Ensure Ollama is running with `ollama pull llama3.2`, set OLLAMA_MODEL, or pass --no-llm."
            ) from exc

    def _is_domain_compatible(self, duty: ParsedDuty, hit: ScoredEvidence) -> bool:
        if duty.domain != "informationssicherheit":
            return True

        fp_lower = hit.unit.file_path.lower()
        if any(marker in fp_lower for marker in self.NON_COMPLIANCE_DOC_MARKERS):
            return False

        passage_lower = hit.unit.exact_passage.lower()
        if self.entity.country == "DE" and (
            "rechtsraum:** fr" in passage_lower or "saint-fons" in passage_lower
        ):
            return False

        if any(
            non_it_cat in passage_lower
            for non_it_cat in (
                "kategorie:** umwelt",
                "kategorie:** arbeitsschutz",
                "kategorie:** gefahrgut",
                "kategorie:** anlagensicherheit",
                "kategorie:** produkte",
                "kategorie:** chemikalien",
            )
        ):
            return False

        if "reg_incidents" in fp_lower and any(
            ehs_word in passage_lower
            for ehs_word in ("arbeitssicherheit", "beinaheunfall", "gabelstapler", "arbeitsunfall", "stoffaustritt")
        ):
            return False

        area = (
            hit.unit.structured_fields.get("Legal area")
            or hit.unit.structured_fields.get("Category")
            or hit.unit.scope_or_area
            or ""
        ).lower()
        basis = (
            hit.unit.structured_fields.get("Basis")
            or hit.unit.structured_fields.get("Legal basis")
            or ""
        ).lower()

        if any(it_kw in f"{area} {basis}" for it_kw in ("informationssicherheit", "it-sicherheit", "bsi", "nis2", "iso/iec 27001")):
            return True
        if area and any(non_it in area for non_it in self.NON_IT_LEGAL_AREAS):
            return False
        return True

    def _select_candidate_evidence(
        self,
        duty: ParsedDuty,
        clause: RequirementClause,
        exclusion_map: dict[str, ExclusionLogItem],
        reviewed_scores: dict[str, float],
    ) -> List[ScoredEvidence]:
        """
        Include all active, in-domain DMS policy/evidence sections from the bounded starter set
        PLUS the top-ranked register rows and fact/questionnaire records matching the specific clause.
        Tracks per-file best relevance score for the duty's search audit log.
        """
        all_scored = self.retriever.score_all(f"{duty.title}. {clause.text}")
        candidates: List[ScoredEvidence] = []
        seen_ids: set[str] = set()
        register_hits_added = 0
        catalog_hits_added = 0

        for rank_idx, hit in enumerate(all_scored):
            u = hit.unit
            prev_best = reviewed_scores.get(u.file_path, -1.0)
            if hit.score > prev_best:
                reviewed_scores[u.file_path] = hit.score

            if not self._is_domain_compatible(duty, hit):
                continue

            if u.is_future_dated:
                exclusion_map[u.source_id] = ExclusionLogItem(
                    source_id=u.source_id,
                    file_path=u.file_path,
                    disposition="not_yet_effective",
                    reason=u.future_date_reason or f"Effective date {u.effective_date} is after {self.as_of_str}.",
                )
                continue

            if u.is_superseded:
                exclusion_map[u.source_id] = ExclusionLogItem(
                    source_id=u.source_id,
                    file_path=u.file_path,
                    disposition="historical_only",
                    reason=(
                        f"Document {u.source_id} (v{u.version or 'unknown'}) was superseded by {u.superseded_by} "
                        f"prior to assessment date {self.as_of_str}."
                    ),
                )
                continue

            if u.is_scope_restricted and (hit.score >= 0.20 or hit.stem_overlap >= 1):
                exclusion_map[u.source_id] = ExclusionLogItem(
                    source_id=u.source_id,
                    file_path=u.file_path,
                    disposition="limited_support",
                    reason=u.scope_restriction_reason or f"Restricted scope on {u.source_id}.",
                )

            include = False
            if u.is_starter_corpus and u.unit_type == "policy_chunk" and u.source_id.startswith("DMS-"):
                include = True
            elif u.unit_type == "register_row":
                if register_hits_added < 8 and (hit.stem_overlap >= 1 or (rank_idx < 6 and hit.score >= 0.25)):
                    include = True
                    register_hits_added += 1
            elif u.unit_type in ("policy_chunk", "twin_qa", "profile_fact"):
                if catalog_hits_added < 6 and (hit.stem_overlap >= 1 or (rank_idx < 5 and hit.score >= 0.25)):
                    include = True
                    catalog_hits_added += 1

            if include and u.unit_id not in seen_ids:
                seen_ids.add(u.unit_id)
                candidates.append(hit)

        return candidates

    def evaluate_duty(self, duty: ParsedDuty) -> DutyComplianceResult:
        components: List[DutyComponent] = []
        exclusion_map: dict[str, ExclusionLogItem] = {}
        reviewed_scores: dict[str, float] = {}

        for c_idx, clause in enumerate(duty.clauses, start=1):
            candidates = self._select_candidate_evidence(duty, clause, exclusion_map, reviewed_scores)
            if self.use_llm:
                comp = self._evaluate_clause_with_llm(
                    duty,
                    clause,
                    candidates,
                    clause_num=c_idx,
                    total_clauses=len(duty.clauses),
                )
            else:
                comp = self._evaluate_clause_conservative_baseline(duty, clause, candidates)
            components.append(comp)

        ranked_sources = [
            fp for fp, _ in sorted(reviewed_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        state = aggregate_duty_state(components)
        reason = self._synthesize_duty_reason(duty, state, components)
        exclusion_list = list(exclusion_map.values())
        decision_influence = self._build_decision_influence(components, exclusion_list)
        actionable_request = (
            self._build_evidence_request(duty, components, ranked_sources)
            if state == ComplianceState.EVIDENCE_MISSING
            else None
        )

        return DutyComplianceResult(
            duty_id=duty.duty_id,
            statutory_ref=duty.statutory_ref,
            duty_title=duty.title,
            state=state,
            reason=reason,
            components=components,
            exclusion_log=exclusion_list,
            actionable_request=actionable_request,
            sources_reviewed=ranked_sources,
            decision_influence=decision_influence,
        )

    def _evaluate_clause_with_llm(
        self,
        duty: ParsedDuty,
        clause: RequirementClause,
        candidates: List[ScoredEvidence],
        clause_num: int = 1,
        total_clauses: int = 1,
    ) -> DutyComponent:
        """
        LLM assesses support, shortfalls, scope, and contradictions across candidate evidence in compact batches,
        with bounded JSON-repair retry and strict deterministic validation of citations, dates, and polarity.
        """
        if not candidates:
            return DutyComponent(
                component_id=clause.clause_id,
                name=clause.name,
                clause_text=clause.text,
                status=ComponentStatus.INSUFFICIENT_EVIDENCE,
                rationale="No active, in-domain candidate evidence found as of assessment date (silence is not a confirmed gap).",
                citations=[],
                limitations=["No matching active evidence in reviewed corpus."],
            )

        batch_size = 8
        batches = [candidates[i : i + batch_size] for i in range(0, len(candidates), batch_size)]
        batch_verdicts: List[DutyComponent] = []

        for b_idx, batch in enumerate(batches, start=1):
            self._log_progress(
                f"  [{duty.duty_id}] Clause {clause_num}/{total_clauses} ({clause.name[:40]}), "
                f"batch {b_idx}/{len(batches)} ({len(batch)} units)..."
            )
            t0 = time.perf_counter()

            evidence_lines: List[str] = []
            for idx, h in enumerate(batch, start=1):
                u = h.unit
                evidence_lines.append(
                    f"[{idx}] source_id={u.source_id} | type={u.unit_type} | status={u.status or 'UNKNOWN'} | "
                    f"date={u.date or 'UNKNOWN'} | effective_date={u.effective_date or 'UNKNOWN'} | "
                    f"scope_restricted={u.is_scope_restricted} | location={u.location}\n"
                    f"    Passage: {u.exact_passage}"
                )

            base_prompt = (
                f"You are a forensic regulatory compliance auditor assessing {self.entity.entity_name}.\n"
                f"Assessment Date (as_of_date): {self.as_of_str}\n"
                f"Duty: {duty.duty_id} ({duty.statutory_ref}) — {duty.title}\n"
                f"Requirement Component: {clause.name} — {clause.text}\n"
                f"Legal Guidance / Interpretation: {duty.evaluation_guidance or 'None'}\n\n"
                "STRICT AUDIT RULES:\n"
                "1. 'supported': ONLY if active, in-scope evidence proves CURRENT fulfillment of this exact requirement as of "
                f"{self.as_of_str}. A future plan ('plan to...', 'geplant') or negated text ('nicht wirksam', 'not effective') is NEVER 'supported'.\n"
                "2. 'confirmed_shortfall': ONLY if active evidence explicitly proves an unfulfilled obligation or breach that is ALREADY due/overdue "
                f"on or before {self.as_of_str}. If an obligation is 'offen'/'open' but its due date is AFTER {self.as_of_str}, it is NOT overdue and NOT a confirmed shortfall ('insufficient_evidence').\n"
                "3. 'conflicting_evidence': ONLY if two sources make mutually incompatible claims about the SAME control, scope, and period. "
                "Completion of an exercise ('exercise completed') plus audit findings ('exposed weaknesses') are NOT contradictory—distinguish execution from effectiveness.\n"
                "4. 'insufficient_evidence': When evidence is missing, partial, scope-restricted, describes a future plan, shows execution without effectiveness, or has a blank questionnaire without a valid supporting record. "
                "If a questionnaire entry is blank/unanswered BUT another valid source in the batch supports the requirement, evaluate the valid supporting source!\n"
                "5. Return compact valid JSON ONLY with schema:\n"
                '   {"status": "supported|confirmed_shortfall|insufficient_evidence|conflicting_evidence", '
                '"rationale": "1-2 concise sentences", "cited_indices": [1], "limitations": ["max 2 short distinct strings, no repetition"]}\n'
                f"6. Every index in 'cited_indices' MUST be an integer between 1 and {len(batch)}.\n\n"
                "CANDIDATE EVIDENCE:\n" + "\n".join(evidence_lines)
            )

            assert self.llm_client is not None
            parsed: Optional[dict] = None
            last_err: Optional[Exception] = None
            raw_response = ""

            for attempt in range(1, 4):
                prompt = (
                    base_prompt
                    if attempt == 1
                    else base_prompt
                    + "\n\nIMPORTANT: Your previous response was invalid or truncated JSON. "
                    "Output strictly valid, compact JSON with a 1-sentence rationale and at most 2 short non-repeating limitations."
                )
                raw_response = self.llm_client(prompt)
                try:
                    candidate_parsed = parse_llm_json_response(raw_response)
                    if not isinstance(candidate_parsed, dict):
                        raise ValueError("LLM JSON root is not an object.")
                    parsed = candidate_parsed
                    break
                except (json.JSONDecodeError, ValueError) as exc:
                    last_err = exc
                    self._log_progress(f"    ! JSON parse retry {attempt}/2 for {clause.clause_id} batch {b_idx}...")

            elapsed = time.perf_counter() - t0
            self._log_progress(f"    -> completed in {elapsed:.1f}s")

            if parsed is None:
                raise ValueError(
                    f"LLM returned invalid JSON for {clause.clause_id} after retries: {raw_response}"
                ) from last_err

            raw_status = parsed.get("status")
            valid_statuses = {s.value for s in ComponentStatus}
            if raw_status not in valid_statuses:
                raise ValueError(f"LLM returned invalid status '{raw_status}' for {clause.clause_id}.")

            raw_indices = parsed.get("cited_indices")
            if not isinstance(raw_indices, list):
                raise ValueError(f"LLM response for {clause.clause_id} missing 'cited_indices' list.")

            cited_hits: List[ScoredEvidence] = []
            for idx in raw_indices:
                if not isinstance(idx, int) or idx < 1 or idx > len(batch):
                    raise ValueError(
                        f"LLM cited out-of-range evidence index {idx} (valid range: 1..{len(batch)}) for {clause.clause_id}. "
                        "Refusing to clamp invalid citation index to an unrelated source."
                    )
                cited_hits.append(batch[idx - 1])

            verdict_status = ComponentStatus(raw_status)
            rationale = str(parsed.get("rationale") or "").strip()
            raw_lims = [str(x).strip() for x in parsed.get("limitations", []) if str(x).strip()]
            limitations = list(dict.fromkeys(raw_lims))[:4]

            verdict_status, rationale, limitations, cited_hits = self._post_validate_verdict(
                clause=clause,
                status=verdict_status,
                rationale=rationale,
                limitations=limitations,
                cited_hits=cited_hits,
                batch=batch,
            )

            citations = [
                self._to_citation(h, demonstrates=rationale or f"Evaluated as {verdict_status.value}.")
                for h in cited_hits
            ]

            batch_verdicts.append(
                DutyComponent(
                    component_id=clause.clause_id,
                    name=clause.name,
                    clause_text=clause.text,
                    status=verdict_status,
                    rationale=rationale,
                    citations=citations,
                    limitations=limitations,
                )
            )

        if len(batch_verdicts) == 1:
            return batch_verdicts[0]

        for preferred_status in (
            ComponentStatus.CONFIRMED_SHORTFALL,
            ComponentStatus.CONFLICTING,
            ComponentStatus.SUPPORTED,
        ):
            matched = [bv for bv in batch_verdicts if bv.status == preferred_status]
            if matched:
                return matched[0]
        return batch_verdicts[0]

    def _post_validate_verdict(
        self,
        clause: RequirementClause,
        status: ComponentStatus,
        rationale: str,
        limitations: List[str],
        cited_hits: List[ScoredEvidence],
        batch: Optional[List[ScoredEvidence]] = None,
    ) -> tuple[ComponentStatus, str, List[str], List[ScoredEvidence]]:
        """Enforce hard legal & temporal invariants on top of the LLM's assessment."""
        if status == ComponentStatus.SUPPORTED:
            if not cited_hits:
                return (
                    ComponentStatus.INSUFFICIENT_EVIDENCE,
                    "Deterministic validator downgraded 'supported' because zero citations were provided.",
                    limitations + ["Affirmative compliance requires at least one valid citation."],
                    cited_hits,
                )
            for h in cited_hits:
                combined_text = f"{h.unit.status or ''} {h.unit.exact_passage}"
                if TextPolarityAnalyzer.has_negation(combined_text):
                    return (
                        ComponentStatus.INSUFFICIENT_EVIDENCE,
                        f"Cited evidence in {h.unit.source_id} contains negated compliance/effectiveness language ('{h.unit.exact_passage}') and cannot support fulfillment.",
                        limitations + ["Negated effectiveness/compliance statement cannot establish fulfillment."],
                        cited_hits,
                    )
                if TextPolarityAnalyzer.is_future_plan_only(h.unit.exact_passage):
                    return (
                        ComponentStatus.INSUFFICIENT_EVIDENCE,
                        f"Cited evidence in {h.unit.source_id} describes a future plan rather than current implementation.",
                        limitations + ["Future plans do not establish current compliance."],
                        cited_hits,
                    )
                if clause.requires_entity_wide_scope and h.unit.is_scope_restricted:
                    return (
                        ComponentStatus.INSUFFICIENT_EVIDENCE,
                        f"Cited evidence in {h.unit.source_id} is scope-restricted and does not cover all entity sites.",
                        limitations + ["Entity-wide scope not established."],
                        cited_hits,
                    )

        if status == ComponentStatus.CONFIRMED_SHORTFALL:
            for h in cited_hits:
                due_raw = (
                    h.unit.structured_fields.get("Next due")
                    or h.unit.structured_fields.get("Due date")
                    or h.unit.structured_fields.get("Fällig")
                )
                due_dt = parse_iso_or_de_date(due_raw)
                if due_dt is not None and due_dt > self.as_of:
                    return (
                        ComponentStatus.INSUFFICIENT_EVIDENCE,
                        f"Obligation in {h.unit.source_id} has future due date {due_dt.isoformat()} (after {self.as_of_str}) and is not yet overdue.",
                        limitations + [f"Future deadline {due_dt.isoformat()} is not an active shortfall as of {self.as_of_str}."],
                        cited_hits,
                    )

        if status == ComponentStatus.INSUFFICIENT_EVIDENCE:
            inspect_pool: List[ScoredEvidence] = list(cited_hits)
            if batch:
                seen = {h.unit.unit_id for h in inspect_pool}
                for h in batch:
                    if h.unit.unit_id in seen:
                        continue
                    subj = (
                        h.unit.structured_fields.get("Obligation")
                        or h.unit.structured_fields.get("Control")
                        or h.unit.exact_passage
                    )
                    if self._matches_obligation_subject(clause, subj):
                        inspect_pool.append(h)

            for h in inspect_pool:
                u = h.unit
                if u.unit_type != "register_row":
                    continue
                if "risk_register" in u.source_id.lower() or "risikoregister" in u.document_title.lower():
                    continue
                status_val = (u.status or "").lower()
                if any(tok in status_val for tok in self.OPEN_STATUS_TOKENS):
                    due_raw = (
                        u.structured_fields.get("Next due")
                        or u.structured_fields.get("Due date")
                        or u.structured_fields.get("Fällig")
                    )
                    due_dt = parse_iso_or_de_date(due_raw)
                    if due_dt is None or due_dt <= self.as_of:
                        overdue_note = f" (due {due_dt.isoformat()}, overdue as of {self.as_of_str})" if due_dt else ""
                        updated_hits = cited_hits if h in cited_hits else [h] + cited_hits
                        return (
                            ComponentStatus.CONFIRMED_SHORTFALL,
                            f"Register {u.source_id} confirms an unfulfilled obligation with status '{u.status}'{overdue_note}: {u.exact_passage}",
                            limitations,
                            updated_hits,
                        )

        return status, rationale, limitations, cited_hits

    @staticmethod
    def _matches_obligation_subject(clause: RequirementClause, subject_text: str) -> bool:
        """Compound-aware German/English subject check so unrelated open obligations never leak across duties."""
        clause_stems = extract_specific_stems(clause.text)
        if not clause_stems:
            return False
        subject_lower = subject_text.lower()
        return any(stem in subject_lower for stem in clause_stems)

    def _evaluate_clause_conservative_baseline(
        self,
        duty: ParsedDuty,
        clause: RequirementClause,
        candidates: List[ScoredEvidence],
    ) -> DutyComponent:
        """
        Explicit non-LLM baseline (--no-llm).
        Strictly forbids defaulting relevant passages to SUPPORTED; only marks CONFIRMED_SHORTFALL
        when an in-domain obligations register entry explicitly matches the clause subject, is open,
        and is already due/overdue on or before as_of_date.
        """
        in_scope = [h for h in candidates if not h.unit.is_scope_restricted]

        for h in in_scope:
            u = h.unit
            if u.unit_type != "register_row":
                continue
            if "risk_register" in u.source_id.lower() or "risikoregister" in u.document_title.lower():
                continue

            subject_text = (
                u.structured_fields.get("Obligation")
                or u.structured_fields.get("Control")
                or u.exact_passage
            )
            if not self._matches_obligation_subject(clause, subject_text):
                continue

            status_val = (u.status or "").lower()
            due_raw = (
                u.structured_fields.get("Next due")
                or u.structured_fields.get("Due date")
                or u.structured_fields.get("Fällig")
            )
            due_dt = parse_iso_or_de_date(due_raw)

            if any(tok in status_val for tok in self.OPEN_STATUS_TOKENS):
                if due_dt is not None and due_dt > self.as_of:
                    return DutyComponent(
                        component_id=clause.clause_id,
                        name=clause.name,
                        clause_text=clause.text,
                        status=ComponentStatus.INSUFFICIENT_EVIDENCE,
                        rationale=(
                            f"Register {u.source_id} lists status '{u.status}' with future deadline "
                            f"{due_dt.isoformat()} (not overdue as of {self.as_of_str})."
                        ),
                        citations=[self._to_citation(h, f"Upcoming obligation due {due_dt.isoformat()}.")],
                        limitations=["Future deadline is not yet overdue."],
                    )

                overdue_note = f" and overdue since {due_dt.isoformat()}" if due_dt else ""
                return DutyComponent(
                    component_id=clause.clause_id,
                    name=clause.name,
                    clause_text=clause.text,
                    status=ComponentStatus.CONFIRMED_SHORTFALL,
                    rationale=f"Register {u.source_id} records '{u.exact_passage}' with status '{u.status}'{overdue_note}.",
                    citations=[self._to_citation(h, f"Confirmed shortfall: status '{u.status}'{overdue_note}.")],
                    limitations=["Active obligations register confirms unfulfilled obligation."],
                )

        cits = [
            self._to_citation(h, "Candidate context retrieved; LLM semantic verification disabled.")
            for h in in_scope[:2]
        ]
        return DutyComponent(
            component_id=clause.clause_id,
            name=clause.name,
            clause_text=clause.text,
            status=ComponentStatus.INSUFFICIENT_EVIDENCE,
            rationale="LLM semantic evaluation is disabled (--no-llm); retrieved passages are not assumed to establish fulfillment without AI interpretation.",
            citations=cits,
            limitations=["Run with LLM evaluation enabled to verify whether candidate passages establish full compliance."],
        )

    def _build_decision_influence(
        self,
        components: List[DutyComponent],
        exclusions: List[ExclusionLogItem],
    ) -> List[str]:
        """Summarize how document versions, effective dates, and register statuses shaped the decision."""
        notes: List[str] = []
        for ex in exclusions:
            if ex.disposition == "historical_only":
                notes.append(f"Version supersession: {ex.reason}")
            elif ex.disposition == "not_yet_effective":
                notes.append(f"Effective-date boundary: {ex.reason}")
            elif ex.disposition == "limited_support":
                notes.append(f"Scope boundary: {ex.reason}")

        seen_citations: set[str] = set()
        for comp in components:
            for cit in comp.citations:
                key = f"{cit.source_id}|{cit.location}"
                if key in seen_citations:
                    continue
                seen_citations.add(key)
                ver_txt = f"v{cit.version}" if cit.version else "unversioned"
                eff_txt = f", effective/date {cit.effective_date or cit.date}" if (cit.effective_date or cit.date) else ""
                st_txt = f", status '{cit.status}'" if cit.status else ""
                notes.append(
                    f"Cited record {cit.source_id} ({cit.location}, {ver_txt}{eff_txt}{st_txt}) -> "
                    f"contributed to component '{comp.name}' ({comp.status.value})."
                )

        if not notes:
            notes.append(
                f"No superseded versions or matching active register entries altered the baseline evaluation as of {self.as_of_str}."
            )
        return notes

    @staticmethod
    def _to_citation(hit: ScoredEvidence, demonstrates: str) -> EvidenceCitation:
        u = hit.unit
        return EvidenceCitation(
            source_id=u.source_id,
            document_title=u.document_title,
            file_path=u.file_path,
            version=u.version,
            date=u.date,
            effective_date=u.effective_date,
            status=u.status,
            exact_passage=u.exact_passage,
            location=u.location,
            demonstrates=demonstrates,
            retrieval_score=round(hit.score, 4),
        )

    @staticmethod
    def _synthesize_duty_reason(
        duty: ParsedDuty,
        state: ComplianceState,
        components: List[DutyComponent],
    ) -> str:
        supported = [c.name for c in components if c.status == ComponentStatus.SUPPORTED]
        shortfalls = [c for c in components if c.status == ComponentStatus.CONFIRMED_SHORTFALL]
        missing = [c for c in components if c.status in (ComponentStatus.INSUFFICIENT_EVIDENCE, ComponentStatus.CONFLICTING)]

        if state == ComplianceState.OPEN:
            prefix = f"Supported aspects ({', '.join(supported)}) exist, however " if supported else ""
            details = "; ".join(c.rationale for c in shortfalls)
            return f"{prefix}confirmed shortfall identified: {details}"

        if state == ComplianceState.MET:
            return f"All {len(components)} decomposed requirements for '{duty.title}' are supported by active, in-scope evidence."

        prefix = f"Supported aspects ({', '.join(supported)}) verified, but full compliance cannot yet be established: " if supported else ""
        details = "; ".join(f"{c.name}: {c.rationale}" for c in missing[:2])
        return f"{prefix}{details}"

    def _build_evidence_request(
        self,
        duty: ParsedDuty,
        components: List[DutyComponent],
        reviewed_sources: List[str],
    ) -> EvidenceRequest:
        unresolved = [
            c for c in components
            if c.status in (ComponentStatus.INSUFFICIENT_EVIDENCE, ComponentStatus.CONFLICTING)
        ]
        missing_summary = "; ".join(f"{c.name} ({c.rationale})" for c in unresolved)
        clause_topics = ", ".join(c.name for c in unresolved)
        cited_ids = sorted({cit.source_id for c in unresolved for cit in c.citations})
        ref_note = f" (reconciling {', '.join(cited_ids)})" if cited_ids else ""

        question = (
            f"For {self.entity.entity_name} under {duty.statutory_ref} ({duty.title}), please provide verifiable "
            f"operational records, test logs, or scope-complete documentation covering: {clause_topics}{ref_note}."
        )
        return EvidenceRequest(
            duty_id=duty.duty_id,
            duty_title=duty.title,
            sources_reviewed=reviewed_sources,
            missing_fact=missing_summary,
            focused_question=question,
        )