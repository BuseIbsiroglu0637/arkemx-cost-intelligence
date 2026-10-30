# A3.15 — Source identity, usage and engineering approval

A3 now reports three distinct facts: `source_verification_status`,
`source_rights_status`, and `engineering_status`. Verifying a real PDF does not
mark its usage rights as checked. Existing catalog/operator checks stay intact.

The fixed ARKEMX-owned fixture uses code `DEMO-ARKEMX-SIVA-01`, with 12 mm / 4 mm
plaster and 240 / 320 kg cement dosage. It is authored test text, has no price,
and is not the official `15.275.1111` position. Its source fingerprint includes
its namespace, version, description, unit and explicit absence of price.

## Local setup on Windows

Requires the existing database through migration `0012_a3_review_assessments`.
No new migration is added. Stop the API before running the local setup helper.
From `services/cost-api`:

```powershell
& .\.venv\Scripts\python.exe .\scripts\setup_a315_owned_pilot.py --email YOUR_EXISTING_ADMIN_EMAIL
```

This is a protected local operator helper, not an HTTP endpoint. It resolves an
existing admin account and creates an isolated `A315-ARKEMX-SENTETIK-SIVA`
project, an actual one-row XLSX in existing upload storage, an owned synthetic
catalog version, an M4 evidence run through the existing builder, and a saved A3
review through the existing review service. It reuses these records on a rerun
and refuses to silently overwrite a changed fixture. It reuses an existing
builtin demo source when present, preserving the original M2 demo version.
It does not grant permission to real catalogs, create catalog approval events,
approve engineering decisions or write cost drafts.

After restarting the API, open `/batch-technical-review`, choose the new project
and generated Excel import, load saved reviews and open the initial review.
The source panel must say owned synthetic test data, with no official price.
Inspect the M4 link to see identity linkage independently from approval gates.

M4's existing multilayer safety gate is still enforced. A successful identity
link is not engineering approval and does not make this pilot cost-ready.
The helper does not add this fixture to the general M4.3 catalog selector;
it uses the declared synthetic source and existing M4 builder for this isolated
pilot only. The real PDF catalog remains pending its separate usage review.

Existing saved reviews remain immutable. Changes to comparison/source rules
are reported as engine changes when reopening older reviews; generate a new
review when current results are needed.
