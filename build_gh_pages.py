"""
Build a self-contained static GitHub Pages site in ./docs from outputs/compliance_report.json
and the company_data directory so Benjamin/reviewers can explore the full interactive UI online.
"""
import argparse
import json
from pathlib import Path
from typing import Any, Dict

from src.loader import DataLoader
from src.web_ui import HTML_PAGE


STATIC_ADAPTER_SCRIPT = r"""
<script>
  // Static GitHub Pages adapter: intercepts /api/report and /api/doc using bundled site_data.json
  let STATIC_BUNDLE = null;

  async function ensureStaticBundle() {
    if (!STATIC_BUNDLE) {
      const resp = await fetch("./site_data.json");
      if (!resp.ok) throw new Error("Failed to load bundled site_data.json");
      STATIC_BUNDLE = await resp.json();
    }
    return STATIC_BUNDLE;
  }

  // Replace server-only toolbar buttons with static snapshot badge + JSON download
  window.addEventListener("DOMContentLoaded", () => {
    const toolbar = document.querySelector(".toolbar");
    if (toolbar) {
      const selectEl = document.getElementById("dutySelect");
      toolbar.innerHTML = "";
      if (selectEl) toolbar.appendChild(selectEl);

      const badge = document.createElement("span");
      badge.textContent = "Static Audit Snapshot";
      badge.style.cssText =
        "background:#1e293b;color:#93c5fd;border:1px solid #334155;padding:7px 12px;border-radius:8px;font-size:0.82rem;font-weight:600;";
      toolbar.appendChild(badge);

      const dlBtn = document.createElement("a");
      dlBtn.href = "./site_data.json";
      dlBtn.download = "coback_compliance_report.json";
      dlBtn.textContent = "Download JSON";
      dlBtn.className = "btn-primary";
      dlBtn.style.textDecoration = "none";
      toolbar.appendChild(dlBtn);
    }

    const openNativeBtn = document.getElementById("openNativeBtn");
    if (openNativeBtn) {
      openNativeBtn.textContent = "Download .txt File";
    }
  });

  // Override loadReport to read directly from ./site_data.json
  loadReport = async function () {
    showBanner("Loading bundled compliance report...");
    try {
      const bundle = await ensureStaticBundle();
      reportData = bundle.report;
      hideBanner();
      if (!selectedDutyId && reportData.results && reportData.results.length > 0) {
        selectedDutyId = reportData.results[0].duty_id;
      }
      renderAll();
    } catch (err) {
      showBanner("Failed to load static report: " + err.message);
    }
  };

  function parseClientLineRange(loc) {
    if (!loc) return [null, null];
    const mRange = loc.match(/lines?\s+(\d+)\s*[-–]\s*(\d+)/i);
    if (mRange) return [parseInt(mRange[1], 10), parseInt(mRange[2], 10)];
    const mSingle = loc.match(/line\s+(\d+)/i);
    if (mSingle) {
      const n = parseInt(mSingle[1], 10);
      return [n, n];
    }
    return [null, null];
  }

  // Override openDoc to render from bundled documents in memory
  openDoc = async function (filePath, locationStr, titleLabel) {
    currentModalPath = filePath;
    document.getElementById("modalDocTitle").textContent = titleLabel || filePath;
    document.getElementById("modalDocSubtitle").textContent =
      `${filePath}${locationStr ? " — " + locationStr : ""}`;
    document.getElementById("modalDocBody").innerHTML =
      `<div style="padding:18px;">Loading document...</div>`;
    document.getElementById("docModal").classList.add("open");

    try {
      const bundle = await ensureStaticBundle();
      const docEntry = bundle.documents[filePath];
      if (!docEntry) {
        document.getElementById("modalDocBody").innerHTML =
          `<div style="padding:18px;color:#b91c1c;">Document not included in static bundle: ${esc(filePath)}</div>`;
        return;
      }

      const openNativeBtn = document.getElementById("openNativeBtn");
      if (openNativeBtn) {
        openNativeBtn.onclick = () => {
          const blob = new Blob([docEntry.lines.join("\n")], { type: "text/plain;charset=utf-8" });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = docEntry.title || "document.txt";
          a.click();
        };
      }

      const [startLine, endLine] = parseClientLineRange(locationStr);
      const linesHtml = docEntry.lines
        .map((lineText, idx) => {
          const lineNum = idx + 1;
          const isHl =
            startLine !== null && endLine !== null && lineNum >= startLine && lineNum <= endLine;
          return `
            <div class="code-line ${isHl ? "highlight" : ""}" id="doc-line-${lineNum}">
              <div class="line-no">${lineNum}</div>
              <div class="line-text">${esc(lineText) || "&nbsp;"}</div>
            </div>
          `;
        })
        .join("");

      document.getElementById("modalDocBody").innerHTML = linesHtml;
      if (startLine !== null) {
        const targetEl = document.getElementById(`doc-line-${Math.max(1, startLine - 2)}`);
        if (targetEl) targetEl.scrollIntoView({ block: "center" });
      }
    } catch (err) {
      document.getElementById("modalDocBody").innerHTML =
        `<div style="padding:18px;color:#b91c1c;">${esc(err.message)}</div>`;
    }
  };

  // Trigger initial load from static bundle
  loadReport();
</script>
"""


def build_static_site(
    report_path: Path,
    data_dir: Path,
    out_dir: Path,
) -> None:
    if not report_path.is_file():
        raise FileNotFoundError(
            f"Report not found at {report_path}. Run `python -m src.cli` first to generate outputs/compliance_report.json."
        )

    report: Dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    default_sub = data_dir / "data" / "COBACK_Marenthal_Inputs" / "company_data"
    resolved_data_dir = default_sub if default_sub.is_dir() else data_dir
    loader = DataLoader(resolved_data_dir)

    # Collect all cited files + all searched files so every link in the UI opens cleanly
    paths_to_bundle: set[str] = set()
    for res in report.get("results", []):
        for fp in res.get("sources_reviewed", []):
            paths_to_bundle.add(fp)
        for comp in res.get("components", []):
            for cit in comp.get("citations", []):
                if cit.get("file_path"):
                    paths_to_bundle.add(cit["file_path"])

    documents_map: Dict[str, Dict[str, Any]] = {}
    for rel_path in sorted(paths_to_bundle):
        try:
            cleaned = rel_path[len("company_data/"):] if rel_path.startswith("company_data/") else rel_path
            resolved_file = loader.resolve_path(cleaned)
            if resolved_file.is_file():
                lines = resolved_file.read_text(encoding="utf-8-sig").splitlines()
                documents_map[rel_path] = {
                    "title": resolved_file.name,
                    "total_lines": len(lines),
                    "lines": lines,
                }
        except Exception:
            continue

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    bundle_payload = {
        "report": report,
        "documents": documents_map,
    }
    bundle_file = out_dir / "site_data.json"
    bundle_file.write_text(json.dumps(bundle_payload, ensure_ascii=False), encoding="utf-8")

    # Inject static adapter right before </body> and remove the live initial loadReport(false, true) call
    static_html = HTML_PAGE.replace("loadReport(false, true);", "// static mode initialized below")
    static_html = static_html.replace("</body>", f"{STATIC_ADAPTER_SCRIPT}\n</body>")
    (out_dir / "index.html").write_text(static_html, encoding="utf-8")

    size_kb = bundle_file.stat().st_size / 1024.0
    print(f"[OK] Built GitHub Pages site in '{out_dir}/':")
    print(f"     - {out_dir / 'index.html'}")
    print(f"     - {bundle_file} ({len(documents_map)} bundled documents, {size_kb:.1f} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static GitHub Pages bundle in ./docs")
    parser.add_argument("--report", type=Path, default=Path("outputs/compliance_report.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/COBACK_Marenthal_Inputs/company_data"))
    parser.add_argument("--out-dir", type=Path, default=Path("docs"))
    args = parser.parse_args()
    build_static_site(args.report, args.data_dir, args.out_dir)


if __name__ == "__main__":
    main()