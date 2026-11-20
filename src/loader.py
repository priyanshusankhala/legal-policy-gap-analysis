"""Load assessment inputs from an explicitly configured data directory."""

import csv
import json
from pathlib import Path
from typing import Any


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

    def load_json(self, rel_path: str) -> Any:
        """Load JSON, allowing either an object or an array."""
        path = self.resolve_path(rel_path)

        with path.open(encoding="utf-8-sig") as handle:
            return json.load(handle)

    def load_csv(self, rel_path: str) -> list[dict[str, str]]:
        """Load a comma-separated file, accepting a UTF-8 BOM."""
        path = self.resolve_path(rel_path)

        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def load_text_with_lines(
        self,
        rel_path: str,
    ) -> tuple[Path, list[str]]:
        """Read text while preserving line endings and line positions."""
        path = self.resolve_path(rel_path)

        with path.open(encoding="utf-8-sig", newline="") as handle:
            return path, handle.readlines()

    @staticmethod
    def _table_cells(line: str) -> list[str] | None:
        """Split a pipe-delimited Markdown row.

        This bounded parser expects leading and trailing pipes. Escaped
        pipes inside cells are not supported.
        """
        stripped = line.strip()

        if not stripped.startswith("|") or not stripped.endswith("|"):
            return None

        return [
            cell.strip()
            for cell in stripped[1:-1].split("|")
        ]

    @staticmethod
    def _is_separator(cells: list[str]) -> bool:
        """Identify a Markdown header separator."""
        return bool(cells) and all(
            bool(cell)
            and "-" in cell
            and set(cell).issubset({"-", ":", " "})
            for cell in cells
        )

    def parse_markdown_table(
        self,
        rel_path: str,
    ) -> list[dict[str, Any]]:
        """Parse Markdown table rows with source provenance.

        Supports multiple tables separated by non-table text. Each table
        must contain a header followed by a Markdown separator.

        Returned rows preserve the metadata keys expected by the current
        analyzer.
        """
        path, lines = self.load_text_with_lines(rel_path)
        parsed_rows: list[dict[str, Any]] = []
        headers: list[str] | None = None

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

            # A table header is immediately followed by its separator.
            if (
                next_cells is not None
                and self._is_separator(next_cells)
                and len(cells) == len(next_cells)
            ):
                headers = cells
                continue

            if self._is_separator(cells):
                continue

            if headers is None:
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
