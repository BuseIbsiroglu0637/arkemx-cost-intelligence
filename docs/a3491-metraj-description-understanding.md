# A3.49.1 — Excel Metraj Açıklamasını Anlama

Bu geliştirme mimarın **Excel metraj satırlarını** teknik özelliklerine ayırır. **Henüz poz adayları eşleştirilmez**, mühendis onayı ve maliyet hesabı yapılmaz. Kullanıcının 2026 kalıcı PDF poz kütüphanesi (20.315 kayıt ve Cilt 1 analizleri) aynen korunur.

## Çıkarılan bilgiler

- Kaynak: orijinal Excel açıklaması, çalışma sayfası, Excel satır numarası, dosyanın SHA-256 özeti, varsa kayıtlı son metraj revizyonu.
- İmalat ailesi: gazbeton, sıva, seramik, PVC, boya, beton, tuğla, çelik, ahşap, yalıtım (yalnız açıkça geçiyorsa).
- Malzeme: özellikle sıva için çimento/alçı/kireç ayrımı; bilinmeyen malzeme uydurulmaz.
- Kalınlık (mm), 60×60 gibi ebat, 3 mm derz genişliği, 2,50 N/mm² dayanım ve 400 kg/m³ yoğunluk ayrı alanlarda tutulur.
- İş kapsamı: malzeme/işçilik birlikte, yalnız malzeme, yalnız işçilik, söküm, uygulama kapsamı belirsiz.
- Bir satırda gazbeton+sıva ya da kaba+ince sıva gibi farklı imalatlar varsa `multiple_works_for_review`; aynı metraj miktarı iki satır için otomatik birleşme/onay sebebi olmaz.
- Çıkarılan katmanların kanıtı orijinal Excel açıklamasında **aynen bulunan alıntı ve karakter konumudur**.

## Ekran

ARKEMX → **Metraj** → **Kaydedilmiş metraj** bölümünün altında açılır **Metraj açıklamalarını yorumla**. Mevcut projeye kaydedilmiş Excel'i seç ve **Metrajı yorumla** tuşuna bas. 20'şer satırlık teknik yorum görünümlerini sayfalayabilirsin. Önizleme salt okunurdur ve hiçbir poz numarasını otomatik atamaz.

## API

`GET /api/projects/{project_id}/a349/imports/{import_id}/understanding?offset=0&limit=20`

- Oturum ve aynı firma/proje yetkisi zorunlu.
- Sayfa başına 1–100 satır; Excel kaynak kimliği/aktif revizyon; `catalog_matching_performed=false`, `approval_allowed=false`, `cost_allowed=false`.
- PostgreSQL/SQLite veya 2026 kalıcı katalog üzerinde yazma yok.

## Sabit portlar

Web: `http://127.0.0.1:3000`, API: `http://127.0.0.1:8000`. Kodu yeni çalışma dalından al, **mevcut test DB**, **UPLOAD_DIR** ve **%LOCALAPPDATA%/ARKEMX/catalogs** verilerini koru. Kaynak PDF'leri yeniden yükleme.

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483
git fetch https://github.com/BuseIbsiroglu0637/arkemx-cost-intelligence.git refs/heads/feat/a3491-metraj-understanding
git switch -c feat/a3491-metraj-understanding FETCH_HEAD
```

API:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\services\cost-api
$env:DATABASE_URL = 'sqlite:///C:/Users/busei/arkemx-dev/arkemx-a3482-runtime/arkemx-a3482-test.db'
$env:UPLOAD_DIR = 'C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\uploads'
$env:CORS_ORIGINS = 'http://127.0.0.1:3000,http://localhost:3000'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Web: yeni PowerShell:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\apps\web
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8000'
npm run dev -- --port 3000
```

Önce 10 kalemlik örnek proje metrajını seç; gazbeton, sıva, seramik, PVC işçilik/söküm gibi farklı tariflere göre çıkarılan alanları ve uyarıları kontrol et. Sonra mevcut 408 kalemlik proje Excel import kaydı ile 20 satırlık sayfaları tarayabiliriz. Bu, poz eşleştirmenin başarı testi değildir: gerçek poz adaylarını arama A3.49.2'de geliştirilecektir.
