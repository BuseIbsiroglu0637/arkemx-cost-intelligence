# ARKEMX Cost Intelligence — M3 Katalog ve Kaynak Yönetimi

**Durum:** Geliştirici pilotu. Kamu pozları veya fiyatları bu repoya eklenmez. M3 bir veri taşıma/izin yönetimi altyapısıdır; Bakanlık veya diğer kurumların verilerini kullanma hakkı verdiği anlamına gelmez.

## Amaç

- Kurum: ÇŞİDB, DSİ, KGM, İLBANK veya Diğer. Excel/CSV kataloglarını *kullanım hakkı bulunduğu varsayılarak değil, inceleme için* yükle.
- Kaynak URL'si (HTTPS), kurum, yıl, dönem, orijinal dosya SHA-256'sı ve normalleştirilmiş poz kodu/tarifi/birimi/fiyatı saklanır. Orijinal dosya baytları saklanmaz: operatör kendi güvenli arşivinde saklamalı.
- Kullanıcılar katalog sütunlarını inceleyip eşleştirebilir, veriyi önizleyebilir ve `pending` statüsüyle kaydedebilir.
- Sadece ayrı yerel operatör onayından geçmiş `CatalogImport` kayıtları M3 eşleştirmeye açılır; sıradan firma yöneticisinin kaynak onayı **yeterli değildir**.
- Gerçek katalogda adaylar mevcut M2/M2.1 algoritmasıyla karşılaştırılır; kararlar mühendis tarafından verilir. İlgili yıl/katalog sürümü ve metraj snapshot'ları değiştirilmeden tutulur.
- Ücretsiz yerel kullanım: SQLite, FastAPI, Next.js; yerel Ollama isteğe bağlıdır. **Fiyat/keşif hesabı M3 kapsamında değil.**

## Dikkat — kullanma hakkı

Kamu internet sitesinden erişilebilir olmak, o içeriğin ticari üründe indekslenmesine, çoğaltılmasına, otomatik AI işlenmesine veya üçüncü kişilere yeniden dağıtılmasına izin verildiği anlamına gelmez. Hak değerlendirmesi, **kaynak belge/kurum, sürüm, yıl, faaliyet (yerel eşleştirme/ticari SaaS) ve aktarım şekli** için ayrı yapılmalıdır. Hukuk danışmanı ve veri kaynağı sahibinden teyit gerekebilir.

**Kataloglar otomatik indirilmez, siteler taranmaz, kamu verisi kopyalanmaz.** Örnek CSV tamamen kurgusal olarak üretilmiştir.

## Yerel başlatma — Windows 11

API ve web sunucularını durdur, SQLite dosyanı yedekle:

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence"
git status --short
# yerel değişiklikleri korumadan dal geçişi yapma
git fetch origin "refs/heads/feat/m3-licensed-poz-catalog:refs/remotes/origin/feat/m3-licensed-poz-catalog"
git switch --no-track -c feat/m3-licensed-poz-catalog refs/remotes/origin/feat/m3-licensed-poz-catalog

cd services\cost-api
Copy-Item .\arkemx-dev.db ".\arkemx-dev-before-m3-$(Get-Date -Format 'yyyyMMdd-HHmmss').db" -ErrorAction Stop
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Beklenen Alembic sürümü: `0004_m3_catalog (head)`. İkinci pencerede:

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence\apps\web"
npm run typecheck
npm run dev
```

Arayüz: http://127.0.0.1:3000

## Kabul testi (sentetik katalogla)

1. M2.1 proje ve revizyonların durduğunu doğrula. Uygulamanın M3 bölümünden `example-data/demo-poz-katalog.csv` dosyasını seç.
2. **Diğer** kurum, **2026** yılı ve `DEMO-2026-TEST` dönemini seç. Önce başlıkları incele, gerekirse sütun eşleştir, önizle.
3. Kaydet. Katalog `pending` olmalı. Poz eşleştirme butonu kilitli kalmalı.
4. Testin devamında *yalnızca kendi ürettiğin sentetik katalog* için bağımsız operatör akışını deneyebilirsin. Bir kanıt metin dosyası hazırla, örn. `C:\secure\synthetic-rights-demo.txt` ve içinde kendi kurgusal verini ürettiğini belirt. Bu kanıt dosyasını git'e ekleme.
5. M3 API'de `GET /api/m3/imports` kayıtlarından `id` alanını öğren. **Kullanım hakkı gerçekten doğrulanmadan gerçek poz dosyasında onay komutunu çalıştırma.**
6. Aşağıdaki komutu sadece ayrı operatör rolünde ve sentetik kaynak için çalıştır:

```powershell
# services\cost-api klasöründe
.\.venv\Scripts\python.exe -m app.catalog_operator approve `
  --import-id "KATALOG_IMPORT_UUID" `
  --reviewer "Local operator - test" `
  --evidence-file "C:\secure\synthetic-rights-demo.txt" `
  --reason "Entirely original synthetic fixture made for local development testing" `
  --confirm-rights I_VERIFIED_THE_DATASET_RIGHTS_FOR_INTERNAL_MATCHING
```

Komut yalnızca backend'e erişebilen yerel operatörün yapabileceği bir işlemdir; **ticari lisansı kendiliğinden oluşturmaz**. Üretimde kimlik doğrulamalı bağımsız operatör portalı, iki aşamalı onay, izin bitişi ve iptal akışı gereklidir.

7. Sayfayı yenile; onaylanmış katalogu seç ve poz eşleştir. M2 kartlarında kurum/yıl/dönem görünmeli; adaylar için insan onayı gerekli.
8. Birim veya tarif uyuşmazlığı uyarısı devam ediyorsa otomatik kabul yapılamaz.
9. Operatör izin iptali komutu:

```powershell
.\.venv\Scripts\python.exe -m app.catalog_operator revoke `
  --import-id "KATALOG_IMPORT_UUID" `
  --reviewer "Local operator - test" `
  --evidence-file "C:\secure\synthetic-rights-demo.txt" `
  --reason "Data matching rights were intentionally revoked for regression testing"
```

İzin iptalinden sonra yeni eşleştirmeler ve yeni onaylar reddedilir. Geçmiş çalıştırmalar arşiv amaçlı kalır.

## API

| Method | Endpoint | Açıklama |
|---|---|---|
| POST | `/api/m3/inspect` | Excel/CSV başlıklarını bul |
| POST | `/api/m3/preview` | Poz dosyasını kaydetmeden doğrula ve ilk 12 satırı göster |
| POST | `/api/m3/imports` | Kurum/yıl/dönem ile yalnızca `pending` katalog kaydet |
| GET | `/api/m3/imports` | Yalnız kendi firma kataloglarını listele |
| GET | `/api/m3/imports/{id}/positions` | İlk 20 poz için kaynak inceleme |
| POST | `/api/m3/projects/{id}/run` | Sadece operatör onaylı sürümle çalıştır |

Kısıtlar: 5 MB, 5.000 poz/sürüm, 100 metraj kalemi/eşleştirme, 24 sütun, UTF-8 CSV veya XLSX, tek sayfa. PDF/OCR ve doğrudan canlı kaynak senkronizasyonu yoktur. Kod sütunu Excel'de **metin** biçiminde olmalı; baştaki sıfırlar otomatik korunamazsa yüklemeyi reddetmek/gözden geçirmek gerekir. Fiyatlar negatif, belirsiz veya formül olamaz.

## Teknik kayıtlar

- `catalog_imports`: firma, kaynak, sürüm, dosya hash, durum, onay kanıtı, operatör, yıl/dönem.
- `catalog_review_events`: append-only izin onayı/iptali; kanıt dosyasının SHA-256'sı, katalog SHA-256'sı, operatör ve gerekçe.
- `catalog_versions`, `catalog_positions`: mevcut M1/M2 tablo yapıları; fiyat ayrı birim ve para birimiyle saklanır, hesaplamada kullanılmaz.
- `match_runs`: M2.1 ile sabitlenmiş katalog ve metraj kimlikleri.

## Çıkış kapısı (pilot)

- [ ] SQLite migration 0004 PASS (önce mevcut veritabanını yedekle)
- [ ] PostgreSQL migration 0004 PASS
- [ ] pytest M1–M3 PASS
- [ ] npm typecheck ve build PASS
- [ ] Windows tarayıcı gerçek akış PASS
- [ ] Tenant sınırı ve izinsiz onay denemeleri reddediliyor
- [ ] Bağımsız operatör kanıtı olmadan M3 eşleştirme kapalı
- [ ] İzin iptalinde yeni eşleştirme ve onay kapalı
- [ ] Tedarik edilen katalogun kullanım izni ve lisans kapsamı yazılı olarak doğrulanmış
- [ ] Müşteri verisi güvenliği, yedek/geri yükleme, üretim oturumu, rate-limit ve izlenebilirlik tamamlanmış

**Bu aşama ticari hizmete açılmayacak.** Geliştirici pilotu, hak analizi ve test araçlarıdır.
