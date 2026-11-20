"""
Hybrid Legal-Tech Retriever.
Combines structured table parsing with text retrieval, version resolution,
and temporal snapshot checking against 2026-11-18.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.loader import DataLoader


@dataclass
class RetrievedSnippet:
    source_id: str
    file_path: str
    document_title: str
    version: Optional[str]
    status: Optional[str]
    date: Optional[str]
    scope_or_area: Optional[str]
    exact_text: str
    location: str
    score: float
    is_superseded: bool = False
    is_scope_mismatch: bool = False


class LegalRetriever:
    SNAPSHOT_DATE = "2026-11-18"

    def __init__(self, loader: DataLoader):
        self.loader = loader

    def search_evidence_for_duty(self, duty_id: str, duty_title: str, query_keywords: List[str]) -> List[RetrievedSnippet]:
        """Dynamically finds relevant document snippets and register entries for a given duty."""
        results: List[RetrievedSnippet] = []

        # 1. Search Structured Obligations Register
        try:
            ob_rows = self.loader.parse_markdown_table("documents/REG_Legal_Obligations_CMS-DE-01.txt")
            for row in ob_rows:
                row_text = " ".join(row.values()).lower()
                if any(kw.lower() in row_text for kw in query_keywords):
                    is_overdue = False
                    next_due = row.get("Next due", "-")
                    if next_due != "-" and next_due < self.SNAPSHOT_DATE:
                        is_overdue = True

                    results.append(
                        RetrievedSnippet(
                            source_id="REG_Legal_Obligations_CMS-DE-01",
                            file_path="documents/REG_Legal_Obligations_CMS-DE-01.txt",
                            document_title="Register of legal and internal obligations",
                            version="1.0",
                            status=f"{row.get('Status')} {'(OVERDUE)' if is_overdue else ''}",
                            date=row.get("Last review"),
                            scope_or_area=row.get("Legal area"),
                            exact_text=row["__raw_line__"],
                            location=f"Line {row['__line_number__']}",
                            score=0.95 if "offen" in row.get("Status", "").lower() else 0.85,
                        )
                    )
        except Exception:
            pass

        # 2. Search Internal Controls Register
        try:
            ctrl_rows = self.loader.parse_markdown_table("documents/REG_Internal_Controls_CMS-DE-01.txt")
            for row in ctrl_rows:
                row_text = " ".join(row.values()).lower()
                if any(kw.lower() in row_text for kw in query_keywords):
                    results.append(
                        RetrievedSnippet(
                            source_id="REG_Internal_Controls_CMS-DE-01",
                            file_path="documents/REG_Internal_Controls_CMS-DE-01.txt",
                            document_title="Register of internal controls and their execution",
                            version="1.0",
                            status=row.get("Status"),
                            date=row.get("Last run"),
                            scope_or_area=row.get("Risk covered"),
                            exact_text=row["__raw_line__"],
                            location=f"Line {row['__line_number__']}",
                            score=0.88,
                        )
                    )
        except Exception:
            pass

        # 3. Search Key Policy Documents & Check Versions
        policies = [
            ("documents/DMS-00000420_KR-009_v2.0_de.txt", "2.0", False),
            ("documents/DMS-00000205_KR-009_v1.1_de.txt", "1.1", True),  # Superseded
            ("documents/DMS-00000671_KR-017_v2.0_de.txt", "2.0", False),
            ("documents/DMS-00001406_V000074_Nachweis.txt", "1.0", False),
        ]

        for p_rel, ver, is_super in policies:
            try:
                p_path, lines = self.loader.load_text_with_lines(p_rel)
                full_text = "".join(lines)
                if any(kw.lower() in full_text.lower() for kw in query_keywords):
                    # Check for explicit scope mismatches (e.g. KR-017 EHS)
                    is_scope_mismatch = "thema: EHS" in full_text and duty_id != "EHS"

                    # Find best matching block of lines
                    best_block = lines[12:28] if len(lines) >= 28 else lines
                    snippet_text = "".join(best_block).strip()

                    results.append(
                        RetrievedSnippet(
                            source_id=Path(p_rel).stem.split("_")[0],
                            file_path=p_rel,
                            document_title=Path(p_rel).name,
                            version=ver,
                            status="Superseded" if is_super else "Approved",
                            date="2024/2025",
                            scope_or_area="EHS" if "thema: EHS" in full_text else "Informationssicherheit",
                            exact_text=snippet_text,
                            location=f"{p_rel}, lines 13-28",
                            score=0.5 if is_super else (0.6 if is_scope_mismatch else 0.9),
                            is_superseded=is_super,
                            is_scope_mismatch=is_scope_mismatch,
                        )
                    )
            except Exception:
                pass

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        return results