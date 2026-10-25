# M1 Test Plan and Exit Criteria

## Automated
- XLSX Turkish headers, manual columns, decimal locale handling, ambiguous numbers.
- Missing unit/description, formula cells, invalid container, large row limit.
- Auth required; register/login; project creation; cross-organization project/import/source access denied.
- Import preview is non-persistent; committed rows store source row and SHA-256.
- Alembic migration applies cleanly to a fresh DB.

## Manual (to be verified after pulling on developer PC)
- [ ] Fresh install: `alembic upgrade head` on PostgreSQL 16.
- [ ] `npm run build` and `npm run typecheck`.
- [ ] Register, create project, inspect/preview/import `example-data/demo-metraj.xlsx`.
- [ ] UI re-open / reload still shows project and rows.
- [ ] Untrusted user cannot access another organization's project.
- [ ] Uploaded raw file not publicly downloadable by URL.
- [ ] Browser test on Windows 11 + Chrome.

## Not a production sign-off
Must complete secure session architecture, organization onboarding, rate limits, encryption at rest, RLS defense in depth, automated backup/restore, virus/ZIP safety scanner, file retention/removal, legal catalog source approval, threat model and operational logging before paid public SaaS rollout.
