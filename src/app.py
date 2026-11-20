"""
Regulatory Compliance Engine (Pilot) - Web Workspace.
Provides a local UI to inspect duties, sub-components, exclusion logs,
and open referenced source documents in an interactive viewer.
"""
from pathlib import Path
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader

app = FastAPI(title="Regulatory Compliance Engine (Pilot)")

loader = DataLoader(Path("."))
analyzer = ComplianceAnalyzer(loader, as_of_date="2026-11-18")

# Cache precomputed assessment for instant, reproducible UI inspection
REPORT = analyzer.run_assessment()


@app.get("/api/duties")
def list_duties():
    return [
        {
            "id": r.duty_id,
            "ref": r.statutory_ref,
            "title": r.duty_title,
            "state": r.state.value,
        }
        for r in REPORT.results
    ]


@app.get("/api/evaluate/{duty_id}")
def get_duty_evaluation(duty_id: str):
    res = next((r for r in REPORT.results if r.duty_id == duty_id), None)
    if not res:
        raise HTTPException(status_code=404, detail="Duty ID not found")
    return res.model_dump()


@app.get("/api/document")
def get_document_content(file_path: str = Query(..., description="File path relative to data")):
    try:
        resolved, lines = loader.load_text_with_lines(file_path)
        return {
            "file_name": resolved.name,
            "full_path": str(resolved),
            "content": "".join(lines),
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Document not found: {e}")


@app.get("/", response_class=HTMLResponse)
def index_ui():
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Regulatory Compliance Analysis Workspace</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col font-sans">
  <header class="bg-slate-800 border-b border-slate-700 px-8 py-4 flex items-center justify-between shadow-lg">
    <div class="flex items-center space-x-3">
      <div class="h-9 w-9 bg-blue-600 rounded-lg flex items-center justify-center font-bold text-lg text-white shadow-md">
        <i class="fa-solid fa-scale-balanced"></i>
      </div>
      <div>
        <h1 class="text-xl font-bold tracking-tight">Compliance AI Engine <span class="text-blue-400 font-normal text-sm">| Pilot Analysis</span></h1>
        <p class="text-xs text-slate-400">Target: Marenthal Chemie AG (DE) · As-of Snapshot: 2026-11-18</p>
      </div>
    </div>
    <div class="flex items-center space-x-4">
      <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
        <span class="h-2 w-2 rounded-full bg-blue-400 mr-2 animate-pulse"></span> Component Evaluator Active
      </span>
    </div>
  </header>

  <main class="flex-1 max-w-7xl w-full mx-auto p-8 grid grid-cols-12 gap-8">
    <!-- Left Pane: Duty Selector -->
    <aside class="col-span-4 bg-slate-800/80 rounded-xl border border-slate-700 p-5 flex flex-col shadow-xl">
      <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-4 flex items-center">
        <i class="fa-solid fa-list-check mr-2 text-blue-400"></i> Select Statutory Duty
      </h2>
      <div id="duty-list" class="space-y-3 flex-1 overflow-y-auto">
        <!-- Injected by JavaScript -->
      </div>
      <div class="mt-6 pt-4 border-t border-slate-700/60 text-xs text-slate-400">
        <p><i class="fa-solid fa-shield-halved mr-1 text-slate-500"></i> Silence or scope mismatch is treated as missing evidence, not an assumption of failure.</p>
      </div>
    </aside>

    <!-- Right Pane: Component Matrix & Audit Trail -->
    <section class="col-span-8 space-y-6">
      <!-- Overview Card -->
      <div class="bg-slate-800/90 rounded-xl border border-slate-700 p-6 shadow-xl relative">
        <div class="flex items-start justify-between">
          <div>
            <span id="statutory-ref" class="text-xs font-mono px-2 py-0.5 rounded bg-slate-700 text-slate-300"></span>
            <h2 id="duty-title" class="text-xl font-bold mt-2 text-white">Loading...</h2>
          </div>
          <div id="state-badge-container"></div>
        </div>
        <div class="mt-4 p-4 rounded-lg bg-slate-900/70 border border-slate-700/50">
          <h3 class="text-xs font-semibold uppercase text-slate-400 mb-1">Duty Synthesis:</h3>
          <p id="duty-reason" class="text-sm text-slate-200 leading-relaxed"></p>
        </div>
      </div>

      <!-- Component Breakdown Matrix -->
      <div class="bg-slate-800/90 rounded-xl border border-slate-700 p-6 shadow-xl">
        <h3 class="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-4 flex items-center">
          <i class="fa-solid fa-cubes-stacked mr-2 text-blue-400"></i> Statutory Component Matrix (Teilpflichten)
        </h3>
        <div id="components-container" class="space-y-4">
          <!-- Components injected here -->
        </div>
      </div>

      <!-- Actionable Follow-up / Gap Notice -->
      <div id="followup-card" class="bg-slate-800/90 rounded-xl border border-slate-700 p-6 shadow-xl hidden">
        <!-- Injected here -->
      </div>

      <!-- Exclusion & Limitation Log -->
      <div class="bg-slate-800/90 rounded-xl border border-slate-700 p-6 shadow-xl">
        <h3 class="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center">
          <i class="fa-solid fa-file-excel mr-2 text-purple-400"></i> Document Exclusion & Scope Limitation Log
        </h3>
        <div id="exclusion-container" class="space-y-2 text-xs text-slate-300">
          <!-- Exclusions injected here -->
        </div>
      </div>
    </section>
  </main>

  <!-- Document Modal Viewer -->
  <div id="doc-modal" class="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center hidden p-6">
    <div class="bg-slate-800 rounded-xl border border-slate-600 max-w-4xl w-full max-h-[85vh] flex flex-col shadow-2xl">
      <div class="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <i class="fa-solid fa-file-lines text-blue-400 text-lg"></i>
          <div>
            <h3 id="modal-doc-title" class="font-bold text-white text-base">Document Viewer</h3>
            <p id="modal-doc-path" class="text-xs font-mono text-slate-400"></p>
          </div>
        </div>
        <button onclick="closeModal()" class="text-slate-400 hover:text-white p-1 rounded-lg">
          <i class="fa-solid fa-xmark text-lg"></i>
        </button>
      </div>
      <div class="p-6 overflow-y-auto flex-1 font-mono text-xs bg-slate-950 text-slate-300 whitespace-pre-wrap leading-relaxed" id="modal-doc-content">
        Loading...
      </div>
      <div class="px-6 py-3 border-t border-slate-700 bg-slate-850 flex justify-end">
        <button onclick="closeModal()" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-medium">Close</button>
      </div>
    </div>
  </div>

  <script>
    async function loadDuties() {
      try {
        const res = await fetch('/api/duties');
        const duties = await res.json();
        const list = document.getElementById('duty-list');
        list.innerHTML = '';

        duties.forEach((d, idx) => {
          const div = document.createElement('div');
          div.className = `p-4 rounded-lg cursor-pointer border transition-all ${idx === 0 ? 'bg-blue-600/20 border-blue-500 text-white' : 'bg-slate-700/40 border-slate-600/50 hover:bg-slate-700 text-slate-300'}`;
          div.onclick = () => selectDuty(d.id, div);
          div.innerHTML = `
            <div class="flex items-center justify-between mb-1">
              <span class="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-slate-800 text-blue-400">${d.id}</span>
              <span class="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${d.state === 'open' ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'}">${d.state}</span>
            </div>
            <p class="text-xs font-medium leading-snug">${d.title}</p>
          `;
          list.appendChild(div);
        });

        if (duties.length > 0) {
          selectDuty(duties[0].id, list.children[0]);
        }
      } catch (err) {
        console.error('Failed to load duties:', err);
      }
    }

    async function selectDuty(dutyId, element) {
      document.querySelectorAll('#duty-list > div').forEach(el => {
        el.className = 'p-4 rounded-lg cursor-pointer border transition-all bg-slate-700/40 border-slate-600/50 hover:bg-slate-700 text-slate-300';
      });
      if (element) {
        element.className = 'p-4 rounded-lg cursor-pointer border transition-all bg-blue-600/20 border-blue-500 text-white shadow-md';
      }

      const res = await fetch(`/api/evaluate/${dutyId}`);
      const data = await res.json();
      renderEvaluation(data);
    }

    function renderEvaluation(data) {
      document.getElementById('duty-title').innerText = `${data.duty_id} · ${data.duty_title}`;
      document.getElementById('statutory-ref').innerText = data.statutory_ref;
      document.getElementById('duty-reason').innerText = data.reason;

      // Aggregated badge
      const badge = document.getElementById('state-badge-container');
      if (data.state === 'open') {
        badge.innerHTML = '<span class="px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40 flex items-center"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i> OPEN (Confirmed Gap)</span>';
      } else {
        badge.innerHTML = '<span class="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center"><i class="fa-solid fa-circle-question mr-1.5"></i> EVIDENCE MISSING</span>';
      }

      // Render Sub-components
      const compCont = document.getElementById('components-container');
      compCont.innerHTML = '';
      data.components.forEach(c => {
        const cCard = document.createElement('div');
        cCard.className = 'p-4 rounded-lg bg-slate-900/80 border border-slate-700/80';
        
        let statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300">SUPPORTED</span>';
        if (c.status === 'confirmed_shortfall') {
          statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300">CONFIRMED SHORTFALL</span>';
        } else if (c.status === 'conflicting_evidence') {
          statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-orange-500/20 text-orange-300">CONFLICTING / STALE</span>';
        } else if (c.status === 'insufficient_evidence') {
          statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300">INSUFFICIENT EVIDENCE</span>';
        }

        let citationsHtml = '';
        if (c.citations && c.citations.length > 0) {
          citationsHtml = '<div class="mt-3 space-y-2">';
          c.citations.forEach(cit => {
            citationsHtml += `
              <div onclick="openDocumentModal('${cit.file_path}', '${encodeURIComponent(cit.exact_passage)}')" class="p-2.5 rounded bg-slate-950 border border-slate-800 hover:border-blue-500 cursor-pointer transition-all">
                <div class="flex justify-between items-center text-[11px] text-blue-400 mb-1">
                  <span class="font-mono flex items-center"><i class="fa-solid fa-arrow-up-right-from-square mr-1 text-[9px]"></i> ${cit.source_id} (${cit.document_title})</span>
                  <span class="text-slate-400 text-[10px]">${cit.location}</span>
                </div>
                <div class="font-mono text-[11px] text-amber-200/90 whitespace-pre-wrap">${cit.exact_passage}</div>
              </div>
            `;
          });
          citationsHtml += '</div>';
        }

        let limitationsHtml = '';
        if (c.limitations && c.limitations.length > 0) {
          limitationsHtml = `<div class="mt-2 text-[11px] text-slate-400 italic"><i class="fa-solid fa-circle-info mr-1 text-slate-500"></i> ${c.limitations.join(' ')}</div>`;
        }

        cCard.innerHTML = `
          <div class="flex justify-between items-center mb-1.5">
            <h4 class="text-xs font-bold text-slate-200">${c.name}</h4>
            ${statusBadge}
          </div>
          <p class="text-xs text-slate-300">${c.rationale}</p>
          ${citationsHtml}
          ${limitationsHtml}
        `;
        compCont.appendChild(cCard);
      });

      // Follow-up Card
      const fuCard = document.getElementById('followup-card');
      if (data.actionable_request) {
        fuCard.className = 'bg-amber-950/30 rounded-xl border border-amber-500/30 p-6 shadow-xl block';
        fuCard.innerHTML = `
          <h3 class="text-sm font-semibold uppercase tracking-wider text-amber-400 mb-2 flex items-center">
            <i class="fa-solid fa-circle-question mr-2"></i> Actionable Evidence Request (Operational Clarification)
          </h3>
          <p class="text-xs font-semibold text-white mb-1">Missing Proof: <span class="font-normal text-slate-300">${data.actionable_request.missing_fact}</span></p>
          <div class="p-3 bg-amber-500/10 border border-amber-500/20 rounded text-xs text-amber-200 italic mt-2">
            "${data.actionable_request.focused_question}"
          </div>
        `;
      } else {
        fuCard.className = 'hidden';
      }

      // Exclusion log
      const exCont = document.getElementById('exclusion-container');
      if (data.exclusion_log && data.exclusion_log.length > 0) {
        exCont.innerHTML = data.exclusion_log.map(e => `
          <div class="p-2.5 rounded bg-slate-900/60 border border-slate-700/60 flex items-start space-x-2">
            <span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-purple-500/20 text-purple-300 uppercase">${e.disposition}</span>
            <div class="flex-1">
              <span class="font-mono text-slate-200 font-bold">${e.file_path}</span>
              <p class="text-slate-400 mt-0.5">${e.reason}</p>
            </div>
          </div>
        `).join('');
      } else {
        exCont.innerHTML = '<p class="text-slate-400 italic">No reviewed documents were excluded or scope-restricted for this duty.</p>';
      }
    }

    async function openDocumentModal(filePath, encodedQuote) {
      const modal = document.getElementById('doc-modal');
      const content = document.getElementById('modal-doc-content');
      document.getElementById('modal-doc-title').innerText = filePath.split('/').pop();
      document.getElementById('modal-doc-path').innerText = filePath;
      modal.classList.remove('hidden');

      try {
        const res = await fetch(`/api/document?file_path=${encodeURIComponent(filePath)}`);
        const data = await res.json();
        let raw = data.content;
        const decoded = decodeURIComponent(encodedQuote);
        const searchSnippet = decoded.trim().split('\\n')[0];
        if (searchSnippet && raw.includes(searchSnippet)) {
          raw = raw.replace(searchSnippet, `>>> [CITED PASSAGE] <<<\n${searchSnippet}\n>>> [END CITATION] <<<`);
        }
        content.innerText = raw;
      } catch (err) {
        content.innerText = 'Failed to load document: ' + err;
      }
    }

    function closeModal() {
      document.getElementById('doc-modal').classList.add('hidden');
    }

    // GUARANTEED INVOCATION ON LOAD
    window.addEventListener('DOMContentLoaded', loadDuties);
  </script>
</body>
</html>
    """
    return HTMLResponse(content=html)