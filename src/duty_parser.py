"""
Dynamic Legal Duty Parser & Requirement Decomposer.
Separates primary operative duties from umbrella provisions and legal interpretation rules
(e.g., Auslegung / Definition) without hardcoding duty IDs.
"""
from pathlib import Path
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from src.loader import DataLoader


@dataclass
class RequirementClause:
    clause_id: str
    name: str
    text: str
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
    """Extracts primary duties, supporting legal context, and atomic requirement clauses."""

    OPERATIONAL_PROOF_CUES = (
        "durchführung", "durchgeführt", "nachweis", "messung", "messwert", "übung",
        "test", "prüfung", "wirksamkeit", "protokoll", "wiederanlauf", "restore",
        "rto", "rpo", "drill", "execution", "operational", "effectiveness", "audit",
        "regelmäßig", "jährlich", "periodic", "annual", "verify", "beleg",
    )

    SCOPE_CUES = (
        "alle standorte", "gesamtunternehmen", "produktion", "ot", "ics", "scada",
        "entity-wide", "all sites", "facilities", "geltungsbereich", "scope",
    )

    BOILERPLATE_LINES = (
        "definition / gewählte auslegung",
        "gewählte auslegung",
        "prüfhinweis",
        "bewertungshinweis",
    )

    def __init__(self, loader: DataLoader):
        self.loader = loader
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
        """Recursively find the list of duty dictionaries inside any JSON wrapper."""
        if isinstance(node, list):
            return [x for x in node if isinstance(x, dict)]

        if isinstance(node, dict):
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
        explicit = (
            item.get("statutory_ref")
            or item.get("legal_ref")
            or item.get("norm")
            or item.get("reference")
            or item.get("provision")
            or item.get("article")
        )
        if explicit:
            return str(explicit).strip()
        for blob in (raw_title, description):
            m = re.search(r"(§\s*\d+\s*(?:Abs\.\s*\d+)?\s*(?:Nr\.\s*\d+)?\s*[A-ZÄÖÜa-zäöüß]*)", blob)
            if m:
                return re.sub(r"\s+", " ", m.group(1)).strip()
        return "§ 30 Abs. 2 BSIG"

    @staticmethod
    def _clean_title(duty_id: str, statutory_ref: str, raw_title: str) -> str:
        title = raw_title
        if title.startswith(duty_id):
            title = title[len(duty_id):].lstrip(" ·:-–")
        if statutory_ref and title.startswith(statutory_ref):
            title = title[len(statutory_ref):].lstrip(" ·:-–")
        return title.strip() or raw_title

    @staticmethod
    def _infer_domain(statutory_ref: str, title: str, description: str) -> str:
        blob = f"{statutory_ref} {title} {description}".lower()
        if any(k in blob for k in ("bsig", "nis2", "it-sicherheit", "informationssicherheit", "cyber", "backup", "vorfall")):
            return "informationssicherheit"
        if any(k in blob for k in ("dsgvo", "datenschutz", "gdpr")):
            return "datenschutz"
        return "informationssicherheit"
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
            raise ValueError("No duty records found inside NIS2_selected_duties.json")

        primary_items, context_items = self._partition_primary_and_context(items)
        self.supporting_context = [
            {
                "id": str(c.get("duty_id") or c.get("source_id") or c.get("id") or ""),
                "label": str(c.get("source_label_de") or c.get("duty_title") or c.get("title") or ""),
                "text": str(c.get("description_de") or c.get("text_de") or c.get("description") or ""),
            }
            for c in context_items
        ]
        context_guidance = " ".join(c["text"] for c in self.supporting_context if c["text"]).strip()

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
            description = str(
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
                guidance = f"{guidance} {context_guidance}".strip()

            statutory_ref = self._extract_statutory_ref(item, raw_title, description)
            title = self._clean_title(duty_id, statutory_ref, raw_title)
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
            statutory_ref = ref_match.group(1).strip() if ref_match else "§ 30 Abs. 2 BSIG"
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

    def _decompose_clauses(
        self,
        duty_id: str,
        title: str,
        description: str,
        guidance: str,
        explicit_sub: Any,
    ) -> List[RequirementClause]:
        raw_texts: List[str] = []

        if isinstance(explicit_sub, list) and explicit_sub:
            for sub in explicit_sub:
                if isinstance(sub, dict):
                    txt = sub.get("text") or sub.get("description") or sub.get("name") or str(sub)
                else:
                    txt = str(sub)
                if txt.strip():
                    raw_texts.append(txt.strip())
        else:
            combined = f"{title}. {description}".strip()
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
                    cleaned = [f"{p}: {description}" for p in parts[:4]]

            raw_texts = cleaned[:4] if cleaned else [combined]

        clauses: List[RequirementClause] = []
        for idx, text in enumerate(raw_texts, start=1):
            lower = f"{text} {guidance}".lower()
            short_name = text.split(":")[0].strip() if ":" in text else text[:72].rstrip(" ,.")
            clauses.append(
                RequirementClause(
                    clause_id=f"{duty_id}.C{idx}",
                    name=short_name,
                    text=text,
                    requires_operational_proof=any(cue in lower for cue in self.OPERATIONAL_PROOF_CUES),
                    requires_entity_wide_scope=any(cue in lower for cue in self.SCOPE_CUES),
                )
            )
        return clauses