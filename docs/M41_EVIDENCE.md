# M4.1 — Teknik Kapsam ve Kaynaklı Kanıt (geliştirici pilot)

**Amaç:** Bir poz eşleştirme adayının neden uyumlu, çelişkili veya eksik bilgi içerdiğini **orijinal proje satırına ve katalog sürümüne bağlanan** izlenebilir bir kanıt kaydıyla göstermek.

## Kanıt sözleşmesi

`arkemx.technical_evidence.v1` şeması ile `technical_evidence` tablosu kullanılır.

- `candidate_id`: aday ve eşleştirme çalışmasına bağlanan değiştirilmeyen kimlik.
- `schema_version`, `status`, `evidence_sha256`, `payload_json`, `created_at`.
- `sources.metraj/catalog.normalized_text` ve `sha256`: kaynak açıklamanın dönüştürülmüş gösterimi ve orijinal metin özeti.
- `source_refs.metraj`: içe aktarım kimliği/SHA-256, Excel kaynak satırı, metraj kalemi, M2.1 revizyonu.
- `source_refs.catalog`: katalog sürüm kimliği/SHA-256, poz kimliği ve kodu.
- Her `checks[]`: `key`, metraj ve katalog `value`, `quote.excerpt`, `start`, `end`, `offset_basis=normalized_text`, karşılaştırma `status` ve uyarı `code`.
- JSON kanıtı deterministik, anahtarları sıralanmış UTF-8 olarak hashlenir; okuma ve onayda SHA-256 tekrar doğrulanır.
- İzin verilen kararlar: `blocked`, `review`, `compatible`. **Uyumlu = yalnızca bu kural setinde uyuşmazlık tespit edilmedi, mühendis onayı yerine geçmez.**

**Not:** İfade konumları normalleştirilmiş metindeki karakter konumlarıdır; Excel dosyasındaki bayt veya hücre koordinatları değildir. Orijinal Excel kaydı ve M2.1 revizyonu ayrı tutulur. SHA-256 imza değildir; kasıtlı veritabanı manipülasyonuna karşı kriptografik, harici kayıt mühürlemesi henüz yoktur.

## M4.1 özellikleri

- Beton dayanım sınıfı `C25/30`, `C30/37` vb.; tek kaynaktaki birden fazla farklı sınıf uzman incelemesine düşer.
- Belirtilmişse `TS EN 206` gibi standart atıfları ayrı değerlendirilir; metinlerde açık standart farkı varsa onay engeli.
- **Dahil/hariç kapsamı:** nakliye, işçilik, malzeme, montaj ve yardımcı imalat için yalnızca açık `dahildir/dahil/hariç` ifadeleri kullanılır.
- Sadece `nakliye` sözcüğünün geçmesi, o işin poz kapsamına kesinlikle dahil olduğunu göstermez.
- Bir tarafta bilgi yoksa `review`, iki tarafta çelişen beyan varsa `blocked`.
- Başlıkların ikisinde de hiçbir açık kapsam ifadesi yoksa `SCOPE_NOT_VERIFIABLE_FROM_TITLES` uyarısıyla `review`.
- Eski M4 kuralları da uygulanmaya devam eder: malzeme, kalınlık, ebat, yüzey, yöntem, birim.
- Teknik raporlar **append-only**, önceki M1–M4 eşleştirme kayıtları ve mühendis onayları değiştirilmez.

## Windows kurulumu (ücretsiz, mevcut proje korunur)

M4 API ve web sunucularını `Ctrl+C` ile durdur.

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence"
git status --short
git fetch origin "refs/heads/feat/m4-1-evidence-model:refs/remotes/origin/feat/m4-1-evidence-model"
git switch --no-track -c feat/m4-1-evidence-model refs/remotes/origin/feat/m4-1-evidence-model

cd services\cost-api
Copy-Item .\arkemx-dev.db ".\arkemx-dev-before-m41-$(Get-Date -Format 'yyyyMMdd-HHmmss').db" -ErrorAction Stop
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Hedef `0006_m41_evidence (head)`. Web için ikinci PowerShell:

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence\apps\web"
npm run typecheck
npm run dev
```

Mevcut `arkemx-dev.db` dosyası silinmez. `git stash pop` yapmadan önce eski yerel değişiklikler incelenmelidir. Ücretli servis veya bulut AI gerekmiyor.

## Kabul senaryosu

1. `DEMO-2026-TEST` kaynağı operatör onaylı olarak korunuyor mu kontrol et. `DEMO-2026-REVOKE-TEST` kaynağı iptal edilmiş ve kilitli kalmalı.
2. Onaylı kaynakla M3 eşleştirme oluştur, M4.1 bölümündeki **Kaynaklı teknik kanıt oluştur** butonunu kullan.
3. Beş metraj için kaynaklı kanıt oluşturulduğu ve önceki M3/M4 kararlarının taşınmadığı doğrulanmalı.
4. Ayrı sentetik teknik denemelerde `hazır beton döküm C25/30 nakliye dahildir` ile `hazır beton döküm C30/37 nakliye dahildir` **engelli**; `C25/30 nakliye hariç` **engelli**; eksik nakliye kapsamı **inceleme** olmalı.
5. Her iddiadaki gösterilen alıntıyı normalleştirilmiş metnin `start/end` aralığı ile karşılaştır.
6. `F5` ile kalıcılığı doğrula. Veritabanındaki bir kanıt hashini değiştiren olumsuz testte görüntüleme/onay **409** ile reddedilmeli.
7. İptal edilmiş M3 kataloğunda M4.1 yeni çalışma ve yeni mühendis onayı reddedilmeli; diğer firmaların projelerine erişim `404`.

## API

| Method | Endpoint | Amaç |
|---|---|---|
| POST | `/api/projects/{id}/m41/run` | Son izinli katalogla yeni M4.1 kanıt çalışması |
| GET | `/api/projects/{id}/m41/latest` | Kaynaklı iddiaları, SHA kontrolüyle salt okunur getir |
| POST | `/api/projects/{id}/m2/decisions` | Mevcut insan kararı API'si; M4.1 için kanıt bütünlüğü ve uyum şartı |

## Ticari sürüme kadar açık riskler

- **En büyük eksik:** Mevcut M3 CSV/XLSX alanı kısa poz başlığıdır. Tam poz açıklaması, iş tarifi, alt analiz ve şartname dokümanları henüz sisteme alınmıyor. Dolayısıyla `review` yaygın ve doğru sonuçtur.
- Türkçe varyasyonlar, iç içe cümlelerde kapsam olumsuzluğu, istisna/hüküm önceliği, kapsamın başka maddelere bağlanması gibi dil halleri daha ayrıntılı işlenmelidir.
- Betonda TS EN atıfları açıkça bulunmayan şartnameler otomatik uygun sayılmamalı. Standart numarasının aynı olması bile sürüm/yayın yılı ve performans uyumunu kanıtlamaz.
- Kapsam karşılaştırması `nakliye`, `işçilik`, `malzeme`, `montaj`, `yardımcı imalat` ile sınırlıdır.
- Bağımsız uzman etiketli gerçek veri seti, gerçek katalog kullanım hakları, PostgreSQL migration ve çok kiracılı güvenlik denetimi olmadan ticari kullanım uygun değildir.
