# A3.48.2 — PDF Poz Kütüphanesi

Bu sürümde Poz Eşleştirme sekmesi (/#technical) yalnızca kullanıcının 2026 YFK Fiyat Listesi PDF'sinden çıkarılan poz kayıtlarını gösterir. Excel veya proje seçimi gerektirmez; teknik onay, manuel poz eşleştirme ve maliyet işlemleri içermez.

## Veriler

Uygulama ilk açılışta giriş yapmış firmanın özel klasöründe kaynak olup olmadığını kontrol eder. Yoksa kullanıcı **2026 İnşaat Birim Fiyat Tarifleri Eki Fiyat Listesi PDF** belgesini seçer ve **PDF'den pozları al** düğmesine basar. Analizler Cilt 1 PDF'si bu modülün kaynağı değildir.

Kaynak PDF ve JSON indeksi UPLOAD_DIR/_a348_official_price_library/<organization-id>/<source-sha256>/ altında yerelde sürümlü saklanır; mevcut kaynak silinmez. Farklı firma katalogları birbirinden ayrılır. Orijinal telifli PDF veya poz kataloğu GitHub'a eklenmez.

Yalnız PDF'den gelen poz no, açıklama, birim, fiyat hücresi (varsa), ayrı montaj bedeli (varsa), sayfa ve kaynak SHA gösterilir. Eksik fiyat ve birimler uydurulmaz. Rayiç ve başlık kayıtları da katalogda olabilir; sayfanın fiyatı teknik onay veya M5 maliyeti anlamına gelmez.

## Yerel Windows test ortamı

Önce a346 veya a347 test veritabanından **yeni bir test kopyası** oluşturun. Orijinal P01 veritabanını kesinlikle hedef göstermeyin.

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a347
git fetch https://github.com/BuseIbsiroglu0637/arkemx-cost-intelligence.git refs/heads/feat/a3482-pdf-only-catalog-page
git worktree add -b feat/a3482-pdf-only-catalog-page ..\arkemx-a3482 FETCH_HEAD
```

Test veritabanı için A3.46 / A3.47 kopyalarından mevcut olanı seçip `sqlite3.Connection.backup` kullanın; hedef `C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\arkemx-a3482-test.db` olmalı. Kopya dosya varsa üstüne yazmayın.

API PowerShell:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3482\services\cost-api
$env:DATABASE_URL = 'sqlite:///C:/Users/busei/arkemx-dev/arkemx-a3482-runtime/arkemx-a3482-test.db'
$env:UPLOAD_DIR = 'C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\uploads'
$env:CORS_ORIGINS = 'http://127.0.0.1:3012,http://localhost:3012'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8012
```

Web PowerShell:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3482\apps\web
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8012'
npm install --no-audit --no-fund
npm run dev -- --port 3012
```

Sayfa: http://127.0.0.1:3012/#technical

## API

- `GET /api/a348/catalog/source`: kaynak ve denetim özeti
- `POST /api/a348/catalog/source`: lisanslı kullanıcı PDF yükleme ve yerel indeks oluşturma
- `GET /api/a348/catalog/positions?q=gazbeton&kind=insaat&page=1&page_size=40`: salt okunur, sayfalı poz listesi

## Kabul

PDF yükleyip 'gazbeton' ve '15.225.1004' aramalarını deneyin; fiyat 2026 resmî PDF hücresindeki değer olarak sunulmalı. Mekanik gruptaki montaj bedeli ayrılmalı. Poz sayıları ve kaynak SHA değişmeden sayfa yenilenince korunmalı. Bu modül henüz Excel metrajını pozlarla eşleştirmez.
