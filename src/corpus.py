"""
Entity-Scoped Corpus Builder, Version Resolver & Scope Analyzer.
Dynamically ingests:
- company_profile.json & legal_entities.csv
- twin_questions.csv (filtered to target legal entity)
- document_starters.csv (or full documents_index.csv)
Automatically detects document version supersession and domain/site scope limits,
and extracts verbatim passages with exact 1-based line numbers.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from src.loader import DataLoader


@dataclass
class EvidenceUnit:
    unit_id: str
    source_id: str
    document_title: str
    file_path: str
    unit_type: str  # policy_chunk | register_row | record_chunk | twin_qa | profile_fact
    text: str
    exact_passage: str
    location: str
    version: Optional[str] = None
    date: Optional[str] = None
    status: Optional[str] = None
    scope_or_area: Optional[str] = None
    structured_fields: Dict[str, str] = field(default_factory=dict)
    is_superseded: bool = False
    superseded_by: Optional[str] = None
    is_scope_restricted: bool = False
    scope_restriction_reason: Optional[str] = None


@dataclass
class EntityContext:
    entity_name: str
    entity_id: str
    entity_code: str
    country: str
    sites: List[str]
    certifications: List[str]


class CorpusBuilder:
    """Builds a clean, provenance-preserving evidence index for the target entity."""

    def __init__(self, loader: DataLoader, target_entity_hint: str = "Marenthal Chemie AG"):
        self.loader = loader
        self.target_entity_hint = target_entity_hint
        self.reviewed_files: List[str] = []

    def _record_path(self, path: Path) -> None:
        key = str(path)
        if key not in self.reviewed_files:
            self.reviewed_files.append(key)

    def _find_data_rel(self, base_name: str) -> Optional[str]:
        for rel in (base_name, f"company_data/{base_name}"):
            resolved = self.loader.try_resolve_path(rel)
            if resolved is not None:
                self._record_path(resolved)
                return rel
        return None

    def load_entity_context(self) -> EntityContext:
        """Resolve target entity metadata from legal_entities.csv and company_profile.json."""
        profile: Dict[str, Any] = {}
        profile_rel = self._find_data_rel("company_profile.json")
        if profile_rel:
            loaded = self.loader.load_json(profile_rel)
            if isinstance(loaded, dict):
                profile = loaded

        entities: List[Dict[str, str]] = []
        entities_rel = self._find_data_rel("legal_entities.csv")
        if entities_rel:
            entities = self.loader.load_csv(entities_rel)

        selected_row: Dict[str, str] = {}
        for row in entities:
            joined = " ".join(row.values()).lower()
            if (
                self.target_entity_hint.lower() in joined
                and ("de" in joined or "germany" in joined or "deutschland" in joined or "ag" in joined)
            ):
                selected_row = row
                break
        if not selected_row and entities:
            selected_row = entities[0]

        entity_name = (
            selected_row.get("legal_name")
            or selected_row.get("entity_name")
            or selected_row.get("name")
            or profile.get("company_name")
            or "Marenthal Chemie AG (DE)"
        )
        country_val = (selected_row.get("country") or selected_row.get("jurisdiction") or "DE").upper()
        if "(DE)" not in entity_name and country_val in ("DE", "GERMANY", "DEUTSCHLAND"):
            entity_name = f"{entity_name} (DE)"

        entity_id = (
            selected_row.get("entity_id")
            or selected_row.get("id")
            or profile.get("entity_id")
            or "CMS-DE-01"
        )
        entity_code = (
            selected_row.get("cms_code")
            or selected_row.get("entity_code")
            or selected_row.get("code")
            or "CMS-DE-01"
        )

        sites: List[str] = []
        for key in ("sites", "locations", "plants", "facilities"):
            val = profile.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        site_country = str(item.get("country", "")).upper()
                        if not site_country or site_country in ("DE", "GERMANY", "DEUTSCHLAND"):
                            sites.append(str(item.get("name") or item.get("city") or item))
                    else:
                        sites.append(str(item))

        certs = [str(c) for c in profile.get("certifications", []) if c]

        return EntityContext(
            entity_name=entity_name,
            entity_id=entity_id,
            entity_code=entity_code,
            country="DE",
            sites=sites,
            certifications=certs,
        )

    def build_corpus(self, entity: EntityContext, full_corpus: bool = False) -> List[EvidenceUnit]:
        """Build all retrievable evidence units for the target entity."""
        units: List[EvidenceUnit] = []
        units.extend(self._extract_profile_units(entity))
        units.extend(self._extract_twin_question_units(entity))

        doc_rel_paths = self._discover_document_paths(entity, full_corpus=full_corpus)
        raw_docs: List[Dict[str, Any]] = []
        for rel in doc_rel_paths:
            resolved = self.loader.try_resolve_path(rel)
            if resolved is None:
                continue
            actual_rel = str(resolved.relative_to(self.loader.base_dir))
            self._record_path(resolved)
            raw_docs.append(self._parse_document_metadata(actual_rel))

        self._resolve_version_families(raw_docs)

        for doc_info in raw_docs:
            units.extend(self._chunk_document(doc_info))

        return units

    @staticmethod
    def _extract_path_from_row(row: Dict[str, str], index_by_id: Dict[str, str]) -> str:
        """Schema-agnostic extraction of a relative document path from any CSV row."""
        for val in row.values():
            if not val:
                continue
            v = val.strip().replace("\\", "/")
            if v.startswith("company_data/"):
                v = v[len("company_data/"):]
            if v.endswith(".txt"):
                return v if v.startswith("documents/") else f"documents/{Path(v).name}"

        for val in row.values():
            if not val:
                continue
            v = val.strip()
            if v in index_by_id:
                return index_by_id[v]
        return ""

    def _discover_document_paths(self, entity: EntityContext, full_corpus: bool) -> List[str]:
        paths: List[str] = []

        index_by_id: Dict[str, str] = {}
        index_rel = self._find_data_rel("documents_index.csv")
        index_rows: List[Dict[str, str]] = []
        if index_rel:
            index_rows = self.loader.load_csv(index_rel)
            for row in index_rows:
                fp = self._extract_path_from_row(row, {})
                if not fp:
                    continue
                for val in row.values():
                    if val and val.strip():
                        index_by_id[val.strip()] = fp

        if not full_corpus:
            starters_path = self.loader.resolve_package_file("document_starters.csv")
            if starters_path is not None:
                self._record_path(starters_path)
                for row in self.loader.load_csv_path(starters_path):
                    fp = self._extract_path_from_row(row, index_by_id)
                    if fp and fp not in paths:
                        paths.append(fp)

        if full_corpus or not paths:
            for row in index_rows:
                fp = self._extract_path_from_row(row, index_by_id)
                if not fp:
                    continue
                joined = " ".join(row.values()).lower()
                if any(other in fp.lower() for other in ("cms-us-", "cms-fr-", "cms-cn-", "_sdb-", "_tdb-")):
                    continue
                if (
                    entity.entity_code.lower() in joined
                    or "_de." in fp.lower()
                    or "reg_" in fp.lower()
                    or "nachweis" in fp.lower()
                    or "audit" in fp.lower()
                    or "zwilling" in fp.lower()
                ):
                    if fp not in paths:
                        paths.append(fp)

        return paths

    def _extract_profile_units(self, entity: EntityContext) -> List[EvidenceUnit]:
        profile_rel = self._find_data_rel("company_profile.json")
        if not profile_rel:
            return []
        data = self.loader.load_json(profile_rel)
        if not isinstance(data, dict):
            return []

        units: List[EvidenceUnit] = []
        for idx, cert in enumerate(entity.certifications, start=1):
            lower_cert = cert.lower()
            is_restricted = any(
                marker in lower_cert for marker in ("only", "nur", "limited", "beschränkt", "frankfurt")
            )
            restriction_reason = None
            if is_restricted:
                restriction_reason = (
                    f"Certification '{cert}' has a restricted geographic/system scope and does not cover all German production sites."
                )
            units.append(
                EvidenceUnit(
                    unit_id=f"profile-cert-{idx}",
                    source_id="company_profile.json",
                    document_title="Company Profile - Certifications",
                    file_path=profile_rel,
                    unit_type="profile_fact",
                    text=f"Certification scope: {cert}. Entity sites: {', '.join(entity.sites)}",
                    exact_passage=cert,
                    location="company_profile.json, path: certifications",
                    version=str(data.get("snapshot_date") or data.get("as_of_date") or "2026-11-09"),
                    date=str(data.get("snapshot_date") or data.get("as_of_date") or "2026-11-09"),
                    status="Active",
                    scope_or_area="Certification Scope",
                    is_scope_restricted=is_restricted,
                    scope_restriction_reason=restriction_reason,
                )
            )
        return units

    def _extract_twin_question_units(self, entity: EntityContext) -> List[EvidenceUnit]:
        tq_rel = self._find_data_rel("twin_questions.csv")
        if not tq_rel:
            return []
        rows = self.loader.load_csv(tq_rel)
        units: List[EvidenceUnit] = []
        for idx, row in enumerate(rows, start=2):
            row_entity = (
                row.get("entity_id")
                or row.get("cms_code")
                or row.get("entity_code")
                or row.get("legal_entity")
                or row.get("entity")
                or ""
            ).strip()
            if row_entity and not any(
                tok.lower() in row_entity.lower()
                for tok in (entity.entity_code, entity.entity_id, "marenthal chemie ag", "de")
            ):
                continue

            q_id = row.get("question_id") or row.get("id") or f"TQ-{idx}"
            question = row.get("question_de") or row.get("question") or row.get("topic") or ""
            answer = (row.get("answer_de") or row.get("answer") or row.get("response") or "").strip()
            status = (row.get("status") or ("answered" if answer else "blank")).strip()

            units.append(
                EvidenceUnit(
                    unit_id=f"twin-q-{q_id}",
                    source_id=f"twin_questions.csv#{q_id}",
                    document_title="Digital Twin Questionnaire",
                    file_path=tq_rel,
                    unit_type="twin_qa",
                    text=f"Question ({q_id}): {question} | Answer: {answer or '[BLANK / UNANSWERED]'} | Status: {status}",
                    exact_passage=f"{question} -> {answer}" if answer else question,
                    location=f"{tq_rel}, row {idx}",
                    date=row.get("updated_at") or row.get("date"),
                    status=status,
                    structured_fields={"question": question, "answer": answer, "status": status},
                )
            )
        return units

    def _parse_document_metadata(self, rel_path: str) -> Dict[str, Any]:
        path, lines = self.loader.load_text_with_lines(rel_path)
        full_text = "".join(lines)
        stem = path.stem

        dms_match = re.match(r"^(DMS-\d+)", stem)
        source_id = dms_match.group(1) if dms_match else stem

        family_match = re.search(r"_(KR-\d+|VA-[A-Z]+-\d+|LK-\d+|V\d+|AU\d+|BR\d+)", stem)
        family_key = family_match.group(1) if family_match else source_id

        ver_match = re.search(r"_v(\d+)(?:\.(\d+))?", stem, re.IGNORECASE)
        if not ver_match:
            ver_match = re.search(r"(?:Version|Stand)\s*:\s*v?(\d+)(?:\.(\d+))?", full_text[:600], re.IGNORECASE)
        version_tuple = (
            (int(ver_match.group(1)), int(ver_match.group(2) or 0))
            if ver_match
            else (1, 0)
        )
        version_str = f"{version_tuple[0]}.{version_tuple[1]}"

        lang_match = re.search(r"_(de|en|fr|zh)(?:_|$)", stem, re.IGNORECASE)
        lang = lang_match.group(1).lower() if lang_match else "de"

        headers: Dict[str, str] = {}
        for line in lines[:25]:
            kv = re.match(r"^([A-Za-zÄÖÜäöüß\- /]+):\s*(.+)$", line.strip())
            if kv:
                headers[kv.group(1).strip().lower()] = kv.group(2).strip()

        title = (
            headers.get("titel")
            or headers.get("title")
            or headers.get("dokument")
            or path.name
        )
        doc_date = (
            headers.get("datum")
            or headers.get("date")
            or headers.get("stand")
            or headers.get("gültig ab")
        )
        doc_status = headers.get("status") or "Active"
        topic = headers.get("thema") or headers.get("topic") or headers.get("bereich") or ""

        is_scope_restricted = False
        scope_reason = None
        if topic and any(k in topic.lower() for k in ("ehs", "umwelt", "arbeitsschutz", "quality", "qualität")):
            is_scope_restricted = True
            scope_reason = (
                f"Document {source_id} explicitly restricts its scope to '{topic}' rather than IT/cybersecurity."
            )

        return {
            "rel_path": rel_path,
            "path": path,
            "lines": lines,
            "full_text": full_text,
            "source_id": source_id,
            "family_key": family_key,
            "lang": lang,
            "version_tuple": version_tuple,
            "version_str": version_str,
            "title": title,
            "date": doc_date,
            "status": doc_status,
            "topic": topic,
            "is_superseded": False,
            "superseded_by": None,
            "is_scope_restricted": is_scope_restricted,
            "scope_reason": scope_reason,
        }

    @staticmethod
    def _resolve_version_families(docs: List[Dict[str, Any]]) -> None:
        """Mark older versions in the same (family_key, lang) group as superseded."""
        by_family: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for d in docs:
            if d["family_key"] != d["source_id"]:
                by_family.setdefault((d["family_key"], d["lang"]), []).append(d)

        for group in by_family.values():
            if len(group) <= 1:
                continue
            group.sort(key=lambda x: x["version_tuple"], reverse=True)
            latest = group[0]
            for older in group[1:]:
                if older["version_tuple"] < latest["version_tuple"]:
                    older["is_superseded"] = True
                    older["superseded_by"] = f"{latest['source_id']} (v{latest['version_str']})"

    def _chunk_document(self, doc: Dict[str, Any]) -> List[EvidenceUnit]:
        """Extract both structured table rows and verbatim overlapping text chunks."""
        units: List[EvidenceUnit] = []
        rel_path: str = doc["rel_path"]
        lines: List[str] = doc["lines"]

        table_rows = self.loader.parse_markdown_table(rel_path)
        table_line_numbers = {r["__line_number__"] for r in table_rows}

        for r in table_rows:
            line_no = r["__line_number__"]
            raw_line = r["__raw_line__"]
            clean_fields = {k: str(v) for k, v in r.items() if not k.startswith("__")}
            row_desc = " | ".join(f"{k}: {v}" for k, v in clean_fields.items())
            row_status = (
                clean_fields.get("Status")
                or clean_fields.get("Result")
                or clean_fields.get("Effectiveness")
                or doc["status"]
            )
            row_date = (
                clean_fields.get("Last run")
                or clean_fields.get("Last review")
                or clean_fields.get("Date")
                or doc["date"]
            )

            units.append(
                EvidenceUnit(
                    unit_id=f"{doc['source_id']}:row:{line_no}",
                    source_id=doc["source_id"],
                    document_title=doc["title"],
                    file_path=rel_path,
                    unit_type="register_row",
                    text=f"[{doc['title']}] {row_desc}",
                    exact_passage=raw_line,
                    location=f"{rel_path}, line {line_no}",
                    version=doc["version_str"],
                    date=row_date,
                    status=row_status,
                    scope_or_area=clean_fields.get("Legal area") or clean_fields.get("Category") or doc["topic"],
                    structured_fields=clean_fields,
                    is_superseded=doc["is_superseded"],
                    superseded_by=doc["superseded_by"],
                    is_scope_restricted=doc["is_scope_restricted"],
                    scope_restriction_reason=doc["scope_reason"],
                )
            )

        non_table_indices = [
            i for i in range(len(lines)) if (i + 1) not in table_line_numbers and lines[i].strip()
        ]
        if not non_table_indices:
            return units

        window_size = 12
        stride = 8
        for start_pos in range(0, len(non_table_indices), stride):
            slice_indices = non_table_indices[start_pos : start_pos + window_size]
            if not slice_indices:
                break
            first_line_idx = slice_indices[0]
            last_line_idx = slice_indices[-1]
            verbatim = "".join(lines[first_line_idx : last_line_idx + 1]).strip()
            if len(verbatim) < 25:
                continue

            units.append(
                EvidenceUnit(
                    unit_id=f"{doc['source_id']}:lines:{first_line_idx + 1}-{last_line_idx + 1}",
                    source_id=doc["source_id"],
                    document_title=doc["title"],
                    file_path=rel_path,
                    unit_type="policy_chunk",
                    text=f"[{doc['title']} | {doc['topic']}] {verbatim}",
                    exact_passage=verbatim,
                    location=f"{rel_path}, lines {first_line_idx + 1}-{last_line_idx + 1}",
                    version=doc["version_str"],
                    date=doc["date"],
                    status="Superseded" if doc["is_superseded"] else doc["status"],
                    scope_or_area=doc["topic"] or "General",
                    is_superseded=doc["is_superseded"],
                    superseded_by=doc["superseded_by"],
                    is_scope_restricted=doc["is_scope_restricted"],
                    scope_restriction_reason=doc["scope_reason"],
                )
            )

        return units