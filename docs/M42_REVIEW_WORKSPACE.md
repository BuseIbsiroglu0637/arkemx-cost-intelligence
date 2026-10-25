# M4.2 — Profesyonel Mühendis İnceleme Merkezi

**Durum: geliştirici pilotu; ticari ürün kabulü değil.**

## Kapsam ve performans gerçeği

- M4'te bir katalog **en fazla 500 poz**, bir eşleştirme çalışması **en fazla 100 metraj satırı** ile sınırlandırılmıştır. Her satırdan üç aday çıkabileceğinden inceleme kuyruğu mevcut pilotta en fazla yaklaşık 300 adaya ulaşır. **500 metraj satırı testi henüz yapılmadı.**
- `GET /api/projects/{id}/m42/queue`: Aday düzeyinde **sunucu sayfalama** (10/20/50), teknik karar durumu, mühendis son kararı ve poz kodu/açıklaması/metraj metni araması; istatistikler filtrelerden bağımsızdır.
- Kanıtlar topluca yüklenmez. Bir aday açılınca `GET /api/projects/{id}/m42/candidates/{candidate_id}` ile M4.1 kanıtı, SHA-256 kontrolü, alıntılar ve son 50 mühendis kararı getirilir.
- Geçmiş, **aynı metraj kalemi ve aynı katalog poz kimliği** ile ilgili güncel ve eski çalışma kararlarını gösterir. Eski kararı yeni çalışma için geçerli onay saymaz.
- Teknik olarak engelli/inceleme gerektiren, kaynak izni geri alınmış veya metrajı revize edilmiş adaylarda **onay kapalıdır**. Kullanıcı arayüzündeki düğmeye güvenilmez: yazma çağrıları mevcut M2 `decisions` API'sinin sunucu yetki, revizyon ve kanıt bütünlüğü kapısından geçer.
- **Ret** kararı bağımsız bir insan kararı olarak kayda alınır; önceki karar silinmez. Mühendis karar gerekçesi UI'de zorunludur (en az 10 karakter).
- Geniş tablolar yatay kaydırılır, filtreler ve aç/kapat düğmeleri klavyeyle erişilebilir. Eski M4/M2 test ekranları kapalı `details` altında saklanır.

## Ücretsiz Windows geliştirme akışı

Önce API ve web sunucularını `Ctrl+C` ile durdur:

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence"
git status --short
git fetch origin "refs/heads/feat/m4-2-engineer-review-ui:refs/remotes/origin/feat/m4-2-engineer-review-ui"
git switch --no-track -c feat/m4-2-engineer-review-ui refs/remotes/origin/feat/m4-2-engineer-review-ui

cd services\cost-api
Copy-Item .\arkemx-dev.db ".\arkemx-dev-before-m42-$(Get-Date -Format 'yyyyMMdd-HHmmss').db" -ErrorAction Stop
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Bu dal **yeni DB migration gerektirmez** (hedef `0006_m41_evidence (head)`). Tüm var olan veriler korunur.

İkinci PowerShell:

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence\apps\web"
npm run typecheck
npm run dev
```

## Kabul testleri

1. `DEMO-2026-TEST` onaylı katalogla M3 eşleştir. M4.2'de `Yeni kaynaklı karşılaştırma oluştur`.
2. Varsayılan kuyrukta aday sayıları, statüler, son kararlar, sayfa sayısı kontrolü.
3. `review`, `blocked`, `compatible`, `undecided`, `approved`, `rejected` filtreleri ve poz kodu araması; her filtre için sadece seçilen adaylar gelmeli.
4. **Kanıt ve karar** açıldığında doğrulanmış M4.1 ifade alıntıları ve hangi eski/güncel çalışmadan geldiğiyle karar geçmişi görünmeli.
5. M4.1 sentetik katalog başlıklarında kapsam belirsizliği çoğunlukla `review`; otomatik onay **0** olması beklenir. Eski M3 onayları yalnız tarihî kayıt olabilir.
6. Ayrı sentetik C25/30–C30/37 test çiftinde `blocked` adayı seçmek ve **onay** yazmak sunucudan 409 döndürmelidir; aynı katalogda `compatible` poz varsa kullanıcı gerekçesiyle onaylanabilir.
7. Katalog izin iptalinde ve revize edilen metrajda yeni onay **403/409** ile engellenir; liste gösterimi geçmiş için açık kalır.
8. 40 metraj satırı × 3 aday = 120 adaylı sentetik denemede API'nin ilk 50 + ikinci 50 + son 20 şeklinde sayfalaması ve kayıt tekrarının olmaması doğrulanmalı.
9. Yabancı firmanın projeyi veya kanıtını okuması 404 olmalı; kanıt SHA-256 bozulması 409 olmalı.

## Ticari açılış öncesi eksikler

Gerçek 500 metraj satırı hedefi için importer, eşleştirme motoru, arka plan işleme, indeksler, API limitleri ve yük testleri genişletilmelidir. Tanınan poz kataloglarının lisansları/izinleri, PostgreSQL, yedekleme, güvenlik testleri, mühendislik kalite ölçümü ve çok kullanıcılı izinler henüz ticari kabulden geçmemiştir.
