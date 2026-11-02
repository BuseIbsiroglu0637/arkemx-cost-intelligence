# A3.48.3 — İki PDF kaynaklı Poz Kütüphanesi

Bu modülde **2026 ÇŞİDB/YFK Fiyat Listesi** (poz, fiyat, birim) ve **2026 İnşaat Birim Fiyat Analizleri Cilt 1** (girdi, miktar, tarif, hesap) *ayrı* kaynak olarak yüklenir. Tek pozda birlikte görüntülenir ama **birbirinin fiyatını değiştirmez**.

## Bilgisayarında sabit portlarla çalıştırma

Mevcut ARKEMX test sunucularını CTRL+C ile durdur, sonra ayrı yeni A3.48.3 çalışma klasörü oluştur:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3482
git fetch https://github.com/BuseIbsiroglu0637/arkemx-cost-intelligence.git refs/heads/feat/a3483-price-and-analysis-pdf-link
git worktree add -b feat/a3483-price-and-analysis-pdf-link ..\arkemx-a3483 FETCH_HEAD
```

**Orijinal P01 veritabanını hedef göstermeyin.** A3.48.2 test DB'si ve `uploads` dizini zaten varsa aynen devam edin; böylece daha önce yüklenen poz listesi korunur. A3.48.2 DB henüz oluşmadıysa onu önce orijinal P01 yerine önceki test DB'sinden kopyalayın.

API (PowerShell 1):

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\services\cost-api
$env:DATABASE_URL = 'sqlite:///C:/Users/busei/arkemx-dev/arkemx-a3482-runtime/arkemx-a3482-test.db'
$env:UPLOAD_DIR = 'C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\uploads'
$env:CORS_ORIGINS = 'http://127.0.0.1:3000,http://localhost:3000'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Web (PowerShell 2):

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\apps\web
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8000'
npm install --no-audit --no-fund
npm run dev -- --port 3000
```

Tarayıcı: `http://127.0.0.1:3000/#technical`.

1. Önceden yüklenen **2026 Fiyat Listesi PDF** kaynaklı pozlar görünmeli; yeniden yüklemek zorunda değilsin.
2. **2. PDF — Detaylı Analizler Cilt 1** kartından `in-aat-analiz-1-20260115162935-20260120125449.pdf` dosyasını seç.
3. `15.225.1004` pozunu ara. Seçince analiz PDF sayfası, birim, girdiler ve fiyat kaynak karşılaştırması gösterilmeli.
4. `15.100.1001` pozunu da kontrol et: 2026 PDF analizinde sayfa 6'da bulunuyor.
5. Analiz yoksa başkasının tarifini kopyalama; `analiz yok veya ayrıştırılamadı` uyarısını doğrula.

## Belge doğrulama

Şu anda kaynak olarak sağlanan 2026 Analizler Cilt 1 PDF'si **704 PDF sayfasıdır** ve 1.01.2026 fiyat analizleri içerir. PDF metin/geometri incelemesinde yaklaşık 933 analiz başlığı, 930 standart okuma kuralına uygun blok tespit edilmiştir; uygulamadaki kesin sayılar yükleme sonrası `audit` alanından alınmalıdır. Analiz fiyatının hesabı mevcut ayrıştırma kuralıyla uyuşmazsa otomatik onaylanmaz. Bu Cilt 1 belge, 2026 bütün mekanik/elektrik analizlerini içermez.

## API

- `GET /api/a348/catalog/analysis/source`: kullanıcı/firma analizi var mı; kaynak SHA, sayfa ve denetim sayıları
- `POST /api/a348/catalog/analysis/source`: kullanıcı PDF'sini özel klasöre al, kaynak analizi ayrıştır; idempotent SHA sürümlü
- `GET /api/a348/catalog/positions/{15.xxx.xxxx}/analysis`: fiyat listesindeki pozu Cilt 1 analiz kaynağıyla yalnız poz no üzerinden ilişkilendir

Kaynak PDF ve tam indeks dosyaları yalnız yerel `UPLOAD_DIR/_a348_official_analysis_library/<org>/<sha>/` dizininde tutulur, GitHub'a gönderilmez. `cost_allowed=false`, `approval_allowed=false` ve M5/metraj DB tablolarında yazma yoktur.
