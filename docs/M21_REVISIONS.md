# M2.1 — Akıllı Metraj Düzeltme / Pilot Kabul

**Kapsam:** Orijinal Excel satırları değiştirilmeden gerekçeli, kimlikli metraj revizyonları. Yalnızca değişen kalemlerde poz adaylarını yeniden hesaplama. Eski eşleştirme ve onay kayıtları veritabanında korunur.

## Windows yerel kurulum

M1/M2 çalışırken API ve web terminallerinde `Ctrl+C` ile durdur.

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence"
git status --short
git fetch origin feat/m2-1-metraj-revizyon
git switch --track origin/feat/m2-1-metraj-revizyon

cd services\cost-api
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Yeni PowerShell:

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence\apps\web"
npm run typecheck
npm run dev
```

Git iş akışı henüz PR aşamasındadır, `main` ve M1/M2 PR'larını otomatik birleştirme. Yerel `arkemx-dev.db` veritabanını **silme**, böylece mevcut kayıtlar ve eski mühendis onayları korunur.

## Uçtan uca senaryo

1. Mevcut beş satırlı test projesini aç ve M2.1 bölümündeki sorunlu gazbeton satırına **Düzelt** de.
2. Miktarı kaynak mühendislik dokümanında doğruladıktan sonra açık biçimde `1234` olarak kaydet. Gerekçeyi yaz.
3. Boya satırının `kutu` birimi uygun değilse teknik projeden kontrol ederek doğru miktar/birimi belirt. Örnek testte `15 m²` kullanılır (gerçek imalat miktarı değildir).
4. Revizyon Geçmişi alanında orijinal `1.234` ve `kutu` girdilerinin korunduğunu doğrula.
5. **Değişen kalemleri yeniden eşleştir** butonuna bas. Hedef: 2 satır yeniden hesaplanır, 3 değişmeyenin adayları kopyalanır.
6. M2 kartlarında yeni değerleri ve kontrol durumlarını doğrula. Eski mühendis onayları otomatik aktarılmaz.
7. F5 yenile; revizyonların ve yeni eşleştirmenin korunduğunu doğrula.

## Veri modeli

- `work_item_revisions`: `work_item_id`, `revision`, `description`, `quantity`, `unit`, `corrected_by_id`, `reason`, `created_at`.
- `match_run_item_snapshots`: run ve iş kalemi için tam sabitlenmiş metraj girdisi.
- `match_runs.parent_run_id`, `match_runs.changed_item_count`: yeniden hesaplamanın izini tutar.

## API

- `GET /api/projects/{id}/m21/items` — Orijinal / güncel metrajı karşılaştır.
- `POST /api/projects/{id}/m21/items/{item_id}/revisions` — Yeni düzeltme ve gerekçe. Eski kaynak korunur.
- `GET /api/projects/{id}/m21/items/{item_id}/history` — Revizyon tarihçesi.
- `POST /api/projects/{id}/m21/rematch` — Etkilenen satırların yeniden eşleşmesi ve yeni run.
- `GET /api/projects/{id}/m21/run-history` — Eski ve yeni eşleştirme çalıştırmalarının listesi.
- `GET /api/projects/{id}/m21/run-history/{run_id}` — Eski giriş değerleri ve mühendis kararlarına ait salt okunur kanıt.

## Güvenlik ve sınırlamalar

- Düzeltme, kaynak dosya üzerinde değil append-only kayıt üzerinde yapılır.
- Sayısal belirsizlikler (`1.234`) tahmin edilmez; giriş `422` ile reddedilir. Formül veya bilinmeyen birim kayıt altına alınamaz.
- `expected_revision` iyimser kilit rolü görür; paralel düzenleme `409` sonucunu verir.
- Farklı kuruluşun proje/kalemlerine erişim sunucu tarafında reddedilir.
- Kullanıcı tekrar doğrulamadıkça eski onaylar yeni run için geçerli olmaz.
- **Bu sürüm de gerçek kamu pozlarını içermiyor; sentetik katalog dışında çalışmıyor.** Ticari kullanım/gerçek müşteri dosyaları için güvenlik, KVKK, katalog lisansı, PostgreSQL doğrulaması ve kabul testleri gereklidir.
- Eski M2 run'ları snapshot tablosu öncesi oluşturulmuş olabilir; bu kayıtlar tarihî M1 kaynak verisiyle temsil edilir.

## Test kapıları

- [ ] Alembic 0003 SQLite migration PASS
- [ ] PostgreSQL 0003 migration PASS
- [ ] M1+M2+M2.1 pytest PASS
- [ ] npm run typecheck, npm run build PASS
- [ ] Windows 5 satır masaüstü kabul testi PASS
- [ ] Değişen satırlar yeniden hesaplandı, değişmeyenler yeniden hesaplanmadı
- [ ] Eski onaylar önceki run'da korundu ve yenide otomatik taşınmadı
- [ ] Farklı firma erişim engeli, revizyon çakışması, hatalı miktar testi PASS
