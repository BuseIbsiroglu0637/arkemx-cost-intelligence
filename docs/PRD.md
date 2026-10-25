# PRD v0.1 — M1 Çalışan Metraj Çekirdeği

**Product hypothesis:** A small design/engineering office can import an architect's XLSX quantity takeoff without rewriting its rows, see ambiguities, and prepare it for engineer-reviewed position matching.

## Personas
- Cost engineer: uploads quantity takeoff, maps arbitrary spreadsheet column names, corrects anomalies before matching.
- Office owner: creates and manages projects, wants repeatable traceable evidence, no cross-client leakage.

## Included M1
- Registration/login for local pilot, separated organizations, project creation/listing.
- `.xlsx` file up to 10 MB, at most 2,000 non-empty work rows, 120 columns; first sheet initially selected.
- Turkish header recognition and manual column mapping.
- Quantity parsing (decimal-point and decimal-comma), unit aliases (m, m², m³, kg, ton, adet), issues for ambiguous values and formulas.
- Preview first 30 rows; commit full dataset with source row, SHA-256 and review flags.
- Catalog source ownership, license-status and evidence metadata.

## Excluded
- AI matching, public catalog ingestion, OCR, IFC/BIM, price calculation, KDV rules, quote exports, live UYAP/ARKEMX CORE integrations, subscription billing.

## User story & acceptance
1. A new owner registers and creates a project (organization ownership enforced).
2. They upload a valid `.xlsx`, inspect proposed column mapping and choose columns.
3. Preview identifies invalid/ambiguous quantities, units and formula cells without inventing values.
4. After saving, the user sees rows in same source order with row numbers; import metadata includes source SHA-256.
5. Another organization's user cannot read or upload to that project.

## Data and trust
Do not claim government position matching, resell government schedules or say the AI has verified any public data in M1. Licensed source handling is a schema foundation only. For production readiness see `docs/DATA_RIGHTS.md` and `docs/ACCEPTANCE.md`.
