"""Verification tests for the local Web UI backend endpoints and document viewer."""
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer
import httpx
import pytest

from src.web_ui import ComplianceWorkbenchState, create_request_handler, parse_line_range


def test_parse_line_range():
    assert parse_line_range("documents/REG_Legal_Obligations_CMS-DE-01.txt, line 82") == (82, 82)
    assert parse_line_range("documents/DMS-00001406_V000074_Nachweis.txt, lines 19-31") == (19, 31)
    assert parse_line_range("no line info") == (None, None)


def test_web_ui_endpoints_and_doc_viewer(tmp_path: Path):
    company_dir = tmp_path / "company_data"
    docs_dir = company_dir / "documents"
    docs_dir.mkdir(parents=True)

    (tmp_path / "NIS2_selected_duties.json").write_text(
        json.dumps(
            [
                {
                    "duty_id": "04-P02-1",
                    "statutory_ref": "§30 Abs.2 Nr.1 BSIG",
                    "duty_title": "Risikoanalyse",
                    "description_de": "Jährliche Risikoanalyse durchführen.",
                }
            ]
        ),
        encoding="utf-8",
    )
    (company_dir / "legal_entities.csv").write_text(
        "entity_id,cms_code,legal_name,country\nENT-DE-01,CMS-DE-01,Marenthal Chemie AG,DE\n",
        encoding="utf-8",
    )
    (company_dir / "company_profile.json").write_text(
        json.dumps({"company_name": "Marenthal Chemie AG", "country": "DE", "certifications": []}),
        encoding="utf-8",
    )
    (docs_dir / "REG_Legal_Obligations_CMS-DE-01.txt").write_text(
        "| Obligation | Legal area | Next due | Status |\n"
        "| --- | --- | --- | --- |\n"
        "| Informationssicherheitsrisikoanalyse jährlich durchführen | Informationssicherheit | 2026-01-01 | offen |\n",
        encoding="utf-8",
    )
    (tmp_path / "document_starters.csv").write_text(
        "source_id,file_path\nREG_Legal_Obligations,documents/REG_Legal_Obligations_CMS-DE-01.txt\n",
        encoding="utf-8",
    )

    state = ComplianceWorkbenchState(
        data_dir=company_dir,
        output_dir=tmp_path / "outputs",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_request_handler(state))
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        scheme = "http"
        host = "127.0.0.1"
        base = f"{scheme}://{host}:{port}"
        home = httpx.get(f"{base}/")
        assert home.status_code == 200
        assert "COBACK AI Compliance Gap Analysis" in home.text

        run_resp = httpx.get(f"{base}/api/run?use_llm=0")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["results"][0]["duty_id"] == "04-P02-1"
        assert payload["results"][0]["state"] == "open"
        assert "documents/REG_Legal_Obligations_CMS-DE-01.txt" in payload["results"][0]["sources_reviewed"]
        assert len(payload["results"][0]["decision_influence"]) >= 1

        doc_resp = httpx.get(
            f"{base}/api/doc",
            params={"path": "documents/REG_Legal_Obligations_CMS-DE-01.txt", "location": "line 3"},
        )
        assert doc_resp.status_code == 200
        doc_json = doc_resp.json()
        assert doc_json["highlight_start"] == 3
        assert "offen" in doc_json["lines"][2]

        traversal_resp = httpx.get(f"{base}/api/doc", params={"path": "../NIS2_selected_duties.json"})
        assert traversal_resp.status_code == 403
    finally:
        server.shutdown()
        server.server_close()