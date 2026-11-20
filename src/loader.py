"""
Robust, self-healing data loader for Coback Marenthal inputs.
Recursively locates files across base_dir, subdirectories, or fallback locations.
"""
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


class DataLoader:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).expanduser().resolve()

    def resolve_path(self, rel_path: str) -> Path:
        """Finds the file by relative path or recursive filename search."""
        target_name = Path(rel_path).name

        # 1. Direct candidate checks
        direct_candidates = [
            self.base_dir / rel_path,
            self.base_dir / "data" / rel_path,
            self.base_dir / "company_data" / rel_path,
            self.base_dir / "data" / "company_data" / rel_path,
        ]
        for c in direct_candidates:
            if c.is_file():
                return c

        # 2. Recursive search inside self.base_dir
        matches = list(self.base_dir.rglob(target_name))
        if matches:
            return matches[0]

        # 3. Fallback search inside ~/Downloads if running from repo root
        downloads_dir = Path.home() / "Downloads"
        if downloads_dir.exists():
            dl_matches = list(downloads_dir.rglob(target_name))
            if dl_matches:
                return dl_matches[0]

        raise FileNotFoundError(
            f"Could not locate '{target_name}' in '{self.base_dir}' or in '~/Downloads'."
        )

    def load_json(self, rel_path: str) -> Dict[str, Any]:
        path = self.resolve_path(rel_path)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_csv(self, rel_path: str) -> List[Dict[str, str]]:
        path = self.resolve_path(rel_path)
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def load_text_with_lines(self, rel_path: str) -> Tuple[Path, List[str]]:
        path = self.resolve_path(rel_path)
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return path, lines

    def parse_markdown_table(self, rel_path: str) -> List[Dict[str, Any]]:
        """Parses markdown table files and attaches the exact line number and raw text."""
        path, raw_lines = self.load_text_with_lines(rel_path)
        parsed_rows = []
        headers = []
        header_found = False

        for line_idx, raw_line in enumerate(raw_lines, start=1):
            line = raw_line.strip()
            if not line.startswith("|") or not line.endswith("|"):
                continue

            cells = [c.strip() for c in line.split("|")[1:-1]]

            if not header_found:
                headers = cells
                header_found = True
                continue

            # Skip markdown table divider line (| --- | --- |)
            if all(set(c).issubset({"-", " ", ":"}) for c in cells):
                continue

            if len(cells) == len(headers):
                row_dict = dict(zip(headers, cells))
                row_dict["__line_number__"] = line_idx
                row_dict["__raw_line__"] = line
                row_dict["__file_path__"] = str(path)
                parsed_rows.append(row_dict)

        return parsed_rows