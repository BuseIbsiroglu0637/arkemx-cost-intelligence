# M5.2.1 — Güvenli iş kuyruğu ve metraj kaynak yönetimi (yerel pilot)

## Neden
M5-TEST-01 üzerinde yanlışlıkla normal M1 ile içe aktarılmış bozuk R02 kaydı (Türkçe karakter / birim), daha yeni temiz 13 m³ M1 kaydı ve bekleyen M4.3 işi bulunuyor. Bu modül iş ve kaynak kimliklerini silmeden operatör kontrolü sağlar.

## M4.3 güvenli iptal
- `POST /api/projects/{project_id}/m521/jobs/{job_id}/cancel`
- Yetki: aynı kuruluşun `admin` kullanıcısı, en az 10 anlamlı karakterlik gerekçe.
- Yalnız `queued` ve `lease_owner IS NULL` durumuna tek SQL compare-and-swap uygular, `blocked` statüsü ve operatör gerekçesi kaydeder. Veritabanındaki `bulk_jobs` CHECK kısıtı olduğu için yeni statü eklenmez. Kayıt ve dondurulmuş MatchRun/kanıt yapıları silinmez.
- `running`, `completed`, `failed`, `blocked` işlerde ilk iptal reddedilir. Daha önce iptal edilen işe tekrar aynı çağrı idempotent yanıttır. Worker ile yarıştığında yalnız bir taraf kazanabilir.
- `GET /m521/jobs` iptal gerekçesi ve işlem geçmişine bağlanan iş durumunu döner.

## Kullanım dışı Excel
- `POST /m521/imports/{import_id}/exclude`; `GET /m521/imports`.
- Yalnız aynı kuruluş admini; `queued` / `running` iş varken o dosyaya dışlama yapılamaz.
- Orijinal M1 `imports`, `work_items`, SHA-256 ve M5 taslakları değiştirilmez.
- Dışlama pilot aşamada **geri alınamaz** ve normal teknik incelemelerde (M2/M3/M4/M4.2/M4.3/M2.1 yeniden eşleştirme) o anki son Excel'e güvenilmesini engeller. Eski onaylar otomatik yeniden etkinleşmez.
- Son dosya dışlandıysa yeni teknik analiz için daha yeni temiz M1 Excel yüklemek gerekir; sessizce eski kaynağa düşülmez.

## Tarihî metraj kaynağı
- M5.2 `preview` ve `apply` isteği opsiyonel `baseline_import_id` kabul eder.
- Seçili M5 taslağının bağlı olduğu `import_id` ile birlikte verilirse eşleşmeli (aksi 409).
- Son importtan farklı bir kaynakla önizleme **salt okunur**, maliyet etkisi indikatif; `apply_allowed=false`.
- Kullanıcı seçimi geçmiş metrajın teknik inceleme onayını otomatik taşımaz.
- Yeni revizyon onayı her zaman M4.3 ve M4.2 ile yeniden yapılmalıdır.

## Güvenli yerel devreye alma
1. API, web ve Worker durdurulur.
2. Mevcut SQLite veritabanı `sqlite3.Connection.backup` ile ayrı dosyaya, `PRAGMA integrity_check = ok` kontrollü yedeklenir.
3. `feat/m5-2-1-safe-revision-queue` dalına geçilir.
4. `alembic current`; `alembic upgrade head`; `alembic current` ile `0010_m521_safe_queue (head)` doğrulanır.
5. Kullanıcı güvenlik panelinde **önce salt-okunur** GET listeleri kontrol eder. Doğru queued job ve bozuk import UUID/SHA gözlemi yapılır.
6. Kullanıcı onayı ve gerekçe olmadan iptal/dışlama çalıştırılmaz.
7. Bekleyen işi iptal edip sonuç `blocked` görüldükten sonra, yalnız bozuk kaynağı işaretleme değerlendirilebilir. Son temiz R02 importu kullanılabilir halde kalır.

## Kabul
- Worker iptal edilmiş işi alamaz; yanlış lease durumunda 409.
- Başka kuruluş iş/satır/ithalat kaydını okuyamaz veya değiştiremez.
- Önceden kaydedilmiş 15.625 TL M5 taslağı SHA-256 doğrulamasıyla açılır.
- Eski 12,50 m³ / yeni 13,00 m³ karşılaştırmasında indikatif +625,00 TL değişmez.
- Migration `0010` uygulanmadan web/API değişikliklerini canlı yerel DB'de çalıştırma.
