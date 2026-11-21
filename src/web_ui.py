"""
Local Web UI for COBACK Compliance Gap Analysis.
Features:
1. Duty selector (dropdown + quick tabs) comparing supplied company evidence against legal clauses.
2. Displays Duty ID, statutory reference, state badge, synthesis reason, clause-level rationales,
   available supporting records, missing facts, separate lists of Supported Gaps and Evidence Questions.
3. Clickable document links that open the exact company document scrolled and highlighted to the cited line(s),
   plus one-click native macOS/OS file opening.
4. Per-duty audit log showing all searched sources and how document versions & register statuses influenced the result.
"""
import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import re
import subprocess
import threading
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse
import webbrowser

from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader
from src.models import ComplianceAssessmentReport


def parse_line_range(location: str) -> Tuple[Optional[int], Optional[int]]:
    """Extract (start_line, end_line) from location strings like 'documents/foo.txt, lines 19-31' or 'line 82'."""
    if not location:
        return None, None
    m_range = re.search(r"lines?\s+(\d+)\s*[-–]\s*(\d+)", location, re.IGNORECASE)
    if m_range:
        return int(m_range.group(1)), int(m_range.group(2))
    m_single = re.search(r"line\s+(\d+)", location, re.IGNORECASE)
    if m_single:
        ln = int(m_single.group(1))
        return ln, ln
    return None, None


class ComplianceWorkbenchState:
    """Thread-safe state holder managing cached and live compliance assessment runs."""

    def __init__(
        self,
        data_dir: Path,
        output_dir: Path,
        as_of_date: str = "2026-11-18",
        target_entity: str = "Marenthal Chemie AG",
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.2",
    ):
        self.raw_data_dir = data_dir
        default_subpath = data_dir / "data" / "COBACK_Marenthal_Inputs" / "company_data"
        self.resolved_data_dir = default_subpath if default_subpath.is_dir() else data_dir
        self.loader = DataLoader(self.resolved_data_dir)
        self.output_dir = output_dir
        self.as_of_date = as_of_date
        self.target_entity = target_entity
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model

        self._lock = threading.Lock()
        self.report_dict: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None
        self._load_cached_if_available()

    def _load_cached_if_available(self) -> None:
        json_path = self.output_dir / "compliance_report.json"
        if json_path.is_file():
            try:
                loaded = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and "results" in loaded:
                    self.report_dict = loaded
            except Exception:
                pass

    def get_report(self, use_llm: bool = True, force_rerun: bool = False) -> Dict[str, Any]:
        with self._lock:
            if not force_rerun and self.report_dict is not None:
                return self.report_dict

            analyzer = ComplianceAnalyzer(
                data_loader=DataLoader(self.raw_data_dir),
                as_of_date=self.as_of_date,
                target_entity=self.target_entity,
                use_dense=True,
                use_llm=use_llm,
                ollama_url=self.ollama_url,
                ollama_model=self.ollama_model,
                progress_callback=lambda msg: print(msg, flush=True),
            )
            report: ComplianceAssessmentReport = analyzer.run_assessment()
            self.output_dir.mkdir(parents=True, exist_ok=True)
            json_path = self.output_dir / "compliance_report.json"
            json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            self.report_dict = json.loads(report.model_dump_json())
            self.last_error = None
            return self.report_dict

    def read_document(self, rel_or_abs_path: str) -> Dict[str, Any]:
        """Safely resolve a document inside the company_data root and return its numbered lines."""
        cleaned = rel_or_abs_path.strip()
        p_obj = Path(cleaned)
        if p_obj.is_absolute():
            try:
                rel_candidate = str(p_obj.relative_to(self.loader.base_dir))
            except ValueError as exc:
                raise PermissionError(f"Access denied outside data root: {cleaned}") from exc
        else:
            rel_candidate = cleaned
            if rel_candidate.startswith("company_data/"):
                rel_candidate = rel_candidate[len("company_data/"):]

        resolved = self.loader.resolve_path(rel_candidate)
        text = resolved.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        return {
            "file_path": str(resolved.relative_to(self.loader.base_dir)),
            "absolute_path": str(resolved),
            "title": resolved.name,
            "total_lines": len(lines),
            "lines": lines,
        }


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>COBACK AI Compliance Gap Analysis — Interactive Workbench</title>
  <style>
    :root {
      --bg: #f4f6fa;
      --surface: #ffffff;
      --surface-alt: #f8fafc;
      --border: #dbe2ec;
      --text: #0f172a;
      --muted: #475569;
      --primary: #1d4ed8;
      --primary-soft: #eff6ff;
      --open-bg: #fef2f2;
      --open-fg: #b91c1c;
      --open-bd: #fecaca;
      --miss-bg: #fffbeb;
      --miss-fg: #b45309;
      --miss-bd: #fde68a;
      --met-bg: #ecfdf5;
      --met-fg: #047857;
      --met-bd: #a7f3d0;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    header {
      background: #0f172a;
      color: #f8fafc;
      padding: 18px 28px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      border-bottom: 3px solid #2563eb;
    }
    header h1 {
      margin: 0;
      font-size: 1.25rem;
      letter-spacing: -0.01em;
    }
    header .meta {
      font-size: 0.84rem;
      color: #cbd5e1;
      margin-top: 3px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    button, select {
      font-family: inherit;
      font-size: 0.88rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      padding: 8px 13px;
      cursor: pointer;
    }
    select {
      background: #ffffff;
      color: var(--text);
      font-weight: 600;
      min-width: 310px;
    }
    .btn-primary {
      background: #2563eb;
      color: #ffffff;
      border-color: #2563eb;
      font-weight: 600;
    }
    .btn-primary:hover { background: #1d4ed8; }
    .btn-secondary {
      background: #1e293b;
      color: #f8fafc;
      border-color: #334155;
    }
    .btn-secondary:hover { background: #334155; }
    .btn-outline {
      background: #ffffff;
      color: var(--text);
      font-weight: 500;
    }
    .btn-outline:hover { background: var(--surface-alt); }
    .container {
      max-width: 1380px;
      margin: 22px auto;
      padding: 0 22px 48px;
    }
    .duty-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }
    .duty-tab {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 14px;
      display: flex;
      align-items: center;
      gap: 10px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .duty-tab.active {
      border-color: #2563eb;
      background: var(--primary-soft);
      box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.18);
    }
    .badge {
      display: inline-block;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 0.74rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .badge-open, .badge-confirmed_shortfall {
      background: var(--open-bg); color: var(--open-fg); border: 1px solid var(--open-bd);
    }
    .badge-evidence_missing, .badge-insufficient_evidence, .badge-conflicting_evidence {
      background: var(--miss-bg); color: var(--miss-fg); border: 1px solid var(--miss-bd);
    }
    .badge-met, .badge-supported {
      background: var(--met-bg); color: var(--met-fg); border: 1px solid var(--met-bd);
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px 22px;
      margin-bottom: 18px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .card h2 {
      margin: 0 0 12px;
      font-size: 1.08rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .grid-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }
    @media (max-width: 960px) {
      .grid-2 { grid-template-columns: 1fr; }
    }
    .reason-box {
      background: var(--surface-alt);
      border-left: 4px solid #2563eb;
      padding: 12px 15px;
      border-radius: 6px;
      margin: 10px 0 16px;
      font-size: 0.94rem;
    }
    .component-item {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px 16px;
      margin-bottom: 12px;
      background: #fcfdff;
    }
    .component-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 6px;
    }
    .doc-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #eff6ff;
      color: #1d4ed8;
      border: 1px solid #bfdbfe;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      margin: 4px 6px 4px 0;
    }
    .doc-link:hover {
      background: #dbeafe;
    }
    .passage-quote {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.81rem;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 8px 10px;
      margin-top: 6px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .missing-box {
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: 8px;
      padding: 10px 12px;
      margin-top: 8px;
      font-size: 0.88rem;
      color: #78350f;
    }
    ul.clean-list {
      margin: 6px 0 0;
      padding-left: 20px;
    }
    ul.clean-list li {
      margin-bottom: 8px;
      font-size: 0.9rem;
    }
    .source-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 7px 10px;
      border-bottom: 1px solid #eef2f6;
      font-size: 0.86rem;
    }
    .source-row:last-child { border-bottom: none; }
    .tag-pill {
      font-size: 0.72rem;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 600;
    }
    .tag-cited { background: #dbeafe; color: #1e40af; }
    .tag-excl { background: #fee2e2; color: #991b1b; }
    .tag-scan { background: #f1f5f9; color: #475569; }

    /* Document Viewer Modal */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.62);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 20px;
    }
    .modal-backdrop.open { display: flex; }
    .modal-panel {
      background: #ffffff;
      width: min(1050px, 96vw);
      max-height: 88vh;
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 20px 45px rgba(0, 0, 0, 0.28);
    }
    .modal-header {
      padding: 14px 18px;
      background: #0f172a;
      color: #f8fafc;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    .modal-body {
      overflow-y: auto;
      padding: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.83rem;
      background: #ffffff;
    }
    .code-line {
      display: flex;
      padding: 2px 14px;
      border-bottom: 1px solid #f8fafc;
    }
    .code-line.highlight {
      background: #fef08a;
      font-weight: 600;
    }
    .line-no {
      width: 54px;
      flex-shrink: 0;
      color: #94a3b8;
      user-select: none;
      text-align: right;
      padding-right: 14px;
    }
    .line-text {
      white-space: pre-wrap;
      word-break: break-word;
      flex: 1;
    }
    .status-banner {
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      color: #1e3a8a;
      padding: 10px 14px;
      border-radius: 8px;
      margin-bottom: 16px;
      display: none;
      font-size: 0.9rem;
    }
    .status-banner.visible { display: block; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>COBACK AI Compliance Gap Analysis</h1>
      <div class="meta" id="headerMeta">Loading assessment metadata...</div>
    </div>
    <div class="toolbar">
      <select id="dutySelect" aria-label="Select Legal Duty"></select>
      <button class="btn-secondary" onclick="triggerRun(false)" title="Fast deterministic run without Ollama">Run Fast Baseline</button>
      <button class="btn-primary" onclick="triggerRun(true)" title="Full semantic audit using local Ollama LLM">Re-run with Ollama LLM</button>
    </div>
  </header>

  <div class="container">
    <div id="statusBanner" class="status-banner"></div>

    <!-- Quick Duty Selector Pills -->
    <div class="duty-tabs" id="dutyTabs"></div>

    <!-- 1. Selected Duty Result: Duty ID, State, Reason, Available Evidence & Missing Facts -->
    <div class="card" id="selectedDutyCard"></div>

    <!-- 2. Clickable Supporting & Cited Company Documents -->
    <div class="card" id="supportingDocsCard"></div>

    <!-- 3. Separate Lists of Supported Gaps and Evidence Questions -->
    <div class="grid-2">
      <div class="card" id="supportedGapsCard"></div>
      <div class="card" id="evidenceQuestionsCard"></div>
    </div>

    <!-- 4. Record of Sources Searched & How Document Versions / Register Statuses Influenced Decision -->
    <div class="grid-2">
      <div class="card" id="searchedSourcesCard"></div>
      <div class="card" id="decisionInfluenceCard"></div>
    </div>
  </div>

  <!-- Interactive Document Viewer Modal -->
  <div class="modal-backdrop" id="docModal" onclick="if (event.target === this) closeDocModal();">
    <div class="modal-panel">
      <div class="modal-header">
        <div>
          <strong id="modalDocTitle">Document</strong>
          <div style="font-size:0.78rem;color:#cbd5e1;" id="modalDocSubtitle"></div>
        </div>
        <div style="display:flex;gap:8px;">
          <button class="btn-outline" id="openNativeBtn">Open File on Mac</button>
          <button class="btn-primary" onclick="closeDocModal()">Close</button>
        </div>
      </div>
      <div class="modal-body" id="modalDocBody"></div>
    </div>
  </div>

  <script>
    let reportData = null;
    let selectedDutyId = null;
    let currentModalPath = null;

    function esc(str) {
      if (str === null || str === undefined) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function showBanner(msg) {
      const el = document.getElementById("statusBanner");
      el.textContent = msg;
      el.classList.add("visible");
    }

    function hideBanner() {
      document.getElementById("statusBanner").classList.remove("visible");
    }

    async function loadReport(force = false, useLlm = true) {
      showBanner(force ? "Running compliance assessment (watch terminal for batch progress)..." : "Loading compliance report...");
      try {
        const url = force ? `/api/run?use_llm=${useLlm ? "1" : "0"}` : "/api/report";
        const resp = await fetch(url);
        const data = await resp.json();
        if (!resp.ok) {
          showBanner("Error: " + (data.error || resp.statusText));
          return;
        }
        reportData = data;
        hideBanner();
        if (!selectedDutyId && reportData.results && reportData.results.length > 0) {
          selectedDutyId = reportData.results[0].duty_id;
        }
        renderAll();
      } catch (err) {
        showBanner("Failed to load report: " + err.message);
      }
    }

    function triggerRun(useLlm) {
      loadReport(true, useLlm);
    }

    function selectDuty(dutyId) {
      selectedDutyId = dutyId;
      document.getElementById("dutySelect").value = dutyId;
      renderAll();
    }

    function renderAll() {
      if (!reportData) return;

      document.getElementById("headerMeta").textContent =
        `${reportData.assessment_entity} (${reportData.entity_code}) | As of ${reportData.as_of_date} | ${reportData.evaluation_mode}`;

      const selectEl = document.getElementById("dutySelect");
      selectEl.innerHTML = reportData.results.map(r =>
        `<option value="${esc(r.duty_id)}">${esc(r.duty_id)} — ${esc(r.duty_title)} [${esc(r.state.toUpperCase())}]</option>`
      ).join("");
      selectEl.value = selectedDutyId;
      selectEl.onchange = (e) => selectDuty(e.target.value);

      const tabsEl = document.getElementById("dutyTabs");
      tabsEl.innerHTML = reportData.results.map(r => `
        <div class="duty-tab ${r.duty_id === selectedDutyId ? "active" : ""}" onclick="selectDuty('${esc(r.duty_id)}')">
          <div>
            <div style="font-weight:700;font-size:0.9rem;">${esc(r.duty_id)}</div>
            <div style="font-size:0.78rem;color:#475569;">${esc(r.duty_title)}</div>
          </div>
          <span class="badge badge-${esc(r.state)}">${esc(r.state)}</span>
        </div>
      `).join("");

      const duty = reportData.results.find(r => r.duty_id === selectedDutyId) || reportData.results[0];
      renderSelectedDuty(duty);
      renderSupportingDocs(duty);
      renderSupportedGaps(duty);
      renderEvidenceQuestions(duty);
      renderSearchedSources(duty);
      renderDecisionInfluence(duty);
    }

    function renderSelectedDuty(duty) {
      const card = document.getElementById("selectedDutyCard");
      const componentsHtml = duty.components.map(c => {
        const citsHtml = (c.citations || []).map(cit => `
          <button class="doc-link" onclick="openDoc('${esc(cit.file_path)}', '${esc(cit.location)}', '${esc(cit.source_id)}')">
            📄 ${esc(cit.source_id)} (${esc(cit.location)})
          </button>
        `).join("");

        const missingHtml = (c.status !== "supported" && c.limitations && c.limitations.length > 0)
          ? `<div class="missing-box"><strong>Missing Facts / Audit Limitations:</strong> ${esc(c.limitations.join(" | "))}</div>`
          : "";

        return `
          <div class="component-item">
            <div class="component-header">
              <strong>${esc(c.component_id)} — ${esc(c.name)}</strong>
              <span class="badge badge-${esc(c.status)}">${esc(c.status)}</span>
            </div>
            <div style="font-size:0.84rem;color:#475569;margin-bottom:6px;"><em>Requirement:</em> ${esc(c.clause_text)}</div>
            <div style="font-size:0.92rem;"><strong>Assessment:</strong> ${esc(c.rationale)}</div>
            <div style="margin-top:8px;">${citsHtml || '<span style="font-size:0.82rem;color:#64748b;">No direct supporting record cited.</span>'}</div>
            ${missingHtml}
          </div>
        `;
      }).join("");

      const missingRecordBanner = duty.actionable_request ? `
        <div class="missing-box" style="margin-bottom:14px;">
          <strong>Record of Missing Facts (${esc(duty.duty_id)}):</strong><br/>
          ${esc(duty.actionable_request.missing_fact)}
        </div>
      ` : "";

      card.innerHTML = `
        <h2>
          <span>Duty <code>${esc(duty.duty_id)}</code>: ${esc(duty.duty_title)} <span style="color:#475569;font-weight:500;">(${esc(duty.statutory_ref)})</span></span>
          <span class="badge badge-${esc(duty.state)}" style="font-size:0.86rem;padding:5px 12px;">${esc(duty.state)}</span>
        </h2>
        <div class="reason-box"><strong>Decision Reason:</strong> ${esc(duty.reason)}</div>
        ${missingRecordBanner}
        <h3 style="font-size:0.96rem;margin:12px 0 10px;">Requirement Clauses — Available Company Evidence vs. Missing Facts</h3>
        ${componentsHtml}
      `;
    }

    function renderSupportingDocs(duty) {
      const card = document.getElementById("supportingDocsCard");
      const uniqueCits = [];
      const seen = new Set();
      for (const c of duty.components) {
        for (const cit of (c.citations || [])) {
          const k = `${cit.source_id}|${cit.location}`;
          if (!seen.has(k)) {
            seen.add(k);
            uniqueCits.push(cit);
          }
        }
      }

      if (uniqueCits.length === 0) {
        card.innerHTML = `
          <h2>Supplied Company Evidence & Supporting Documents (${esc(duty.duty_id)})</h2>
          <p style="color:#475569;font-size:0.9rem;">No active supporting company documents were matched for this duty as of ${esc(reportData.as_of_date)}.</p>
        `;
        return;
      }

      const items = uniqueCits.map(cit => `
        <div class="component-item">
          <div class="component-header">
            <div>
              <button class="doc-link" onclick="openDoc('${esc(cit.file_path)}', '${esc(cit.location)}', '${esc(cit.source_id)}')">
                🔍 Open ${esc(cit.source_id)} — ${esc(cit.document_title)}
              </button>
              <span style="font-size:0.8rem;color:#475569;">
                Path: <code>${esc(cit.file_path)}</code> | Location: <strong>${esc(cit.location)}</strong>
                ${cit.version ? ` | Version: <strong>v${esc(cit.version)}</strong>` : ""}
                ${cit.status ? ` | Status: <strong>${esc(cit.status)}</strong>` : ""}
              </span>
            </div>
          </div>
          <div style="font-size:0.88rem;margin-top:4px;"><strong>What this record shows:</strong> ${esc(cit.demonstrates)}</div>
          <div class="passage-quote">${esc(cit.exact_passage)}</div>
        </div>
      `).join("");

      card.innerHTML = `
        <h2>Supplied Company Evidence & Clickable Source Documents (${esc(duty.duty_id)})</h2>
        ${items}
      `;
    }

    function renderSupportedGaps(duty) {
      const card = document.getElementById("supportedGapsCard");
      const allGaps = reportData.supported_gaps || [];
      if (allGaps.length === 0) {
        card.innerHTML = `
          <h2>Supported Gaps (Confirmed Shortfalls)</h2>
          <p style="color:#475569;font-size:0.9rem;">No confirmed overdue shortfalls identified across assessed duties.</p>
        `;
        return;
      }

      const html = allGaps.map(g => {
        const isCurrent = g.duty_id === duty.duty_id;
        const cits = (g.citations || []).map(cit => `
          <button class="doc-link" onclick="openDoc('${esc(cit.file_path)}', '${esc(cit.location)}', '${esc(cit.source_id)}')">
            📄 ${esc(cit.source_id)} (${esc(cit.location)})
          </button>
        `).join("");
        return `
          <li style="${isCurrent ? "background:#fef2f2;padding:8px 10px;border-radius:8px;border:1px solid #fecaca;" : ""}">
            <strong>[${esc(g.duty_id)}] ${esc(g.component_name)}</strong> (${esc(g.statutory_ref)}):<br/>
            <span>${esc(g.shortfall_description)}</span><br/>
            ${cits}
          </li>
        `;
      }).join("");

      card.innerHTML = `
        <h2>Supported Gaps — Confirmed Shortfalls (${allGaps.length})</h2>
        <ul class="clean-list">${html}</ul>
      `;
    }

    function renderEvidenceQuestions(duty) {
      const card = document.getElementById("evidenceQuestionsCard");
      const reqs = reportData.evidence_requests || [];
      if (reqs.length === 0) {
        card.innerHTML = `
          <h2>Evidence Questions (Follow-up Requests)</h2>
          <p style="color:#475569;font-size:0.9rem;">All duties met; no follow-up evidence questions needed.</p>
        `;
        return;
      }

      const html = reqs.map(q => {
        const isCurrent = q.duty_id === duty.duty_id;
        return `
          <li style="${isCurrent ? "background:#fffbeb;padding:8px 10px;border-radius:8px;border:1px solid #fde68a;" : ""}">
            <strong>[${esc(q.duty_id)}] ${esc(q.duty_title)}</strong><br/>
            <span style="color:#1e293b;">${esc(q.focused_question)}</span>
          </li>
        `;
      }).join("");

      card.innerHTML = `
        <h2>Evidence Questions — Follow-up Audit Requests (${reqs.length})</h2>
        <ul class="clean-list">${html}</ul>
      `;
    }

    function renderSearchedSources(duty) {
      const card = document.getElementById("searchedSourcesCard");
      const citedPaths = new Set();
      for (const c of duty.components) {
        for (const cit of (c.citations || [])) {
          citedPaths.add(cit.file_path);
        }
      }
      const excludedByPath = {};
      for (const ex of (duty.exclusion_log || [])) {
        excludedByPath[ex.file_path] = ex.disposition;
      }

      const searched = duty.sources_reviewed || [];
      const rows = searched.map(fp => {
        let tag = `<span class="tag-pill tag-scan">Searched</span>`;
        if (citedPaths.has(fp)) {
          tag = `<span class="tag-pill tag-cited">Cited in Verdict</span>`;
        } else if (excludedByPath[fp]) {
          tag = `<span class="tag-pill tag-excl">Excluded (${esc(excludedByPath[fp])})</span>`;
        }
        return `
          <div class="source-row">
            <a href="javascript:void(0)" onclick="openDoc('${esc(fp)}', '', '${esc(fp)}')" style="color:#1d4ed8;text-decoration:none;font-family:monospace;">
              ${esc(fp)}
            </a>
            ${tag}
          </div>
        `;
      }).join("");

      card.innerHTML = `
        <h2>Sources Searched for ${esc(duty.duty_id)} (${searched.length} files)</h2>
        <div>${rows || '<span style="color:#64748b;">No sources logged.</span>'}</div>
      `;
    }

    function renderDecisionInfluence(duty) {
      const card = document.getElementById("decisionInfluenceCard");
      const notes = duty.decision_influence || [];
      const items = notes.map(n => `<li>${esc(n)}</li>`).join("");
      card.innerHTML = `
        <h2>How Document Versions & Register Statuses Influenced ${esc(duty.duty_id)}</h2>
        <ul class="clean-list">${items}</ul>
      `;
    }

    async function openDoc(filePath, locationStr, titleLabel) {
      currentModalPath = filePath;
      document.getElementById("modalDocTitle").textContent = titleLabel || filePath;
      document.getElementById("modalDocSubtitle").textContent = `${filePath}${locationStr ? " — " + locationStr : ""}`;
      document.getElementById("modalDocBody").innerHTML = `<div style="padding:18px;">Loading document...</div>`;
      document.getElementById("docModal").classList.add("open");

      document.getElementById("openNativeBtn").onclick = () => {
        fetch(`/api/open-native?path=${encodeURIComponent(filePath)}`);
      };

      try {
        const resp = await fetch(`/api/doc?path=${encodeURIComponent(filePath)}&location=${encodeURIComponent(locationStr || "")}`);
        const data = await resp.json();
        if (!resp.ok) {
          document.getElementById("modalDocBody").innerHTML = `<div style="padding:18px;color:#b91c1c;">${esc(data.error)}</div>`;
          return;
        }
        const startLine = data.highlight_start;
        const endLine = data.highlight_end;

        const linesHtml = data.lines.map((lineText, idx) => {
          const lineNum = idx + 1;
          const isHl = startLine !== null && endLine !== null && lineNum >= startLine && lineNum <= endLine;
          return `
            <div class="code-line ${isHl ? "highlight" : ""}" id="doc-line-${lineNum}">
              <div class="line-no">${lineNum}</div>
              <div class="line-text">${esc(lineText) || "&nbsp;"}</div>
            </div>
          `;
        }).join("");

        document.getElementById("modalDocBody").innerHTML = linesHtml;
        if (startLine !== null) {
          const targetEl = document.getElementById(`doc-line-${Math.max(1, startLine - 2)}`);
          if (targetEl) targetEl.scrollIntoView({ block: "center" });
        }
      } catch (err) {
        document.getElementById("modalDocBody").innerHTML = `<div style="padding:18px;color:#b91c1c;">${esc(err.message)}</div>`;
      }
    }

    function closeDocModal() {
      document.getElementById("docModal").classList.remove("open");
    }

    loadReport(false, true);
  </script>
</body>
</html>
"""


def create_request_handler(state: ComplianceWorkbenchState):
    class WorkbenchHandler(BaseHTTPRequestHandler):
        def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html_text: str) -> None:
            body = html_text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)

            if parsed.path == "/":
                self._send_html(HTML_PAGE)
                return

            if parsed.path == "/api/report":
                try:
                    data = state.get_report(use_llm=True, force_rerun=False)
                    self._send_json(HTTPStatus.OK, data)
                except Exception as exc:
                    self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            if parsed.path == "/api/run":
                use_llm = qs.get("use_llm", ["1"])[0] != "0"
                try:
                    data = state.get_report(use_llm=use_llm, force_rerun=True)
                    self._send_json(HTTPStatus.OK, data)
                except Exception as exc:
                    self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            if parsed.path == "/api/doc":
                doc_path = qs.get("path", [""])[0]
                loc_str = qs.get("location", [""])[0]
                if not doc_path:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Missing 'path' query parameter."})
                    return
                try:
                    doc_data = state.read_document(doc_path)
                    start_ln, end_ln = parse_line_range(loc_str)
                    doc_data["highlight_start"] = start_ln
                    doc_data["highlight_end"] = end_ln
                    self._send_json(HTTPStatus.OK, doc_data)
                except (PermissionError, ValueError) as exc:
                    self._send_json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
                except FileNotFoundError as exc:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except Exception as exc:
                    self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return

            if parsed.path == "/api/open-native":
                doc_path = qs.get("path", [""])[0]
                try:
                    doc_data = state.read_document(doc_path)
                    abs_path = doc_data["absolute_path"]
                    sys_name = platform.system()
                    if sys_name == "Darwin":
                        subprocess.Popen(["open", abs_path])
                    elif sys_name == "Windows":
                        subprocess.Popen(["cmd", "/c", "start", "", abs_path])
                    else:
                        subprocess.Popen(["xdg-open", abs_path])
                    self._send_json(HTTPStatus.OK, {"opened": abs_path})
                except Exception as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {parsed.path}"})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return WorkbenchHandler

def serve_ui(
    data_dir: Path,
    output_dir: Path = Path("outputs"),
    as_of_date: str = "2026-11-18",
    entity: str = "Marenthal Chemie AG",
    ollama_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    state = ComplianceWorkbenchState(
        data_dir=data_dir,
        output_dir=output_dir,
        as_of_date=as_of_date,
        target_entity=entity,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
    )
    host = "127.0.0.1"
    server = ThreadingHTTPServer((host, port), create_request_handler(state))
    actual_port = server.server_address[1]
    scheme = "http"
    url = f"{scheme}://{host}:{actual_port}/"
    print(f"[OK] COBACK Compliance UI running at: {url}", flush=True)
    print("     Press Ctrl+C to stop the local server.", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down local UI server.")
    finally:
        server.server_close()

def main() -> None:
    parser = argparse.ArgumentParser(description="COBACK Local Interactive Compliance Web UI")
    parser.add_argument("--data-dir", type=Path, default=Path("."), help="Path to data root or company_data directory")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"), help="Directory for JSON/Markdown reports")
    parser.add_argument("--as-of-date", type=str, default="2026-11-18", help="Assessment reference date (YYYY-MM-DD)")
    parser.add_argument("--entity", type=str, default="Marenthal Chemie AG", help="Target legal entity name or code")
    parser.add_argument("--ollama-url", type=str, default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--ollama-model", type=str, default="llama3.2", help="Ollama model name")
    parser.add_argument("--port", type=int, default=8765, help="Local HTTP port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser tab")
    args = parser.parse_args()

    serve_ui(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        as_of_date=args.as_of_date,
        entity=args.entity,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()