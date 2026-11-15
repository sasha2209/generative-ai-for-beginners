# Family Health Graph

A platform that **ingests** a person's medical records and their family's health history,
**stores** them securely, and generates **explainable, guideline-based insights** about what
is worth discussing with a clinician, such as earlier cancer screening, genetic counseling or
cardiovascular risk checks.

> Family history is one of the strongest, cheapest predictors of disease risk, but it is
> usually incomplete, scattered across relatives' memories, and missing from the EHR. This
> project turns it into structured data that can drive action.

For how this grows through partnerships with existing companies, see
**[docs/PARTNERSHIP_STRATEGY.md](docs/PARTNERSHIP_STRATEGY.md)**.

---

## Quick start

```bash
cd family-health-graph
pip install -r requirements.txt
python -m fhg            # http://127.0.0.1:8000  (dashboard)  ·  /docs (OpenAPI)
python -m pytest -q      # 59 tests
```

In the dashboard, click **Import sample FHIR record**, then **Use sample text** → **Add to my
record**. The text describes the same family, so it is merged and de-duplicated rather than
added twice.

## What it does

```
          INGEST                         STORE                         INSIGHTS
 ┌──────────────────────┐     ┌──────────────────────────┐     ┌──────────────────────────┐
 │ FHIR R4 bundle       │     │ Merge + de-duplicate     │     │ Rule engine (pure funcs) │
 │  (EHR, payer, Apple  │ ──▶ │ into one longitudinal    │ ──▶ │  each insight carries:   │
 │   Health, aggregator)│     │ HealthProfile            │     │  · evidence (the facts)  │
 │ Free text ("my mom   │     │                          │     │  · recommendation        │
 │  had breast cancer   │     │ Encrypted at rest        │     │  · guideline citations   │
 │  at 46")             │     │ Provenance per import    │     │                          │
 │ CSV / spreadsheet    │     │ Consent + audit log      │     │ Optional AI rewrite into │
 │ Manual entry         │     │                          │     │ plain language (Claude)  │
 └──────────────────────┘     └──────────────────────────┘     └──────────────────────────┘
                                          │
                                          ▼
                         SHARE (consent-gated, minimum necessary)
              FHIR export · partner payloads · de-identified research export
```

### Ingestion (`fhg/ingest/`)
| Source | Handles |
|---|---|
| **FHIR R4** (`fhir.py`) | `Patient`, `Condition`, `Observation` (incl. BP panels), `MedicationStatement/Request`, `FamilyMemberHistory`. Maps SNOMED CT, ICD-10-CM, LOINC and HL7 v3 RoleCodes. Full export too (round-trip tested). |
| **Free text** (`text.py`) | "Grandpa on my father's side died of colon cancer when he was 72", "my mother and sister both had breast and ovarian cancer", "in her late 50s" (stored as ~58, flagged as estimated), "my other sister…". Deterministic, with a **preview** mode so users confirm before saving. |
| **CSV** (`csv_import.py`) | `relationship,condition,age_at_diagnosis,sex,deceased,name`, with per-row warnings. |

Terminology normalization (`terminology.py`) maps everything onto canonical concepts
(e.g. `breast_cancer`, `coronary_artery_disease`). Adding a concept is a data change.

### Storage (`fhg/storage.py`, `fhg/security.py`)
- Health data and raw imported documents are **encrypted at rest** (Fernet, AES + HMAC). The key comes from `FHG_ENCRYPTION_KEY`; use a KMS in production.
- API tokens are stored as SHA-256 hashes only.
- **Provenance**: every import is recorded (source type, merge stats, encrypted original).
- **Consent** scopes (`share:<partner>`, `ai_summary`, `research_deidentified`) are granted and revoked by the user.
- **Audit log** of every read, import, share and export. **Right to delete** via `DELETE /v1/me`.

### Insights (`fhg/insights/`)
| Rule | Triggers on (simplified from cited guidance) | Source |
|---|---|---|
| Hereditary breast/ovarian cancer | close relative with breast cancer ≤50, ovarian or pancreatic cancer at any age, male breast cancer, ≥2 same-side breast cancers, known BRCA variant | USPSTF 2019, NCCN |
| Colorectal cancer / Lynch | first-degree relative with CRC → screening start age (40, or 10 yrs before youngest dx); early-onset or ≥3 Lynch-spectrum cancers → genetic counseling | USMSTF 2017, USPSTF 2021 |
| Premature ASCVD | first-degree male relative <55 / female <65 with MI/CAD/stroke; escalates with LDL ≥160 | 2018 AHA/ACC |
| Familial hypercholesterolemia | LDL ≥190 mg/dL (mmol/L converted) or FH in family | 2018 AHA/ACC |
| Type 2 diabetes | first-degree relative + BMI ≥25 / age ≥35; HbA1c prediabetes or diabetes range | ADA Standards |
| Prostate cancer | father/brother/son <65 or ≥2 affected | ACS |
| Malignant hyperthermia | any blood relative → anesthesia safety alert | MHAUS |
| Blood pressure | stage 1 / stage 2 / severe ranges | 2017 ACC/AHA |
| Record gaps | unknown cancer types, missing ages that would change guidance, missing parents/grandparents | Surgeon General's Family Health Portrait |

Design principles:
- **Rules decide; the LLM only explains.** Clinical logic is deterministic, testable and cites its sources. The optional Claude summary (`narrative.py`) receives only the already-computed insights, never raw records or relatives' names. It runs only with the user's `ai_summary` consent and falls back to a template without an API key.
- **Every insight shows its evidence**, so a user or clinician can check the reasoning.
- **Conservative language**: "worth discussing", never a diagnosis.

## API

| Method & path | Purpose |
|---|---|
| `POST /v1/users` | Create an account → bearer token |
| `GET /v1/profile` · `PUT /v1/profile/demographics` | Read profile / set sex & birth date |
| `POST /v1/ingest/fhir` · `/text` · `/csv` (`?preview=true`) | Import data |
| `POST /v1/family` · `DELETE /v1/family/{id}` · `POST /v1/observations` | Manual entry |
| `GET /v1/insights` · `GET /v1/insights/summary` | Insight report / plain-language summary |
| `GET/POST /v1/consents` | View, grant, revoke consent |
| `GET /v1/partners` · `POST /v1/partners/{id}/share` | Consent-gated partner sharing |
| `GET /v1/export/fhir` | Data portability (FHIR bundle) |
| `GET /v1/ingests` · `GET /v1/audit` | Provenance and audit trail |
| `DELETE /v1/me` | Delete all data |
| `GET /admin/research/export` | De-identified, consented cohort (needs `X-Admin-Key`) |

## Configuration

| Env var | Default | |
|---|---|---|
| `FHG_DB_PATH` | `data/fhg.sqlite3` | SQLite path |
| `FHG_ENCRYPTION_KEY` | auto-generated dev key | Fernet key, **required in production** |
| `FHG_ADMIN_KEY` | unset (research export disabled) | |
| `FHG_PSEUDONYM_SECRET` | dev value | HMAC key for research IDs |
| `ANTHROPIC_API_KEY`, `FHG_LLM_MODEL` | unset, `claude-opus-5-5` | Optional AI summaries |

## Before this touches real patients

This is a working prototype, not a medical device. Before any real use:
1. **Clinical review** of every rule by clinicians and genetic counselors, a documented review cycle for guideline updates, and validation against real pedigrees (sensitivity/specificity versus established tools such as the Ontario FHAT or the Tyrer-Cuzick/CanRisk models).
2. **Regulatory review**: FDA software-as-a-medical-device / clinical decision support positioning, HIPAA (when acting as a business associate), the FTC Health Breach Notification Rule, and state health-privacy laws (e.g. Washington's My Health My Data Act).
3. **Production hardening**: real identity (OIDC, SMART on FHIR app launch), Postgres with row-level security, KMS-managed keys, rate limiting, a security review and pen test, backups, and accessibility review.

## Roadmap
- **Family invitations**: relatives add their own history (with consent) and enrich each other's insights. This is the core growth loop.
- SMART on FHIR "connect your patient portal" and payer Patient Access API connectors.
- Risk models (CanRisk/BOADICEA, PREVENT) alongside rule flags; pedigree visualisation.
- Clinician-facing view and FHIR `FamilyMemberHistory` write-back / CDS Hooks into the EHR.
- Genetic test report ingestion (structured variant results).
