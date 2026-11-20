"""Load assessment inputs safely from an explicitly configured data directory."""

import csv
import json
from pathlib import Path
from typing import Any, List, Optional, Tuple


class DataLoader:
    """Read input files without searching outside the configured root."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).expanduser().resolve()

    def resolve_path(self, rel_path: str) -> Path:
        """Resolve an existing file strictly inside the data root."""
        relative = Path(rel_path)

        if relative.is_absolute():
            raise ValueError("Absolute input paths are not permitted.")

        candidate = (self.base_dir / relative).resolve()

        if not candidate.is_relative_to(self.base_dir):
            raise ValueError(
                "Input path escapes the configured data directory."
            )

        if not candidate.is_file():
            raise FileNotFoundError(
                f"Input file not found: {rel_path}\n"
                f"Configured data directory: {self.base_dir}"
            )

        return candidate

    def try_resolve_path(self, rel_path: str) -> Optional[Path]:
        """Resolve rel_path inside base_dir (or company_data/ if base_dir is package root)."""
        for candidate_rel in (rel_path, f"company_data/{rel_path}"):
            try:
                return self.resolve_path(candidate_rel)
            except (FileNotFoundError, ValueError):
                continue
        return None

    def resolve_package_file(self, filename: str) -> Optional[Path]:
        """Resolve a top-level package metadata file in base_dir or its parent (if company_data)."""
        safe_name = Path(filename).name
        if safe_name != filename:
            raise ValueError("Package metadata lookup accepts a plain filename only.")

        roots = [self.base_dir]
        if self.base_dir.name == "company_data":
            roots.append(self.base_dir.parent)

        for root in roots:
            candidate = (root / safe_name).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return candidate
        return None

    def load_json_path(self, path: Path) -> Any:
        with path.open(encoding="utf-8-sig") as handle:
            return json.load(handle)

    def load_csv_path(self, path: Path) -> List[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
            return list(csv.DictReader(handle, delimiter=delimiter))

    def load_json(self, rel_path: str) -> Any:
        """Load JSON, allowing either an object or an array."""
        return self.load_json_path(self.resolve_path(rel_path))

    def load_csv(self, rel_path: str) -> List[dict[str, str]]:
        """Load a CSV file, accepting a UTF-8 BOM."""
        return self.load_csv_path(self.resolve_path(rel_path))

    def load_text_with_lines(self, rel_path: str) -> Tuple[Path, List[str]]:
        """Read text while preserving line endings and line positions."""
        path = self.resolve_path(rel_path)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return path, handle.readlines()

    @staticmethod
    def _table_cells(line: str) -> Optional[List[str]]:
        """Split a pipe-delimited Markdown row."""
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            return None
        return [cell.strip() for cell in stripped[1:-1].split("|")]

    @staticmethod
    def _is_separator(cells: List[str]) -> bool:
        """Identify a Markdown header separator."""
        return bool(cells) and all(
            bool(cell) and "-" in cell and set(cell).issubset({"-", ":", " "})
            for cell in cells
        )

    def parse_markdown_table(self, rel_path: str) -> List[dict[str, Any]]:
        """Parse Markdown table rows with source provenance."""
        path, lines = self.load_text_with_lines(rel_path)
        parsed_rows: List[dict[str, Any]] = []
        headers: Optional[List[str]] = None

        for index, raw_line in enumerate(lines):
            cells = self._table_cells(raw_line)
            if cells is None:
                headers = None
                continue

            next_cells = (
                self._table_cells(lines[index + 1])
                if index + 1 < len(lines)
                else None
            )

            if (
                next_cells is not None
                and self._is_separator(next_cells)
                and len(cells) == len(next_cells)
            ):
                headers = cells
                continue

            if self._is_separator(cells) or headers is None:
                continue

            if len(cells) != len(headers):
                raise ValueError(
                    f"Malformed table row in {rel_path}, "
                    f"line {index + 1}: expected {len(headers)} cells, "
                    f"found {len(cells)}."
                )

            row: dict[str, Any] = dict(zip(headers, cells))
            row["__line_number__"] = index + 1
            row["__raw_line__"] = raw_line.strip()
            row["__file_path__"] = str(path)
            parsed_rows.append(row)

        return parsed_rows