"""
Entity-Scoped Corpus Builder, Effective-Date Version Resolver & Scope Analyzer.
Enforces:
- Fail-loud entity resolution (never falls back to entities[0] or invents country='DE')
- Exact entity matching for twin_questions.csv (never matches substring 'de')
- Unknown stays unknown (missing dates/statuses remain None, never fabricated defaults)
- Effective-date awareness: policies effective after as_of_date are marked 'not_yet_effective'
  and never supersede policies currently in force on as_of_date.
"""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from src.loader import DataLoader


def parse_iso_or_de_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    cleaned = raw.strip()
    iso_m = re.search(r"(\d{4})-(\d{2})-(\d{2})", cleaned)
    if iso_m:
        try:
            return date(int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3)))
        except ValueError:
            return None
    de_m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", cleaned)
    if de_m:
        try:
            return date(int(de_m.group(3)), int(de_m.group(2)), int(de_m.group(1)))
        except ValueError:
            return None
    return None


@dataclass
class EvidenceUnit:
    unit_id: str
    source_id: str
    document_title: str
    file_path: str
    unit_type: str  # policy_chunk | register_row | twin_qa | profile_fact
    text: str
    exact_passage: str
    location: str
    version: Optional[str] = None
    date: Optional[str] = None
    effective_date: Optional[str] = None
    status: Optional[str] = None
    scope_or_area: Optional[str] = None
    structured_fields: Dict[str, str] = field(default_factory=dict)
    is_superseded: bool = False
    superseded_by: Optional[str] = None
    is_future_dated: bool = False
    future_date_reason: Optional[str] = None
    is_scope_restricted: bool = False
    scope_restriction_reason: Optional[str] = None
    is_starter_corpus: bool = False


@dataclass
class EntityContext:
    entity_name: str
    entity_id: str
    entity_code: str
    country: str
    sites: List[str]
    certifications: List[str]


class CorpusBuilder:
    """Builds a clean, provenance-preserving evidence index for a strictly resolved entity."""

    def __init__(
        self,
        loader: DataLoader,
        target_entity_hint: str = "Marenthal Chemie AG",
        as_of_date: str = "2026-11-18",
    ):
        self.loader = loader
        self.target_entity_hint = target_entity_hint.strip()
        self.as_of_str = as_of_date
        self.as_of = date.fromisoformat(as_of_date)
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
        """Strictly resolve target entity metadata; raise ValueError if unresolved or ambiguous."""
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

        hint_lower = self.target_entity_hint.lower()
        if not hint_lower:
            raise ValueError("target_entity_hint must not be empty.")

        selected_row: Dict[str, str] = {}
        if entities:
            matches = [
                row
                for row in entities
                if any(
                    hint_lower == val.strip().lower() or hint_lower in val.strip().lower()
                    for val in row.values()
                    if val
                )
            ]
            if len(matches) > 1:
                exact_matches = [
                    row
                    for row in matches
                    if any(hint_lower == val.strip().lower() for val in row.values() if val)
                ]
                if len(exact_matches) == 1:
                    matches = exact_matches

            if len(matches) == 0:
                available = [
                    row.get("legal_name") or row.get("entity_name") or row.get("name") or str(row)
                    for row in entities
                ]
                raise ValueError(
                    f"Target entity '{self.target_entity_hint}' not found in legal_entities.csv. "
                    f"Available entities: {available}"
                )
            if len(matches) > 1:
                ambiguous = [
                    row.get("legal_name") or row.get("entity_name") or row.get("name") or str(row)
                    for row in matches
                ]
                raise ValueError(
                    f"Ambiguous target entity '{self.target_entity_hint}' matched multiple entities: {ambiguous}. "
                    "Please specify an exact legal name, entity_id, or cms_code."
                )
            selected_row = matches[0]
        elif profile:
            prof_name = str(profile.get("company_name") or profile.get("legal_name") or "").strip()
            if prof_name and hint_lower not in prof_name.lower():
                raise ValueError(
                    f"Target entity '{self.target_entity_hint}' does not match company_profile.json ('{prof_name}')."
                )
        else:
            raise FileNotFoundError("Neither legal_entities.csv nor company_profile.json found.")

        raw_name = (
            selected_row.get("legal_name")
            or selected_row.get("entity_name")
            or selected_row.get("name")
            or profile.get("company_name")
            or self.target_entity_hint
        ).strip()

        country = (
            selected_row.get("country")
            or selected_row.get("jurisdiction")
            or profile.get("country")
            or "UNKNOWN"
        ).strip().upper()

        entity_name = raw_name
        if country != "UNKNOWN" and f"({country})" not in entity_name:
            entity_name = f"{entity_name} ({country})"

        entity_id = (
            selected_row.get("entity_id")
            or selected_row.get("id")
            or profile.get("entity_id")
            or "UNKNOWN"
        ).strip()

        entity_code = (
            selected_row.get("cms_code")
            or selected_row.get("entity_code")
            or selected_row.get("code")
            or entity_id
        ).strip()

        sites: List[str] = []
        for key in ("sites", "locations", "plants", "facilities"):
            val = profile.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        site_country = str(item.get("country", "")).strip().upper()
                        if country == "UNKNOWN" or not site_country or site_country == country:
                            sites.append(str(item.get("name") or item.get("city") or item))
                    else:
                        sites.append(str(item))

        certs = [str(c) for c in profile.get("certifications", []) if c]

        return EntityContext(
            entity_name=entity_name,
            entity_id=entity_id,
            entity_code=entity_code,
            country=country,
            sites=sites,
            certifications=certs,
        )

    def build_corpus(self, entity: EntityContext, full_corpus: bool = False) -> List[EvidenceUnit]:
        """Build all retrievable evidence units for the target entity."""
        units: List[EvidenceUnit] = []
        units.extend(self._extract_profile_units(entity))
        units.extend(self._extract_twin_question_units(entity))

        discovered = self._discover_document_paths(entity, full_corpus=full_corpus)
        raw_docs: List[Dict[str, Any]] = []
        for rel, is_starter in discovered:
            resolved = self.loader.try_resolve_path(rel)
            if resolved is None:
                continue
            actual_rel = str(resolved.relative_to(self.loader.base_dir))
            self._record_path(resolved)
            doc_meta = self._parse_document_metadata(actual_rel)
            doc_meta["is_starter"] = is_starter
            raw_docs.append(doc_meta)

        self._resolve_version_families(raw_docs)

        for doc_info in raw_docs:
            units.extend(self._chunk_document(doc_info))

        return units

    @staticmethod
    def _extract_path_from_row(row: Dict[str, str], index_by_id: Dict[str, str]) -> str:
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

    def _discover_document_paths(
        self, entity: EntityContext, full_corpus: bool
    ) -> List[Tuple[str, bool]]:
        discovered: List[Tuple[str, bool]] = []
        seen: set[str] = set()

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
                    if fp and fp not in seen:
                        seen.add(fp)
                        discovered.append((fp, True))

        if full_corpus or not discovered:
            code_lower = entity.entity_code.lower()
            country_suffix = f"_{entity.country.lower()}." if entity.country != "UNKNOWN" else ""
            for row in index_rows:
                fp = self._extract_path_from_row(row, index_by_id)
                if not fp or fp in seen:
                    continue
                joined = " ".join(row.values()).lower()
                if any(other in fp.lower() for other in ("_sdb-", "_tdb-")):
                    continue
                if (
                    (code_lower != "unknown" and code_lower in joined)
                    or (country_suffix and country_suffix in fp.lower())
                    or "reg_" in fp.lower()
                    or "nachweis" in fp.lower()
                    or "audit" in fp.lower()
                    or "zwilling" in fp.lower()
                ):
                    seen.add(fp)
                    discovered.append((fp, False))

        return discovered

    def _extract_profile_units(self, entity: EntityContext) -> List[EvidenceUnit]:
        profile_rel = self._find_data_rel("company_profile.json")
        if not profile_rel:
            return []
        data = self.loader.load_json(profile_rel)
        if not isinstance(data, dict):
            return []

        snap_date = data.get("snapshot_date") or data.get("as_of_date")
        units: List[EvidenceUnit] = []
        for idx, cert in enumerate(entity.certifications, start=1):
            lower_cert = cert.lower()
            is_restricted = any(
                marker in lower_cert for marker in ("only", "nur", "limited", "beschränkt", "frankfurt")
            )
            restriction_reason = None
            if is_restricted:
                restriction_reason = (
                    f"Certification '{cert}' has a restricted geographic/system scope and does not cover all entity sites."
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
                    version=str(snap_date) if snap_date else None,
                    date=str(snap_date) if snap_date else None,
                    effective_date=str(snap_date) if snap_date else None,
                    status=None,
                    scope_or_area="Certification Scope",
                    is_scope_restricted=is_restricted,
                    scope_restriction_reason=restriction_reason,
                    is_starter_corpus=True,
                )
            )
        return units

    def _extract_twin_question_units(self, entity: EntityContext) -> List[EvidenceUnit]:
        tq_rel = self._find_data_rel("twin_questions.csv")
        if not tq_rel:
            return []
        rows = self.loader.load_csv(tq_rel)

        allowed_tokens = {
            entity.entity_code.lower(),
            entity.entity_id.lower(),
            entity.entity_name.lower(),
            re.sub(r"\s*\([A-Z]+\)\s*$", "", entity.entity_name).strip().lower(),
        }
        if entity.country != "UNKNOWN":
            allowed_tokens.add(entity.country.lower())
        allowed_tokens.discard("unknown")
        allowed_tokens.discard("")

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
            if row_entity and row_entity.lower() not in allowed_tokens:
                continue

            q_id = row.get("question_id") or row.get("id") or f"TQ-{idx}"
            question = (row.get("question_de") or row.get("question") or row.get("topic") or "").strip()
            answer = (row.get("answer_de") or row.get("answer") or row.get("response") or "").strip()
            raw_status = (row.get("status") or "").strip()
            status = raw_status if raw_status else ("answered" if answer else "blank")

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
                    date=row.get("updated_at") or row.get("date") or None,
                    effective_date=row.get("updated_at") or row.get("date") or None,
                    status=status,
                    structured_fields={"question": question, "answer": answer, "status": status},
                    is_starter_corpus=True,
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
            else None
        )
        version_str = f"{version_tuple[0]}.{version_tuple[1]}" if version_tuple is not None else None

        lang_match = re.search(r"_(de|en|fr|zh)(?:_|$)", stem, re.IGNORECASE)
        lang = lang_match.group(1).lower() if lang_match else "unknown"

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
            or None
        )
        effective_raw = (
            headers.get("gültig ab")
            or headers.get("gueltig ab")
            or headers.get("effective date")
            or headers.get("valid from")
            or headers.get("inkrafttreten")
            or doc_date
        )
        effective_dt = parse_iso_or_de_date(effective_raw)
        is_future_dated = effective_dt is not None and effective_dt > self.as_of
        future_reason = (
            f"Document {source_id} has effective date {effective_dt.isoformat()}, which is after assessment date {self.as_of_str}."
            if is_future_dated
            else None
        )

        doc_status = headers.get("status") or None
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
            "effective_date": effective_dt.isoformat() if effective_dt else effective_raw,
            "effective_dt": effective_dt,
            "status": doc_status,
            "topic": topic,
            "is_future_dated": is_future_dated,
            "future_reason": future_reason,
            "is_superseded": False,
            "superseded_by": None,
            "is_scope_restricted": is_scope_restricted,
            "scope_reason": scope_reason,
            "is_starter": False,
        }

    @staticmethod
    def _resolve_version_families(docs: List[Dict[str, Any]]) -> None:
        """
        Mark older versions in the same (family_key, lang) group as superseded,
        considering ONLY versions effective on or before as_of_date.
        A future-dated policy must never supersede the policy effective on as_of_date.
        """
        by_family: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for d in docs:
            if d["is_future_dated"]:
                continue
            if d["family_key"] != d["source_id"]:
                by_family.setdefault((d["family_key"], d["lang"]), []).append(d)

        for group in by_family.values():
            if len(group) <= 1:
                continue
            group.sort(
                key=lambda x: (
                    x["version_tuple"] or (0, 0),
                    x["effective_dt"] or date.min,
                ),
                reverse=True,
            )
            latest = group[0]
            for older in group[1:]:
                older_ver = older["version_tuple"] or (0, 0)
                latest_ver = latest["version_tuple"] or (0, 0)
                if older_ver < latest_ver or (
                    older_ver == latest_ver
                    and older["effective_dt"] is not None
                    and latest["effective_dt"] is not None
                    and older["effective_dt"] < latest["effective_dt"]
                ):
                    older["is_superseded"] = True
                    v_label = f"v{latest['version_str']}" if latest["version_str"] else "newer version"
                    older["superseded_by"] = f"{latest['source_id']} ({v_label})"

    def _chunk_document(self, doc: Dict[str, Any]) -> List[EvidenceUnit]:
        """Extract structured table rows and non-overlapping verbatim sections."""
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
                    effective_date=doc["effective_date"],
                    status=row_status,
                    scope_or_area=clean_fields.get("Legal area") or clean_fields.get("Category") or doc["topic"] or None,
                    structured_fields=clean_fields,
                    is_superseded=doc["is_superseded"],
                    superseded_by=doc["superseded_by"],
                    is_future_dated=doc["is_future_dated"],
                    future_date_reason=doc["future_reason"],
                    is_scope_restricted=doc["is_scope_restricted"],
                    scope_restriction_reason=doc["scope_reason"],
                    is_starter_corpus=doc["is_starter"],
                )
            )

        non_table_indices = [
            i for i in range(len(lines)) if (i + 1) not in table_line_numbers and lines[i].strip()
        ]
        if not non_table_indices:
            return units

        window_size = 16
        stride = 16
        for start_pos in range(0, len(non_table_indices), stride):
            slice_indices = non_table_indices[start_pos : start_pos + window_size]
            if not slice_indices:
                break
            first_line_idx = slice_indices[0]
            last_line_idx = slice_indices[-1]
            verbatim = "".join(lines[first_line_idx : last_line_idx + 1]).strip()
            if len(verbatim) < 25:
                continue

            status_val = "Superseded" if doc["is_superseded"] else doc["status"]

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
                    effective_date=doc["effective_date"],
                    status=status_val,
                    scope_or_area=doc["topic"] or None,
                    is_superseded=doc["is_superseded"],
                    superseded_by=doc["superseded_by"],
                    is_future_dated=doc["is_future_dated"],
                    future_date_reason=doc["future_reason"],
                    is_scope_restricted=doc["is_scope_restricted"],
                    scope_restriction_reason=doc["scope_reason"],
                    is_starter_corpus=doc["is_starter"],
                )
            )

        return units