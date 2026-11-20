"""Local evidence-review workspace for a precomputed assessment.

The existing analyzer runs once at application startup. Selecting a duty
displays its stored result; it does not trigger a new legal assessment.
"""

import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.analyzer import ComplianceAnalyzer
from src.loader import DataLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATA_ROOT = (
    PROJECT_ROOT
    / "data"
    / "COBACK_Marenthal_Inputs"
    / "company_data"
)

DATA_ROOT = Path(
    os.environ.get("COBACK_DATA_DIR", str(DEFAULT_DATA_ROOT))
).expanduser().resolve()

# Preserves the existing prototype's default. Verify this date against
# the assignment inputs before submission.
AS_OF_DATE = os.environ.get("COBACK_AS_OF", "2026-11-18")
date.fromisoformat(AS_OF_DATE)

if not (DATA_ROOT / "documents").is_dir():
    raise RuntimeError(
        "The configured input directory does not contain documents/.\n"
        f"Configured directory: {DATA_ROOT}\n"
        "Set COBACK_DATA_DIR to the parent of documents/."
    )

loader = DataLoader(DATA_ROOT)
analyzer = ComplianceAnalyzer(loader, as_of_date=AS_OF_DATE)

# Deliberately precomputed: the UI inspects a reproducible report.
REPORT = analyzer.run_assessment()

RESULTS_BY_ID = {
    result.duty_id: result
    for result in REPORT.results
}

# Only documents referenced by this report are exposed by the API.
ALLOWED_DOCUMENTS = {
    citation.file_path
    for result in REPORT.results
    for component in result.components
    for citation in component.citations
}
ALLOWED_DOCUMENTS.update(
    item.file_path
    for result in REPORT.results
    for item in result.exclusion_log
)

app = FastAPI(title="Coback Compliance Evidence Workspace")


@app.get("/api/assessment")
def get_assessment_summary():
    """Return report metadata without exposing local filesystem paths."""
    return {
        "assessment_entity": REPORT.assessment_entity,
        "as_of_date": REPORT.as_of_date,
        "total_duties_assessed": REPORT.total_duties_assessed,
        "execution_mode": "Precomputed assessment; selection does not rerun analysis.",
    }


@app.get("/api/duties")
def list_duties():
    """List independently selectable duty results."""
    return [
        {
            "id": result.duty_id,
            "ref": result.statutory_ref,
            "title": result.duty_title,
            "state": result.state.value,
        }
        for result in REPORT.results
    ]


@app.get("/api/evaluate/{duty_id}")
def get_duty_evaluation(duty_id: str):
    """Return only the requested duty."""
    result = RESULTS_BY_ID.get(duty_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown duty ID.",
        )

    return result.model_dump(mode="json")


@app.get("/api/document")
def get_document(file_path: str = Query(...)):
    """Read an allowlisted source from inside the configured data root."""
    if file_path not in ALLOWED_DOCUMENTS:
        raise HTTPException(
            status_code=404,
            detail="Document is not referenced by this assessment.",
        )

    try:
        path, lines = loader.load_text_with_lines(file_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Referenced document is missing from the input directory.",
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid document path.",
        ) from None
    except (OSError, UnicodeError):
        raise HTTPException(
            status_code=500,
            detail="The referenced document could not be read.",
        ) from None

    return {
        "file_name": path.name,
        "file_path": file_path,
        "content": "".join(lines),
    }


PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Compliance Evidence Workspace</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
    }

    * { box-sizing: border-box; }
    body { margin: 0; }
    button { font: inherit; }
    button:focus-visible, a:focus-visible {
      outline: 3px solid #60a5fa;
      outline-offset: 3px;
    }

    header {
      padding: 24px 32px;
      background: #1e293b;
      border-bottom: 1px solid #334155;
    }

    h1 { font-size: 24px; margin: 0 0 8px; }
    h2 { font-size: 21px; margin: 10px 0; }
    h3 { font-size: 15px; margin: 0 0 16px; }
    h4 { margin: 0; font-size: 15px; }
    p { line-height: 1.6; }
    .muted { color: #94a3b8; font-size: 13px; }
    .small { font-size: 12px; }
    .mono { font-family: ui-monospace, monospace; }
    .hidden { display: none !important; }

    .layout {
      max-width: 1500px;
      margin: 0 auto;
      padding: 28px;
      display: grid;
      grid-template-columns: 330px minmax(0, 1fr);
      gap: 24px;
      align-items: start;
    }

    .panel {
      padding: 22px;
      border: 1px solid #334155;
      border-radius: 14px;
      background: #1e293b;
    }

    .stack > * + * { margin-top: 20px; }

    .duty {
      display: block;
      width: 100%;
      padding: 16px;
      margin-top: 12px;
      text-align: left;
      color: #e2e8f0;
      background: #263449;
      border: 1px solid #475569;
      border-radius: 10px;
      cursor: pointer;
    }

    .duty:hover { border-color: #60a5fa; }
    .duty[aria-pressed="true"] {
      background: #20385c;
      border-color: #60a5fa;
      box-shadow: 0 0 0 1px #60a5fa;
    }

    .duty-top, .component-top, .modal-top {
      display: flex;
      gap: 12px;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
    }

    .duty-title { margin-top: 10px; line-height: 1.5; }
    .blue { color: #93c5fd; }

    .badge {
      display: inline-block;
      padding: 5px 8px;
      border-radius: 6px;
      font-size: 10px;
      font-weight: 750;
      letter-spacing: .03em;
    }

    .met, .supported { color: #6ee7b7; background: #064e3b; }
    .open, .confirmed_shortfall { color: #fda4af; background: #681c33; }
    .evidence_missing, .insufficient_evidence {
      color: #fcd34d;
      background: #5a421d;
    }
    .conflicting_evidence { color: #fdba74; background: #713c1c; }
    .unknown { color: #e2e8f0; background: #475569; }

    .component, .exclusion {
      margin-top: 14px;
      padding: 18px;
      background: #111c30;
      border: 1px solid #334155;
      border-radius: 10px;
    }

    .source {
      display: block;
      width: 100%;
      margin-top: 14px;
      padding: 14px;
      background: #080f20;
      color: #e2e8f0;
      border: 1px solid #334155;
      border-radius: 8px;
      text-align: left;
      cursor: pointer;
      overflow-wrap: anywhere;
    }

    .source:hover { border-color: #60a5fa; }

    .quote {
      color: #fde68a;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: 12px/1.7 ui-monospace, monospace;
      margin-bottom: 0;
    }

    .limitation { color: #cbd5e1; font-size: 12px; }
    .error { color: #fda4af; }
    .warning { color: #fcd34d; }

    .link {
      color: #93c5fd;
      background: transparent;
      border: 0;
      padding: 0;
      text-decoration: underline;
      cursor: pointer;
      overflow-wrap: anywhere;
      text-align: left;
    }

    dialog {
      width: min(1100px, 94vw);
      max-height: 90vh;
      padding: 0;
      color: #e2e8f0;
      background: #1e293b;
      border: 1px solid #64748b;
      border-radius: 12px;
    }

    dialog::backdrop { background: rgb(0 0 0 / 75%); }
    .modal-header { padding: 20px; border-bottom: 1px solid #475569; }
    .modal-title { margin: 0 0 8px; overflow-wrap: anywhere; }

    .close {
      padding: 8px 14px;
      border-radius: 6px;
      border: 1px solid #64748b;
      background: #334155;
      color: white;
      cursor: pointer;
    }

    #document-content {
      margin: 0;
      padding: 22px;
      height: 62vh;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: 12px/1.8 ui-monospace, monospace;
      background: #080f20;
    }

    #document-notice { padding: 0 20px; }
    mark { background: #fde047; color: #111827; }

    @media (max-width: 900px) {
      .layout { grid-template-columns: 1fr; padding: 16px; }
      header { padding: 20px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Compliance Evidence Workspace</h1>
    <div id="assessment-meta" class="muted">Loading assessment metadata…</div>
    <p class="muted small">
      Review interface for the existing prototype report.
      Duty selection displays stored findings; it does not rerun analysis.
      Findings require source verification before submission.
    </p>
  </header>

  <main class="layout">
    <aside class="panel">
      <h3>Select a duty</h3>
      <nav id="duty-list" aria-label="Assessment duties"></nav>
      <p class="muted">
        A source may be relevant to more than one duty.
        Shared citations do not mean the duty assessments are identical.
      </p>
    </aside>

    <section class="stack" aria-live="polite">
      <div class="panel">
        <div id="statutory-ref" class="mono muted"></div>
        <h2 id="duty-title">Loading…</h2>
        <div id="state-badge"></div>
        <p id="duty-reason"></p>
      </div>

      <div class="panel">
        <h3>Component-level findings</h3>
        <div id="components"></div>
      </div>

      <div id="followup" class="panel hidden"></div>

      <div class="panel">
        <h3>Version and scope limitations</h3>
        <div id="exclusions"></div>
      </div>
    </section>
  </main>

  <dialog id="document-dialog" aria-labelledby="document-title">
    <div class="modal-header">
      <div class="modal-top">
        <div>
          <h3 id="document-title" class="modal-title">Source document</h3>
          <div id="document-path" class="muted mono small"></div>
        </div>
        <button id="close-document" class="close" type="button">Close</button>
      </div>
    </div>
    <p id="document-notice" class="muted"></p>
    <pre id="document-content"></pre>
  </dialog>

  <script>
    "use strict";

    const $ = (id) => document.getElementById(id);
    let dutySequence = 0;
    let documentSequence = 0;

    const labels = {
      met: "MET",
      open: "OPEN — CONFIRMED GAP",
      evidence_missing: "EVIDENCE MISSING",
      supported: "SUPPORTED",
      confirmed_shortfall: "CONFIRMED SHORTFALL",
      insufficient_evidence: "INSUFFICIENT EVIDENCE",
      conflicting_evidence: "CONFLICTING EVIDENCE",
    };

    function element(tag, text = "", className = "") {
      const result = document.createElement(tag);
      result.textContent = text;
      result.className = className;
      return result;
    }

    function badge(status) {
      const known = Object.hasOwn(labels, status);
      return element(
        "span",
        known ? labels[status] : String(status || "UNKNOWN"),
        `badge ${known ? status : "unknown"}`,
      );
    }

    async function fetchJson(url) {
      const response = await fetch(url, { cache: "no-store" });
      let payload;

      try {
        payload = await response.json();
      } catch {
        throw new Error(`Invalid server response (${response.status}).`);
      }

      if (!response.ok) {
        const detail = typeof payload.detail === "string"
          ? payload.detail
          : `Request failed (${response.status}).`;
        throw new Error(detail);
      }

      return payload;
    }

    function clearDuty(message) {
      $("duty-title").textContent = message;
      $("statutory-ref").textContent = "";
      $("state-badge").replaceChildren();
      $("duty-reason").textContent = "";
      $("components").replaceChildren();
      $("exclusions").replaceChildren();
      $("followup").replaceChildren();
      $("followup").classList.add("hidden");
    }

    async function initialize() {
      try {
        const [metadata, duties] = await Promise.all([
          fetchJson("/api/assessment"),
          fetchJson("/api/duties"),
        ]);

        $("assessment-meta").textContent =
          `${metadata.assessment_entity} · As of ${metadata.as_of_date} · `
          + `${metadata.total_duties_assessed} duties`;

        const list = $("duty-list");
        list.replaceChildren();

        for (const duty of duties) {
          const button = element("button", "", "duty");
          button.type = "button";
          button.dataset.dutyId = duty.id;
          button.setAttribute("aria-pressed", "false");

          const top = element("div", "", "duty-top");
          top.append(
            element("span", duty.id, "mono blue"),
            badge(duty.state),
          );

          button.append(
            top,
            element("div", duty.title, "duty-title"),
          );

          button.addEventListener("click", () => selectDuty(duty.id));
          list.append(button);
        }

        if (duties.length > 0) {
          await selectDuty(duties[0].id);
        } else {
          clearDuty("No assessment results available.");
        }
      } catch (error) {
        clearDuty("Could not load the assessment.");
        $("duty-reason").append(
          element("span", error.message, "error"),
        );
      }
    }

    async function selectDuty(dutyId) {
      const requestId = ++dutySequence;

      document.querySelectorAll("[data-duty-id]").forEach((button) => {
        button.setAttribute(
          "aria-pressed",
          String(button.dataset.dutyId === dutyId),
        );
      });

      clearDuty(`Loading ${dutyId}…`);

      try {
        const data = await fetchJson(
          `/api/evaluate/${encodeURIComponent(dutyId)}`,
        );

        // A slower old request must not overwrite the latest selection.
        if (requestId !== dutySequence) return;

        if (data.duty_id !== dutyId) {
          throw new Error("The server returned a different duty.");
        }

        renderDuty(data);
      } catch (error) {
        if (requestId !== dutySequence) return;

        clearDuty(`Could not load ${dutyId}.`);
        $("duty-reason").append(
          element("span", error.message, "error"),
        );
      }
    }

    function sourceButton(citation) {
      const button = element("button", "", "source");
      button.type = "button";

      button.append(
        element(
          "div",
          `Open source ↗ ${citation.source_id}`,
          "blue mono small",
        ),
        element(
          "p",
          citation.document_title,
          "small",
        ),
        element("div", citation.location, "muted small"),
        element(
          "p",
          `Version: ${citation.version || "unspecified"} · `
            + `Date: ${citation.date || "unspecified"} · `
            + `Status: ${citation.status || "unspecified"}`,
          "muted small",
        ),
        element("pre", citation.exact_passage, "quote"),
        element("p", citation.demonstrates, "small"),
      );

      button.addEventListener("click", () => {
        openDocument(citation.file_path, citation.exact_passage);
      });

      return button;
    }

    function renderDuty(data) {
      $("duty-title").textContent =
        `${data.duty_id} · ${data.duty_title}`;
      $("statutory-ref").textContent = data.statutory_ref;
      $("state-badge").replaceChildren(badge(data.state));
      $("duty-reason").textContent = data.reason;

      const container = $("components");
      container.replaceChildren();

      for (const component of data.components || []) {
        const card = element("article", "", "component");
        const top = element("div", "", "component-top");

        top.append(
          element("h4", component.name),
          badge(component.status),
        );

        card.append(
          top,
          element("p", component.rationale, "small"),
        );

        for (const citation of component.citations || []) {
          card.append(sourceButton(citation));
        }

        if (!(component.citations || []).length) {
          card.append(
            element(
              "p",
              "No source citation attached to this component.",
              "muted small",
            ),
          );
        }

        for (const limitation of component.limitations || []) {
          card.append(
            element(
              "p",
              `Limitation: ${limitation}`,
              "limitation",
            ),
          );
        }

        container.append(card);
      }

      const followup = $("followup");
      followup.replaceChildren();
      followup.classList.toggle("hidden", !data.actionable_request);

      if (data.actionable_request) {
        followup.append(
          element("h3", "Focused evidence request"),
          element("p", data.actionable_request.missing_fact),
          element("p", data.actionable_request.focused_question, "warning"),
          element(
            "p",
            `Listed sources: ${
              (data.actionable_request.sources_reviewed || []).join(", ")
            }`,
            "muted small",
          ),
        );
      }

      const exclusions = $("exclusions");
      exclusions.replaceChildren();

      for (const item of data.exclusion_log || []) {
        const card = element("div", "", "exclusion");
        const button = element(
          "button",
          `Open source ↗ ${item.source_id}`,
          "link mono small",
        );
        button.type = "button";
        button.addEventListener("click", () => {
          openDocument(item.file_path);
        });

        card.append(
          button,
          element("p", item.disposition, "muted small"),
          element("p", item.reason, "small"),
        );

        exclusions.append(card);
      }

      if (!exclusions.childElementCount) {
        exclusions.append(
          element(
            "p",
            "No version or scope exclusions recorded for this duty.",
            "muted",
          ),
        );
      }
    }

    async function openDocument(filePath, exactQuote = "") {
      const requestId = ++documentSequence;
      const dialog = $("document-dialog");
      const content = $("document-content");
      const notice = $("document-notice");

      $("document-title").textContent = filePath.split("/").pop();
      $("document-path").textContent = filePath;
      notice.textContent = "";
      content.textContent = "Loading source document…";

      if (!dialog.open) dialog.showModal();

      try {
        const data = await fetchJson(
          `/api/document?file_path=${encodeURIComponent(filePath)}`,
        );

        if (requestId !== documentSequence) return;

        const text = data.content;
        const quote = exactQuote.trim();
        const position = quote ? text.indexOf(quote) : -1;

        content.replaceChildren();
        content.scrollTop = 0;

        if (!quote || position < 0) {
          content.textContent = text;
          notice.textContent = quote
            ? "Warning: the exact quotation was not found in this file. "
              + "Verify the citation."
            : "Full source document.";
          notice.className = quote ? "warning" : "muted";
          return;
        }

        const mark = element("mark", quote);

        content.append(
          document.createTextNode(text.slice(0, position)),
          mark,
          document.createTextNode(
            text.slice(position + quote.length),
          ),
        );

        const sourceLine = text.slice(0, position).split("\n").length;
        notice.textContent =
          `Exact cited passage highlighted, starting at line ${sourceLine}.`;
        notice.className = "muted";

        requestAnimationFrame(() => {
          if (requestId === documentSequence && dialog.open) {
            mark.scrollIntoView({ block: "center" });
          }
        });
      } catch (error) {
        if (requestId !== documentSequence) return;

        content.textContent = `Could not open document: ${error.message}`;
        notice.textContent = "Document loading failed.";
        notice.className = "error";
      }
    }

    $("close-document").addEventListener("click", () => {
      $("document-dialog").close();
    });

    $("document-dialog").addEventListener("close", () => {
      documentSequence += 1;
    });

    initialize();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index_ui():
    """Serve the self-contained review interface."""
    return HTMLResponse(
        content=PAGE,
        headers={"Cache-Control": "no-store"},
    )
