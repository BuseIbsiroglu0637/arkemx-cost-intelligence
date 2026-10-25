# ARKEMX Cost Intelligence — M1 Metraj Çekirdeği

**Status:** Developer pilot, not commercially deployable. **Scope:** `.xlsx` upload -> column mapping -> data normalization -> human review flags -> tenant-scoped database records. **Not implemented:** AI position matching, commercial catalog data, cost calculation, Excel cost reporting, payment or production hardened access.

## M2.1 — Akıllı Metraj Düzeltme (yeni)

- Ayrı geliştirme dalı: `feat/m2-1-metraj-revizyon`; bu dal M2'yi temel alır.
- Orijinal Excel ve ilk metraj satırları değişmeden kalır; her düzeltme gerekçeli ve sürümlüdür.
- Belirsiz miktarlar kendiliğinden düzeltilmez. Kullanıcı açık, geçerli miktar ve birimi girer.
- **Değişen kalemleri yeniden eşleştir** yalnızca güncellenmiş satırları yeniden hesaplar, değişmeyen adayları kopyalar.
- Önceki poz onayları eski run'da tutulur; **yeni run için yeniden mühendis onayı gerekir**.
- Eski API/Web sunucularını durdurduktan sonra dalı indir, `python -m alembic upgrade head` yap ve yeniden başlat.
- Test adımları: [M2.1 revizyon rehberi](docs/M21_REVISIONS.md).
- **Mevcut SQLite veritabanını silme.** Bu geliştirici pilotu ticari kullanım için hazır değildir.

## M2 poz eşleştirme pilotu — yeni özellik

M2, M1 metraj satırlarına **sadece sentetik DEMO- kodlarından** teknik filtreli aday önerileri, gerekçeler, zorunlu kontrol uyarıları ve insan onayı/red geçmişi ekler.

- Branch: `feat/m2-ai-poz-eslestirme` (M1 dalını temel alır).
- API klasöründe önce: `python -m alembic upgrade head`. **Eski yerel SQLite veritabanını silme!**
- Web ve API'yi yeniden başlat; projeni seç ve **Sentetik katalogla poz önerilerini oluştur** butonuna bas.
- Çevrimdışı lexical / metin benzerliği ücretsiz varsayılandır. İsteğe bağlı olarak çalışan yerel Ollama ile adayları yeniden sıralayabilirsin (`M2_OLLAMA_MODEL`).
- Kod, fiyat veya kamu katalog içeriği uydurulmaz ve indirilmez. M2 **ticari kullanıma hazır değildir**.
- Ayrıntılar ve test kapıları: [docs/M2_MATCHING.md](docs/M2_MATCHING.md).

## Quick start (free, local-first)

Requirements: Python 3.11+, Node.js 20.9+, npm. PostgreSQL 16 optional; SQLite works for local evaluation. All data stays in your own environment. Never commit `.env`, database files or uploaded customer files.

### API (terminal A)

```bash
cd services/cost-api
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[test]"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs ; health http://127.0.0.1:8000/api/health

### Web (terminal B)

```bash
cd apps/web
npm install
npm run dev
```

Open http://127.0.0.1:3000. Register a local test account, create a project, choose `example-data/demo-metraj.xlsx`, inspect columns, preview, then save. Expect five items with two review flags (`1.234` ambiguous and `kutu` unsupported). Regenerate demo with `python scripts/create_demo_workbook.py`.

### Optional local PostgreSQL

```bash
docker compose up -d postgres
# Configure DATABASE_URL=postgresql+psycopg://arkemx:change-me-local-only@127.0.0.1:5432/arkemx_cost
cd services/cost-api && python -m alembic upgrade head
```

Only use sample passwords on localhost; check Docker Desktop licensing for commercial organizations. Local PostgreSQL works without Docker.

### Tests

```bash
cd services/cost-api
python -m pytest -q
cd ../../apps/web
npm run typecheck
npm run build
```

GitHub Actions runs API and frontend CI on pushes and PRs subject to account-specific quota; Codespaces not needed.

## M1 acceptance

| ID | Check | Expected |
|---|---|---|
| M1-01 | Register/login | Password hashed; JWT; no anonymous project access |
| M1-02 | Create project | Scoped to organization |
| M1-03 | Read `.xlsx` | Turkish header detection; manual mapping available |
| M1-04 | Parse `1.245,50` | `1245.50`, source row preserved |
| M1-05 | Parse `1.234` | Ambiguity flagged; no automatic guess |
| M1-06 | Formula quantity | Never executed; review flag |
| M1-07 | Save import | SHA-256, filename, tenant-scoped private path, rows |
| M1-08 | Tenant isolation | Other organization's project inaccessible |
| M1-09 | Catalog source registration | Defaults to `pending`; no official data copied |
| M1-10 | Migration | Fresh SQLite and PostgreSQL (both must be checked before release) |

## Security and data rights

**Pilot-only:** `sessionStorage` bearer token, public registration, local file storage and development JWT secret are not suitable for production. Before accepting real customer data, implement secure sessions, invitations and rate limiting, CSRF protections, malware/ZIP checks, audit logs, encrypted storage, backups and restores, RLS and file retention controls.

`license_status=verified` means **an organization administrator recorded an attestation and evidence text**, not independent commercial rights verification. Do not import, copy or redistribute restricted official poz data without permission. Only synthetic demo files are included.

For details see `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/DATA_RIGHTS.md`, and `docs/ACCEPTANCE.md`.

## Repo workflow

The `main` branch contains the project introduction. Development lives in `feat/m1-metraj-core`. Review the pull request and CI before merging. Do not commit client data or credentials.

**Roadmap:** M2 licensed source import; M3 explainable poz candidates; M4 engineer review and deterministic cost reports.
