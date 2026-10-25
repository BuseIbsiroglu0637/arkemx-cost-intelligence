# Technical design (M1)

```text
Browser (Next.js 16 / React 19)
  -> FastAPI HTTP endpoints (bearer JWT, pilot-only)
     -> organization + project access check
     -> XLSX reader (openpyxl read-only, data_only=False)
     -> validation/normalization (Decimal, unit aliases)
     -> SQLAlchemy transaction (imports + work_items)
     -> private local file storage (organization/project/import UUID path)
  -> SQLAlchemy/PostgreSQL 16 via Alembic
```

- `POST /api/auth/register|login`, `GET /api/me`.
- `GET|POST /api/projects`; `GET /api/projects/{id}/items|imports`.
- `POST /api/imports/inspect|preview`: upload does not persist and return headers/first 30 sample rows.
- `POST /api/projects/{id}/imports`: validates first, persists atomically at DB level; orphan file cleanup on DB exception.
- `GET|POST /api/catalog/sources`, `POST /api/catalog/sources/{id}/verify` (local admin attestation only).
- All project operations verify `Project.organization_id == token.organization_id` through server-side DB lookup. Never trust a tenant id from request bodies.

## Design limitations
- Cross-system object storage not yet implemented; local file persistence is for single-machine pilot only.
- JWT in sessionStorage is not an acceptable final browser-auth system; switch to hardened HttpOnly same-site cookies + CSRF and refresh token policy.
- `register` is publicly callable on local API; disable public registration or implement invitations and rate limiting before public hosting.
- CORS localhost only; never use `*` with credentials.
- XLSX parser rejects formulas for quantity and flags any formula in selected columns. Do not export raw untrusted strings as Excel formulas without spreadsheet injection protection.
- At-rest encryption not provided by this app. Use encrypted disk in development and encrypted object storage in production.
- The source 'verify' endpoint stores customer-admin supplied evidence; an independent license review is still required prior to accessing restricted data.
- Before large files or untrusted internet upload: ZIP bomb controls, streaming pipeline, malware scanning, quotas, cancellation and worker queue.
