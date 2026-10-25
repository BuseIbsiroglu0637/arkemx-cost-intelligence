# M5.0 — Taslak maliyet hesabı

Geliştirici pilotu: M4.3'ten ayrı dalda, sadece teknik kanıtı sağlam ve mühendisçe onaylanmış pozları fiyatlandırır.

## M5.0 kapsamı
- Projeye bağlı mühendis onayı, güncel metraj ve katalog hakları doğrulanmadan yeni taslak oluşturulmaz.
- Fiyatlar sadece kullanıcı tarafından birim fiyat ve kaynak açıklamasıyla girilir. Katalogdaki kamu veya başka kaynak fiyatlarını otomatik kullanmaz.
- Her maliyet taslağı değiştirilemez kayıt: kaynak Excel SHA-256, katalog SHA-256, kanıt SHA-256, dondurulmuş miktar ve birim, poz ve fiyat açıklaması.
- Para hesabı decimal + kuruşa HALF_UP; toplam ayrı kalem tutarlarının toplamı.
- En fazla 500 poz, idempotency anahtarı, çoklu firma izolasyonu.
- UTF-8 BOM CSV; Excel formül enjeksiyonu için metin hücre kaçışı.
- M5 sekmesi: 20'li sayfalanan onaylı pozlar, manuel fiyat girişi, kayıtlı taslaklar, CSV çıktısı.

## Windows ücretsiz geliştirme
Mevcut yerel dosya değişikliklerini kontrol et. Git temiz değilse önce koru. API ve worker'ı durdur:

    cd "$HOME\arkemx-dev\arkemx-cost-intelligence"
    git status --short
    git fetch origin
    git switch --no-track -c feat/m5-cost-draft-foundation origin/feat/m5-cost-draft-foundation

Bu dal varsa onun yerine mevcut dalı seçip pull --ff-only yap.

SQLite veritabanını SİLME; M5 migration öncesi mutlaka yedek al:

    cd services\cost-api
    Copy-Item .\arkemx-dev.db ".\arkemx-dev-before-m5-$(Get-Date -Format 'yyyyMMdd-HHmmss').db" -ErrorAction Stop
    .\.venv\Scripts\python.exe -m alembic upgrade head
    .\.venv\Scripts\python.exe -m alembic current
    .\.venv\Scripts\python.exe -m pytest -q

Beklenen revision: 0008_m5_cost_drafts (head). Web: apps\web içinde npm run dev.

## Sınır
M5.0 nihai teklif, Excel XLSX/PDF, resmi fiyat lisans API'si, KDV/kâr, alternatif maliyet karşılaştırması veya metraj revizyon farklarını içermez; M5.1+ kapsamıdır. Ticari kabul veya saha fiyat doğruluğu iddiası yoktur.
