import pytest
from pathlib import Path
from src.loader import DataLoader

def test_loader_missing_file(tmp_path):
    loader = DataLoader(tmp_path)
    with pytest.raises(FileNotFoundError):
        loader.load_json("non_existent.json")

def test_parse_markdown_table(tmp_path):
    table_content = (
        "| Header1 | Header2 |\n"
        "| --- | --- |\n"
        "| Value1 | Value2 |\n"
        "| Value3 | Value4 |\n"
    )
    test_file = tmp_path / "test_table.txt"
    test_file.write_text(table_content, encoding="utf-8")

    loader = DataLoader(tmp_path)
    rows = loader.parse_markdown_table("test_table.txt")
    assert len(rows) == 2
    assert rows[0]["Header1"] == "Value1"
    assert rows[1]["Header2"] == "Value4"