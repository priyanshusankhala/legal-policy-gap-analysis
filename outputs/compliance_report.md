# Coback Compliance Analysis Report
**Entity:** Marenthal Chemie AG (DE) (`1764010d-db68-42e2-8aa2-db89242548ad`)
**Snapshot Date:** 2026-11-18 | **Analysis Date:** 2026-11-20
**Scope:** 4 Primary NIS2 / BSIG Duties (§ 30 BSIG)

## 1. Compliance Assessment Summary

| Duty ID | Statutory Ref | Duty Title | State | Summary Reason |
| :--- | :--- | :--- | :---: | :--- |
| `04-P02-1` | § 30 Abs. 2 Nr. 1 BSIG | Risikoanalyse und IT-Sicherheitskonzept | **`OPEN`** | An approved IT security policy exists (KR-009 v2.0), but the legal obligations register explicitly confirms th... |
| `04-P02-2` | § 30 Abs. 2 Nr. 2 BSIG | Vorfallbewältigung | **`EVIDENCE_MISSING`** | Emergency policy KR-017 is strictly restricted to EHS matters, and the incident register contains zero IT secu... |
| `04-P02-3` | § 30 Abs. 2 Nr. 3 BSIG | Betriebsaufrechterhaltung, Backups, Wiederherstellung, Krisenmanagement | **`EVIDENCE_MISSING`** | While record DMS-00001406 asserts that an IT recovery exercise was conducted ('erfüllt') and quarterly backup ... |
| `04-P02-6` | § 30 Abs. 2 Nr. 6 BSIG | Wirksamkeitsbewertung | **`EVIDENCE_MISSING`** | Individual technical controls (patching, phishing, access checks) are periodically tested and tracked. However... |

---

## 2. Detailed Findings by Duty

### Duty `04-P02-1`: Risikoanalyse und IT-Sicherheitskonzept (§ 30 Abs. 2 Nr. 1 BSIG)
- **State:** `open`
- **Assessment Reasoning:** An approved IT security policy exists (KR-009 v2.0), but the legal obligations register explicitly confirms that the annual IT risk analysis is unfulfilled (status: 'offen') and overdue since 2026-01-01.
- **Supported Aspects:**
  - Formal IT security concept exists and was approved on 2024-07-08 (KR-009 v2.0).
- **Shortfalls / Missing Aspects:**
  - Annual IT security risk analysis covering ERP, SCADA/OT, and office IT is overdue and marked 'offen'.
  - IT risks in the risk register have exceeded their scheduled review windows.
- **Reviewed Evidence Citations:**
  - **Source ID:** `DMS-00000420` | **Title:** Informationssicherheitsrichtlinie (KR-009) (Version: 2.0, Date: 2024-07-09)
    - **Location:** `documents/DMS-00000420_KR-009_v2.0_de.txt, lines 15-34`
    - **Demonstrates:** An approved group-wide IT security policy framework exists.
    - **Exact Quote:**
      ```text
      Vertraulichkeit
Confidential
Zweck und Geltungsbereich
Diese Richtlinie legt für Marenthal Chemie AG verbindliche Regeln zum Thema „Informationssicherheit“
fest. Sie gilt für alle Beschäftigten, Führungskräfte und, soweit vertraglich vereinbart, für
Geschäftspartner. Verstöße können arbeits- und strafrechtliche Folgen haben.
Pflichten und Zuständigkeiten
Dieses Dokument wird im Dokumentenmanagement der Marenthal-Gruppe geführt und ist in der
jeweils gültigen Fassung verbindlich.
Richtlinie
nummer: KR-009
titel: Informationssicherheitsrichtlinie
thema: Informationssicherheit
geltung: Konzern
aktuelle_version: 2.0
status: gültig
naechste_ueberpruefung: 2027-06-23
master_sprache: de
vertraulichkeit: vertraulich
Richtlinienversion
      ```
  - **Source ID:** `REG_Legal_Obligations_CMS-DE-01` | **Title:** Register of legal and internal obligations (Version: 1.0, Date: 2026-11-09)
    - **Location:** `documents/REG_Legal_Obligations_CMS-DE-01.txt, line 82`
    - **Demonstrates:** Statutory obligation 'Informationssicherheitsrisikoanalyse jährlich durchführen' is officially recorded with status 'offen'. Next due was 2026-01-01, which is overdue relative to snapshot 2026-11-18.
    - **Exact Quote:**
      ```text
      | Informationssicherheitsrisikoanalyse jährlich durchführen | Risiken für ERP, Produktionssteuerung und Büro-IT bewerten; Maßnahmenplan fortschreiben. | Informationssicherheit | BSI-Gesetz; ISO/IEC 27001 | Gesetz | - | DE | anwendbar | - | wiederkehrend | 2026-01-01 | 12 | offen | 2025-01-06 |
      ```


### Duty `04-P02-2`: Vorfallbewältigung (§ 30 Abs. 2 Nr. 2 BSIG)
- **State:** `evidence_missing`
- **Assessment Reasoning:** Emergency policy KR-017 is strictly restricted to EHS matters, and the incident register contains zero IT security incidents or cyber drills. Under Coback rules, silence leaves evidence missing.
- **Supported Aspects:**
  - An Information Security Officer role is formally designated and active.
- **Shortfalls / Missing Aspects:**
  - No documented IT-specific incident response plan (IRP) found in reviewed files.
  - No practical test protocols or drill records for cyber incident response.
- **Reviewed Evidence Citations:**
  - **Source ID:** `DMS-00000671` | **Title:** Notfall- und Krisenmanagement (KR-017) (Version: 2.0, Date: 2025-03-25)
    - **Location:** `documents/DMS-00000671_KR-017_v2.0_de.txt, lines 13-20`
    - **Demonstrates:** Policy KR-017 specifically governs EHS (Environmental Health and Safety), not IT incidents.
    - **Exact Quote:**
      ```text
      Status
Approved
Vertraulichkeit
Internal
Zweck und Geltungsbereich
Diese Richtlinie legt für Marenthal Chemie AG verbindliche Regeln zum Thema „EHS“ fest. Sie gilt für
alle Beschäftigten, Führungskräfte und, soweit vertraglich vereinbart, für Geschäftspartner. Verstöße
können arbeits- und strafrechtliche Folgen haben.
      ```
  - **Source ID:** `REG_Compliance_Roles_CMS-DE-01` | **Title:** Register of compliance roles and responsibilities (Version: 1.0, Date: 2026-11-09)
    - **Location:** `documents/REG_Compliance_Roles_CMS-DE-01.txt, line 17`
    - **Demonstrates:** An Information Security Officer role is appointed with a designated deputy.
    - **Exact Quote:**
      ```text
      | Informationssicherheitsbeauftragter | Informationssicherheit | - | 2021-05-25 | - | yes |
      ```


### Duty `04-P02-3`: Betriebsaufrechterhaltung, Backups, Wiederherstellung, Krisenmanagement (§ 30 Abs. 2 Nr. 3 BSIG)
- **State:** `evidence_missing`
- **Assessment Reasoning:** While record DMS-00001406 asserts that an IT recovery exercise was conducted ('erfüllt') and quarterly backup restores run regularly, the actual operational test report with measured restore times and recovery targets (RTO/RPO) is absent from the data. Under 17-AUS-17, a register assertion without underlying operational metrics cannot establish full compliance.
- **Supported Aspects:**
  - Formal obligation and proof document exists (DMS-00001406).
  - Quarterly offline backup restore controls are active (4 effective runs out of 5).
- **Shortfalls / Missing Aspects:**
  - Underlying test log with measured recovery times (RTO) and restore targets is missing.
  - The 2025-10-13 DR exercise execution is rated only 'teilweise wirksam' in the internal controls register.
- **Reviewed Evidence Citations:**
  - **Source ID:** `DMS-00001406` | **Title:** Nachweis: Notfall- und Wiederanlaufübung der IT durchführen (Version: 1.0, Date: 2025-12-23)
    - **Location:** `documents/DMS-00001406_V000074_Nachweis.txt, lines 15-26`
    - **Demonstrates:** A compliance record asserts that an IT recovery drill was executed with status 'erfüllt'.
    - **Exact Quote:**
      ```text
      Internal
Angaben
Dieses Dokument wird im Dokumentenmanagement der Marenthal-Gruppe geführt und ist in der
jeweils gültigen Fassung verbindlich.
Verpflichtung
titel: Notfall- und Wiederanlaufübung der IT durchführen
beschreibung: Wiederherstellung kritischer Systeme (ERP, Prozessleitsystem) üben und Ergebnisse
dokumentieren.
quelle: Konzernrichtlinie Informationssicherheit
quelltyp: Konzernrichtlinie
land: DE
anwendbarkeit: anwendbar
      ```
  - **Source ID:** `REG_Internal_Controls_CMS-DE-01` | **Title:** Register of internal controls and their execution (Version: 1.0, Date: 2026-11-09)
    - **Location:** `documents/REG_Internal_Controls_CMS-DE-01.txt, line 35`
    - **Demonstrates:** Offline backup restores run quarterly, with 4 effective runs and 1 open.
    - **Exact Quote:**
      ```text
      | Offline-Datensicherung und Wiederherstellungstest | präventiv | quartalsweise | Verschlüsselungsangriff auf ERP und Produktionssteuerung | Informationssicherheitsrisikoanalyse jährlich durchführen | - | aktiv | 5 runs: wirksam 4, offen 1 | 2025-10-17 | 2026-01-21 |
      ```


### Duty `04-P02-6`: Wirksamkeitsbewertung (§ 30 Abs. 2 Nr. 6 BSIG)
- **State:** `evidence_missing`
- **Assessment Reasoning:** Individual technical controls (patching, phishing, access checks) are periodically tested and tracked. However, an overarching effectiveness assessment program covering all company operations and OT systems is absent. Per 17-AUS-17, discrete tests and a site-limited ISO certificate (Frankfurt DC only) do not establish full entity-wide effectiveness.
- **Supported Aspects:**
  - Specific technical controls undergo monthly/quarterly execution tracking (patching, phishing).
  - ISO 27001 certification covers Frankfurt data center systems.
- **Shortfalls / Missing Aspects:**
  - No comprehensive effectiveness testing plan (penetration testing, technical audits) for production plants (Marl, Bitterfeld).
  - No independent verification of effectiveness across the full scope of § 30 BSIG measures.
- **Reviewed Evidence Citations:**
  - **Source ID:** `REG_Internal_Controls_CMS-DE-01` | **Title:** Register of internal controls and their execution (Version: 1.0, Date: 2026-11-09)
    - **Location:** `documents/REG_Internal_Controls_CMS-DE-01.txt, line 38`
    - **Demonstrates:** Individual operational security controls undergo recurring effectiveness testing.
    - **Exact Quote:**
      ```text
      | Patch- und Schwachstellenmanagement für Server | IT-Kontrolle | monatlich | Verschlüsselungsangriff auf ERP und Produktionssteuerung | Informationssicherheitsrisikoanalyse jährlich durchführen | - | aktiv | 14 runs: wirksam 12, offen 2 | 2025-12-12 | 2026-01-15 |
      ```
  - **Source ID:** `company_profile.json` | **Title:** Company Profile - Certifications (Version: 2026-11-09, Date: 2026-11-09)
    - **Location:** `company_profile.json, path: certifications`
    - **Demonstrates:** An ISO 27001 certificate exists, but its scope is strictly limited to the Frankfurt Data Center and development systems.
    - **Exact Quote:**
      ```text
      Zertifikat Informationssicherheit ISO/IEC 27001:2022 · Geltungsbereich: Geltungsbereich: Rechenzentrum und Entwicklungssysteme Frankfurt. · Stelle: TÜV Rheinland · Nummer: IS-FRA-48211 [Q001 · belegt · hoch · Stichtag 2026-11-09]
      ```


---

## 3. Supported Gaps (Ready for Task Planning)

- **Duty `04-P02-1` (Risikoanalyse und IT-Sicherheitskonzept)**
  - **Finding:** An approved IT security policy exists (KR-009 v2.0), but the legal obligations register explicitly confirms that the annual IT risk analysis is unfulfilled (status: 'offen') and overdue since 2026-01-01.
  - **Evidence Basis:** Documented in Register of legal and internal obligations (REG_Legal_Obligations_CMS-DE-01)
  - **Exact Passage:** `"| Informationssicherheitsrisikoanalyse jährlich durchführen | Risiken für ERP, Produktionssteuerung und Büro-IT bewerten; Maßnahmenplan fortschreiben. | Informationssicherheit | BSI-Gesetz; ISO/IEC 27001 | Gesetz | - | DE | anwendbar | - | wiederkehrend | 2026-01-01 | 12 | offen | 2025-01-06 |"`

---

## 4. Focused Evidence Requests (Unresolved Duties)

### Actionable Follow-up for `04-P02-2` (Vorfallbewältigung)
- **Missing Fact:** Operational IT incident response runbooks and practical test logs are absent from the reviewed corpus.
- **Focused Question:** *"Does Marenthal Chemie AG maintain a dedicated IT Incident Response Plan (IRP) defining detection, escalation, containment, and recovery workflows, and have practical tabletop exercises or test drills been conducted and documented for the German entity?"*
- **Sources Reviewed:** documents/DMS-00000671_KR-017_v2.0_de.txt, documents/REG_Incidents_CMS-DE-01.txt, documents/REG_Compliance_Roles_CMS-DE-01.txt


### Actionable Follow-up for `04-P02-3` (Betriebsaufrechterhaltung, Backups, Wiederherstellung, Krisenmanagement)
- **Missing Fact:** Underlying operational restore logs with quantitative recovery metrics (RTO/RPO) are absent.
- **Focused Question:** *"Where is the underlying technical restore test protocol for the exercise referenced in DMS-00001406 (dated 2025-12-23), including actual measured Recovery Time Objectives (RTO), Recovery Point Objectives (RPO), and verification logs for ERP and process control systems (ICS/SCADA)?"*
- **Sources Reviewed:** documents/DMS-00001406_V000074_Nachweis.txt, documents/REG_Internal_Controls_CMS-DE-01.txt


### Actionable Follow-up for `04-P02-6` (Wirksamkeitsbewertung)
- **Missing Fact:** An overarching technical effectiveness evaluation program (e.g. penetration test reports, independent audits) covering all entity facilities is missing.
- **Focused Question:** *"Does Marenthal Chemie AG have an established cybersecurity effectiveness assessment program (such as periodic penetration testing, Red Teaming, or holistic ISMS audit reports) covering all German sites and production OT/ICS environments, including documented test results and remediation plans?"*
- **Sources Reviewed:** documents/REG_Internal_Controls_CMS-DE-01.txt, company_profile.json


---

## 5. Reviewed Sources & Version Effects

- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/company_profile.json`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/DMS-00000420_KR-009_v2.0_de.txt`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/DMS-00000671_KR-017_v2.0_de.txt`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/DMS-00001406_V000074_Nachweis.txt`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/REG_Compliance_Roles_CMS-DE-01.txt`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/REG_Incidents_CMS-DE-01.txt`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/REG_Internal_Controls_CMS-DE-01.txt`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/REG_Legal_Obligations_CMS-DE-01.txt`
- `/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs/company_data/documents/REG_Risk_Register_CMS-DE-01.txt`

**Version & Register Status Notes:**
- Policy `DMS-00000420` (KR-009) is active at version 2.0; the older v1.1 was superseded.
- Policy `DMS-00000671` (KR-017) is active at version 2.0, but its scope is strictly EHS, leaving IT incident handling silent.
- Register `REG_Legal_Obligations_CMS-DE-01.txt` carries authoritative evidentiary weight for confirmed gaps where obligations are explicitly marked `offen`.