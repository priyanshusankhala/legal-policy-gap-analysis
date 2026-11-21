"""
Lossless Legal Duty Parser & Requirement Decomposer.
Loads supplied duties and legal interpretation rules without truncating requirements,
inventing statutory references, or matching broad substrings like 'ot'.
Supports optional LLM-assisted decomposition with verbatim source-quote verification.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from src.loader import DataLoader


@dataclass
class RequirementClause:
    clause_id: str
    name: str
    text: str
    source_quote: str
    requires_operational_proof: bool
    requires_entity_wide_scope: bool


@dataclass
class ParsedDuty:
    duty_id: str
    statutory_ref: str
    title: str
    description: str
    evaluation_guidance: str
    domain: str = "informationssicherheit"
    clauses: List[RequirementClause] = field(default_factory=list)


class DutyParser:
    """Extracts primary duties, supporting legal context, and verified requirement clauses."""

    OPERATIONAL_PROOF_PATTERN = re.compile(
        r"\b(durchführung|durchgeführt|nachweis|messung|messwert|übung|test|prüfung|"
        r"wirksamkeit|protokoll|wiederanlauf|restore|rto|rpo|drill|execution|operational|"
        r"effectiveness|audit|regelmäßig|jährlich|periodic|annual|verify|beleg)\b",
        re.IGNORECASE,
    )

    SCOPE_PATTERN = re.compile(
        r"\b(alle standorte|gesamtunternehmen|produktion|ot|ics|scada|"
        r"operational technology|produktionssteuerung|leitstand|entity-wide|"
        r"all sites|facilities|geltungsbereich|scope)\b",
        re.IGNORECASE,
    )

    BOILERPLATE_LINES = (
        "definition / gewählte auslegung",
        "gewählte auslegung",
        "prüfhinweis",
        "bewertungshinweis",
    )

    def __init__(
        self,
        loader: DataLoader,
        llm_client: Optional[Callable[[str], str]] = None,
    ):
        self.loader = loader
        self.llm_client = llm_client
        self.supporting_context: List[Dict[str, str]] = []

    def load_duties(self, duty_file: Optional[str] = None) -> List[ParsedDuty]:
        """Discover and parse primary duties from NIS2_selected_duties.json or TXT."""
        candidates = (
            [duty_file]
            if duty_file
            else ["NIS2_selected_duties.json", "NIS2_selected_duties.txt"]
        )
        found_path: Optional[Path] = None
        for name in candidates:
            if not name:
                continue
            found_path = self.loader.resolve_package_file(name)
            if found_path is not None:
                break

        if found_path is None:
            raise FileNotFoundError(
                "Could not locate NIS2_selected_duties.json or NIS2_selected_duties.txt in input directory."
            )

        if found_path.suffix.lower() == ".json":
            raw = self.loader.load_json_path(found_path)
            return self._parse_json_duties(raw)
        return self._parse_txt_duties(found_path)

    @classmethod
    def _extract_duty_dicts(cls, node: Any) -> List[Dict[str, Any]]:
        """Recursively locate the list of duty objects in the JSON schema."""
        if isinstance(node, list):
            return [x for x in node if isinstance(x, dict)]

        if isinstance(node, dict):
            for key in ("duties", "selected_duties", "items", "records", "obligations"):
                val = node.get(key)
                if isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
                    return val

            for val in node.values():
                if isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
                    return val

            dict_vals = [v for v in node.values() if isinstance(v, dict)]
            if dict_vals and any(
                any(k in d for k in ("duty_id", "source_id", "duty_title", "source_label_de", "title", "statutory_ref"))
                for d in dict_vals
            ):
                return dict_vals

            for val in node.values():
                if isinstance(val, (dict, list)):
                    found = cls._extract_duty_dicts(val)
                    if found:
                        return found
        return []

    @staticmethod
    def _extract_statutory_ref(item: Dict[str, Any], raw_title: str, description: str) -> str:
        """Extract statutory citation if present; never fabricate one when absent."""
        explicit = (
            item.get("statutory_ref")
            or item.get("legal_ref")
            or item.get("norm")
            or item.get("reference")
            or item.get("provision")
            or item.get("article")
        )
        if explicit and str(explicit).strip():
            return str(explicit).strip()

        for blob in (raw_title, description):
            m = re.search(
                r"(§\s*\d+\s*(?:Abs\.\s*\d+)?\s*(?:Nr\.\s*\d+)?\s*[A-ZÄÖÜa-zäöüß]*)",
                blob,
            )
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()

        return "Not specified"

    @staticmethod
    def _clean_title(duty_id: str, statutory_ref: str, raw_title: str) -> str:
        title = raw_title
        for prefix in (duty_id, statutory_ref):
            if prefix and prefix != "Not specified":
                title = re.sub(r"^" + re.escape(prefix) + r"[\s·:\-–]*", "", title).strip()
        return title or raw_title

    @staticmethod
    def _strip_header_prefix(text: str, duty_id: str, statutory_ref: str, title: str) -> str:
        cleaned = text.strip()
        for _ in range(3):
            prev = cleaned
            for prefix in (duty_id, statutory_ref, title):
                if prefix and prefix != "Not specified":
                    cleaned = re.sub(r"^" + re.escape(prefix) + r"[\s·:\-–.]*", "", cleaned).strip()
            if cleaned == prev:
                break
        return cleaned or text.strip()

    @staticmethod
    def _infer_domain(statutory_ref: str, title: str, description: str) -> str:
        blob = f"{statutory_ref} {title} {description}".lower()
        if any(k in blob for k in ("bsig", "nis2", "it-sicherheit", "informationssicherheit", "cyber", "backup", "vorfall")):
            return "informationssicherheit"
        if any(k in blob for k in ("dsgvo", "datenschutz", "gdpr")):
            return "datenschutz"
        return "general"

    def _partition_primary_and_context(
        self, items: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Separate primary operative duties from umbrella provisions and interpretation rules."""
        def _item_header(it: Dict[str, Any]) -> str:
            return " ".join(
                str(it.get(k) or "")
                for k in (
                    "duty_id",
                    "source_id",
                    "id",
                    "duty_title",
                    "source_label_de",
                    "label_de",
                    "title_de",
                    "title",
                    "statutory_ref",
                )
            )

        has_specific_nr = any(
            re.search(r"\bNr\.\s*\d+\b", _item_header(item))
            for item in items
        )

        primary: List[Dict[str, Any]] = []
        context: List[Dict[str, Any]] = []

        for item in items:
            header = _item_header(item)
            blob = " ".join(str(v) for v in item.values())
            item_id = str(item.get("duty_id") or item.get("source_id") or item.get("id") or "")
            item_type = str(item.get("type") or item.get("kind") or item.get("role") or "").lower()

            is_interpretation = (
                "-AUS-" in item_id.upper()
                or "auslegung" in item_type
                or "definition" in item_type
                or "gewählte auslegung" in blob.lower()
            )
            is_umbrella = (
                has_specific_nr
                and bool(re.search(r"Abs\.\s*1\b", header))
                and not bool(re.search(r"\bNr\.\s*\d+\b", header))
            )

            if is_interpretation or is_umbrella:
                context.append(item)
            else:
                primary.append(item)

        if not primary:
            return items, []
        return primary, context

    def _parse_json_duties(self, raw: Any) -> List[ParsedDuty]:
        items = self._extract_duty_dicts(raw)
        if not items:
            raise ValueError("No duty records found inside duty JSON file.")

        primary_items, context_items = self._partition_primary_and_context(items)
        self.supporting_context = [
            {
                "id": str(c.get("duty_id") or c.get("source_id") or c.get("id") or ""),
                "label": str(c.get("source_label_de") or c.get("duty_title") or c.get("title") or ""),
                "text": str(c.get("description_de") or c.get("text_de") or c.get("description") or ""),
            }
            for c in context_items
        ]
        context_guidance = "\n".join(
            f"[{c['id']}] {c['label']}: {c['text']}"
            for c in self.supporting_context
            if c["text"]
        ).strip()

        duties: List[ParsedDuty] = []
        for idx, item in enumerate(primary_items, start=1):
            duty_id = str(
                item.get("duty_id")
                or item.get("source_id")
                or item.get("id")
                or item.get("code")
                or f"DUTY-{idx:02d}"
            ).strip()
            raw_title = str(
                item.get("duty_title")
                or item.get("source_label_de")
                or item.get("label_de")
                or item.get("title_de")
                or item.get("title")
                or item.get("name")
                or duty_id
            ).strip()
            raw_description = str(
                item.get("description_de")
                or item.get("duty_text_de")
                or item.get("text_de")
                or item.get("description")
                or item.get("text")
                or item.get("requirement")
                or raw_title
            ).strip()
            guidance = str(
                item.get("evaluation_guidance_de")
                or item.get("evaluation_guidance")
                or item.get("guidance_de")
                or item.get("guidance")
                or item.get("criteria")
                or ""
            ).strip()
            if context_guidance:
                guidance = f"{guidance}\n{context_guidance}".strip()

            statutory_ref = self._extract_statutory_ref(item, raw_title, raw_description)
            title = self._clean_title(duty_id, statutory_ref, raw_title)
            description = self._strip_header_prefix(raw_description, duty_id, statutory_ref, title)
            domain = self._infer_domain(statutory_ref, title, description)

            explicit_sub = (
                item.get("components")
                or item.get("sub_requirements")
                or item.get("requirements")
                or item.get("criteria_list")
            )
            clauses = self._decompose_clauses(
                duty_id=duty_id,
                title=title,
                description=description,
                guidance=guidance,
                explicit_sub=explicit_sub,
            )
            duties.append(
                ParsedDuty(
                    duty_id=duty_id,
                    statutory_ref=statutory_ref,
                    title=title,
                    description=description,
                    evaluation_guidance=guidance,
                    domain=domain,
                    clauses=clauses,
                )
            )
        return duties

    def _parse_txt_duties(self, path: Path) -> List[ParsedDuty]:
        full_text = path.read_text(encoding="utf-8-sig")
        blocks = re.split(r"\n(?=#{1,3}\s+|\d+\.\s+|Duty\s+ID:|source_id:)", full_text.strip())
        duties: List[ParsedDuty] = []

        for idx, block in enumerate(blocks, start=1):
            block = block.strip()
            if not block:
                continue
            id_match = re.search(r"\b(\d{2}-[A-Z]\d{2}-\d+)\b", block)
            duty_id = id_match.group(1) if id_match else f"DUTY-{idx:02d}"
            ref_match = re.search(r"(§\s*\d+[^\n,;]*)", block)
            statutory_ref = ref_match.group(1).strip() if ref_match else "Not specified"
            first_line = block.splitlines()[0].lstrip("#").strip()
            title = re.sub(r"^" + re.escape(duty_id) + r"[:\s\-–]*", "", first_line).strip() or duty_id

            clauses = self._decompose_clauses(
                duty_id=duty_id,
                title=title,
                description=block,
                guidance="",
                explicit_sub=None,
            )
            duties.append(
                ParsedDuty(
                    duty_id=duty_id,
                    statutory_ref=statutory_ref,
                    title=title,
                    description=block,
                    evaluation_guidance="",
                    clauses=clauses,
                )
            )
        return duties

    def _llm_decompose_with_verification(
        self,
        duty_id: str,
        title: str,
        description: str,
        guidance: str,
    ) -> Optional[List[RequirementClause]]:
        """Decompose a duty via LLM and verify each component cites a verbatim legal passage."""
        if self.llm_client is None:
            return None

        source_corpus = f"{title}\n{description}"
        prompt = (
            "Decompose the following legal duty into atomic, non-overlapping requirement components.\n"
            'Return JSON: {"components": [{"name": "...", "text": "...", "exact_legal_quote": "..."}]}.\n'
            "Rules:\n"
            "1. Do NOT omit any obligation or sub-requirement.\n"
            "2. 'exact_legal_quote' MUST be a verbatim substring from the provided title or description.\n"
            "3. Keep 'name' short (max 6 words).\n\n"
            f"Duty ID: {duty_id}\nTitle: {title}\nDescription: {description}\nGuidance: {guidance}\n"
        )
        raw_out = self.llm_client(prompt)
        try:
            cleaned = raw_out.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

        comp_list = parsed.get("components")
        if not isinstance(comp_list, list) or not comp_list:
            return None

        verified: List[RequirementClause] = []
        for idx, entry in enumerate(comp_list, start=1):
            if not isinstance(entry, dict):
                return None
            quote = str(entry.get("exact_legal_quote") or "").strip()
            if not quote or quote not in source_corpus:
                return None
            text = str(entry.get("text") or quote).strip()
            name = str(entry.get("name") or text[:60]).strip()
            lower = f"{text} {guidance}"
            verified.append(
                RequirementClause(
                    clause_id=f"{duty_id}.C{idx}",
                    name=name,
                    text=text,
                    source_quote=quote,
                    requires_operational_proof=bool(self.OPERATIONAL_PROOF_PATTERN.search(lower)),
                    requires_entity_wide_scope=bool(self.SCOPE_PATTERN.search(lower)),
                )
            )
        return verified

    def _decompose_clauses(
        self,
        duty_id: str,
        title: str,
        description: str,
        guidance: str,
        explicit_sub: Any,
    ) -> List[RequirementClause]:
        if explicit_sub is None and self.llm_client is not None:
            llm_clauses = self._llm_decompose_with_verification(duty_id, title, description, guidance)
            if llm_clauses:
                return llm_clauses

        raw_items: List[Tuple[str, str]] = []

        if isinstance(explicit_sub, list) and explicit_sub:
            for sub in explicit_sub:
                if isinstance(sub, dict):
                    txt = str(sub.get("text") or sub.get("description") or sub.get("name") or "").strip()
                else:
                    txt = str(sub).strip()
                if txt:
                    raw_items.append((txt, txt))
        else:
            combined = description if description.lower().startswith(title.lower()) else f"{title}. {description}".strip()
            segments = re.split(
                r"(?:\n\s*[-*•]\s+|\n\s*\d+[\.)]\s+|;\s+|\.\s+(?=[A-ZÄÖÜ]))",
                combined,
            )
            cleaned: List[str] = []
            for seg in segments:
                s = re.sub(r"\s+", " ", seg).strip(" .;-")
                if len(s) < 18:
                    continue
                if any(bp in s.lower() for bp in self.BOILERPLATE_LINES):
                    continue
                if s not in cleaned:
                    cleaned.append(s)

            if len(cleaned) <= 1:
                parts = re.split(r"\s+(?:und|sowie|einschließlich|and|including)\s+|,\s+", title)
                parts = [p.strip() for p in parts if len(p.strip()) >= 6]
                if len(parts) >= 2:
                    raw_items = [(f"{p}: {description}", p) for p in parts]
                else:
                    raw_items = [(combined, description)]
            else:
                raw_items = [(seg, seg) for seg in cleaned]

        clauses: List[RequirementClause] = []
        for idx, (text, quote) in enumerate(raw_items, start=1):
            lower = f"{text} {guidance}"
            if len(raw_items) == 1:
                short_name = title
            elif ":" in text:
                short_name = text.split(":")[0].strip()
            else:
                short_name = text[:80].rstrip(" ,.")
            clauses.append(
                RequirementClause(
                    clause_id=f"{duty_id}.C{idx}",
                    name=short_name,
                    text=text,
                    source_quote=quote,
                    requires_operational_proof=bool(self.OPERATIONAL_PROOF_PATTERN.search(lower)),
                    requires_entity_wide_scope=bool(self.SCOPE_PATTERN.search(lower)),
                )
            )
        return clauses