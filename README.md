# Coback Candidate Challenge: NIS2 Compliance Analysis Service

**Author:** Priyanshu Sankhala  
**Role:** AI / Software Engineer Candidate  
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

## 2. Findings Summary

| Duty ID | Statute | Duty Description | Resulting State | Core Justification |
| :--- | :--- | :--- | :---: | :--- |
| **`04-P02-1`** | § 30 Abs. 2 Nr. 1 BSIG | Risikoanalyse und IT-Sicherheitskonzept | **`open`** | IT policy exists (`DMS-00000420`, KR-009 v2.0), but obligation register `REG_Legal_Obligations_CMS-DE-01.txt` explicitly documents the annual IT risk analysis as **`offen`** (overdue since 2026-01-01). |
| **`04-P02-2`** | § 30 Abs. 2 Nr. 2 BSIG | Vorfallbewältigung | **`evidence_missing`** | Policy `DMS-00000671` (KR-017 v2.0) is strictly restricted to **EHS**; incident register `REG_Incidents_CMS-DE-01.txt` contains zero IT incidents. Silence leaves evidence missing. |
| **`04-P02-3`** | § 30 Abs. 2 Nr. 3 BSIG | Betriebsaufrechterhaltung, Backups, Wiederherstellung | **`evidence_missing`** | Document `DMS-00001406` asserts an IT recovery exercise, but underlying operational test protocols with measured restore times (RTO/RPO) are absent. Internal controls register also notes DR exercise as only "teilweise wirksam". |
| **`04-P02-6`** | § 30 Abs. 2 Nr. 6 BSIG | Wirksamkeitsbewertung | **`evidence_missing`** | Individual operational controls (patching, phishing) are tested, and ISO 27001 covers the Frankfurt DC. However, an overarching effectiveness assessment program across all entity OT/IT sites is missing. |

---

## 3. Setup & Execution

### Prerequisites
* Python 3.10+
* Virtual environment active

### Installation
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt