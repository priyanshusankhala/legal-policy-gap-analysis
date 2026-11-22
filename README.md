> **Live Interactive Compliance Workbench:** **[https://priyanshusankhala.github.io/legal-policy-gap-analysis//](https://priyanshusankhala.github.io/legal-policy-gap-analysis/)**  
> *Click any duty (`04-P02-1`, `04-P02-2`, `04-P02-3`, `04-P02-6`) to inspect the verdict, open highlighted company evidence files directly in the browser, and review version/register audit traces — no local setup required.*  
> **Solution Walkthrough PDF:** Available in this repository (`COBACK_Solution_Priyanshu_Sankhala.pdf`)


# Coback Task Challenge: NIS2 Compliance Analysis Service

**Author:** Priyanshu Sankhala  
**Challenge Date:** November 2026  
**Target Entity:** Marenthal Chemie AG (DE) (`1764010d-db68-42e2-8aa2-db89242548ad`)  

---

## 1. Overview & Business Context

This service implements **Step 3 (Compliance Analysis)** of the Coback end-to-end regulatory intelligence workflow.
It performs an automated, evidence-backed comparison between four primary NIS2 / German BSIG (§ 30 BSIG) duties and the operational documentation of **Marenthal Chemie AG (DE)**.

### Strict Epistemic Evaluation Guardrails:
1. **Three Clear States:**
   * `met`: Fulfillment is positively established by verified operational proof.
   * `open`: Recorded shortfall/gap supported by reviewed evidence.
   * `evidence_missing`: The data is silent, ambiguous in scope, or missing underlying operational logs. **Silence is never treated as a confirmed shortfall.**
2. **Strict Traceability:** Every decision cites the source ID, exact verbatim passage, document status, and version/date.
3. **Actionable Follow-up:** Every unresolved duty generates a focused, targeted inquiry for operational clarification.

---
# COBACK AI Compliance Gap Analysis — Marenthal Chemie AG (DE)

An auditable, neuro-symbolic compliance evaluation service and interactive local Web UI built for **Step 3 (Compliance Analysis)** of the COBACK workflow. It compares the four selected German BSIG / NIS2 duties (`04-P02-1`, `04-P02-2`, `04-P02-3`, `04-P02-6`) against the Marenthal Chemie AG (`CMS-DE-01`) company data dump as of `2026-11-18`.

---

## Quick Start: Open the Local Compliance Website

Pre-generated full-corpus assessment outputs (`outputs/compliance_report.json` and `outputs/compliance_report.md`) are included in this repository so you can inspect the complete results in the Web UI immediately—even without a local LLM running.

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/priyanshusankhala/legal-policy-gap-analysis/
cd legal-policy-gap-analysis
python3 -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate
pip install -r requirements.txt

```

### 2. Launch the Interactive Web UI
```bash
python -m src.web_ui --data-dir data/COBACK_Marenthal_Inputs/company_data 
```

Open http://localhost:8765 in your browser (opens automatically on start).

What you can do in the UI:

1. Select any duty (04-P02-1, 04-P02-2, 04-P02-3, 04-P02-6) from the dropdown or top cards.

2. Inspect the verdict: View Duty ID, statutory reference, state (met, open, evidence_missing), synthesized reason, clause-level rationales, available evidence, and missing facts.

3. Open cited source documents: Click any document chip (e.g., DMS-00001406, REG_Legal_Obligations_CMS-DE-01.txt) to open the file in an inline line-numbered viewer scrolled and highlighted to the exact cited lines (or open natively on your OS).

4. Review separate action lists: View the separated Supported Gaps (confirmed shortfalls) and Evidence Questions (focused follow-up requests).

5. Inspect audit provenance: View every file searched for the selected duty (ranked by relevance score) and an explicit log of how document versions (v1.1 superseded vs. v2.0 active) and register statuses (offen, erfüllt) shaped the verdict.


### Re-Running the Analysis (CLI & Live UI Re-Run)

#### Option A: Deterministic Baseline (No Ollama Required — Runs in ~10s)
``` Bash 
python -m src.cli --data-dir data/COBACK_Marenthal_Inputs/company_data --no-llm
```
You can also click "Run Fast Baseline" directly inside the Web UI header.

#### Option B: Full Semantic Audit with Local Ollama (llama3.2)
Install and start Ollama and pull llama3.2:

``` Bash
ollama pull llama3.2
```
Run the CLI assessment (or click "Re-run with Ollama LLM" inside the Web UI):

```Bash
# Starter corpus (15 starter files + entity registers)
python -m src.cli --data-dir data/COBACK_Marenthal_Inputs/company_data

# Full corpus (all 1,426 documents indexed for Marenthal Chemie AG)
python -m src.cli --data-dir data/COBACK_Marenthal_Inputs/company_data --full-corpus
Running Automated Verification Tests
```
``` Bash
pytest -v
Runs 17 unit, integration, and behavioral edge-case tests verifying:
```

1. Overdue vs. future-dated offen register obligations (due_date <= as_of_date vs. due_date > as_of_date),

2. Negated effectiveness statements (nicht wirksam, not effective) never marked supported,

3. Execution vs. effectiveness distinction (completed drills with audit findings),

4. Blank twin_questions.csv cells not blocking valid supporting documents,

5. Version supersession (v1.1 excluded when v2.0 is active) and future effective-date filtering,

6. Verbatim substring citation verification, out-of-range citation rejection, and Web UI path-traversal protection.

### Project Structure
```text
├── data/                # Input company data (COBACK_Marenthal_Inputs/company_data)
├── outputs/             # Pre-generated JSON & Markdown assessment reports
├── src/
│   ├── analyzer.py      # End-to-end orchestration & report assembly
│   ├── corpus.py        # Entity scoping (CMS-DE-01), version & date resolution, chunking
│   ├── duty_parser.py   # Lossless duty & legal-interpretation parser + clause decomposition
│   ├── evaluator.py     # Grounded LLM evaluator + deterministic legal/temporal validator
│   ├── loader.py        # Safe path resolution & CSV/JSON/Markdown-table ingestion
│   ├── models.py        # Pydantic schemas for results, citations, gaps & evidence requests
│   ├── retriever.py     # Hybrid multilingual dense + lexical TF-IDF retriever
│   ├── web_ui.py        # Local HTTP server & interactive single-page compliance workbench
│   └── cli.py           # CLI entry point (--ui, --full-corpus, --no-llm, --check-llm)
├── static/              # Frontend assets for the local Web UI
├── tests/               # 17 automated pytest verification suites
├── p1.py                # Pipeline entry / helper script
├── pytest.ini           # Pytest configuration
├── requirements.txt     # Python dependencies
└── run_ui.py            # Convenience launcher for the local Web UI
```


### AI Tools Disclosure & Output Verification
AI coding assistance (Gemini) was used for code development and to cross-check German/English BSIG § 30 Abs. 2 terminology.