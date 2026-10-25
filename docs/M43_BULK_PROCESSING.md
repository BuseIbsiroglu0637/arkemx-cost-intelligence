# M4.3 — Kalıcı Yerel Toplu İşlem (500 Metraj)

**Geliştirici pilotu.** M4.2'deki mühendis kararı, kaynak izin denetimi ve kaynaklı M4.1 kanıtı korunur.

## Mimari ve kapasite
- Giriş: En son Excel içe aktarımı, 1–500 metraj kalemi. Excel parser'ı zaten 2000 satıra kadar açar; M4.3 motorunun sınırı **500**. M2/M3/M4 eski API sınırı hâlâ 100; M4.3 bunları değiştirmeden ayrı bir `/m43/jobs` yolu açar.
- Katalog: 1–500 poz, yalnızca M3 operatör onaylı ve hash doğrulanmış kaynak (veya sistemin özgün sentetik demoları).
- İşyeri: Kurum/proje kapsamıyla sınırlandırılmış `bulk_jobs`; idempotency anahtarı proje başına tekil. Kısmi işler ayrı `MatchRun` altında, tamamlanana dek M2/M4.2 "son sonuç" olarak yayımlanmaz.
- Kuyruk: API sadece kalıcı işi oluşturur. **Ücretsiz ayrı bir yerel Python worker** en fazla 20 satırlık transaction'larla işi yürütür; durum, ilerleme, kanıt ve adaylar aynı veritabanında tutulur.
- Güvenlik: İşin başında tüm satırların M2.1 etkin sürümü **dondurulur**. Her parça öncesinde katalog hakkı, son import ve dondurulmuş satırların revizyonları yeniden doğrulanır; değişiklik varsa `blocked`.
- Devam: Her işlem parçasında snapshot/tarama/kanıt/ilerleme tek transaction'da kayıtlı. Güç kesilirse 600 saniyelik işçi kira süresi dolduktan sonra aynı sıradaki satırdan işlenir. `failed` işleri tekrar kuyruğa alınır; `blocked` işlerine tekrar deneme izni yoktur, yeni çalışma gerekir.
- Sıralama: Her metraj için 500 poz metin benzerliği hesaplanır, yalnız en iyi 3 poz için kaynaklı teknik karşılaştırma çıkarılır (yüksek benzerlik teknik doğruluk değildir).
- Kanıtlar: `TechnicalComparison`, `TechnicalEvidence` SHA-256, poz/metraj kaynağı. Teknik durum `review/blocked/compatible`, hiçbir otomatik mühendis onayı yok.
- Durum ekranı: 2 saniyelik sorguyla `processed_rows`, `total_rows`, `candidate_count`, `status`, hata veya bitiş.
- Ürün ölçeği: Tek SQLite işçisi **geliştirme pilotudur**; birden fazla düğüm, büyük kurum verileri, dağıtık worker güvenlik garantileri için PostgreSQL+ayrı kuyruk ve benchmark gereklidir.

## Windows/PowerShell ücretsiz kurulum
Açık API ve web sunucularını Ctrl+C ile durdur.

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence"
git status --short
git fetch origin "refs/heads/feat/m4-3-bulk-processing:refs/remotes/origin/feat/m4-3-bulk-processing"
git switch --no-track -c feat/m4-3-bulk-processing refs/remotes/origin/feat/m4-3-bulk-processing

cd services\cost-api
$backup = "arkemx-dev-before-m43-$(Get-Date -Format 'yyyyMMdd-HHmmss').db"
Copy-Item .\arkemx-dev.db $backup -ErrorAction Stop
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest -q
```

Hedef `0007_m43_bulk (head)`. Eski sqlite dosyanız silinmez.

**Ayrı üç PowerShell penceresi**

API:
```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence\services\cost-api"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Yerel işçi (aynı klasörde, **yalnızca bir tane**):
```powershell
.\.venv\Scripts\python.exe -m app.m43_worker --watch
```

Web:
```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence\apps\web"
npm run typecheck
npm run dev
```

Tarayıcı: http://127.0.0.1:3000

## Akış
1. `ÖRNEK PROJE - 1` veya ayrı proje. 100/250/500 satırlı bir Excel içe aktar.
2. M4.3 bölümünde `OTHER / 2026 / DEMO-2026-TEST` onaylı katalogu seç. İptal edilmiş katalog seçilemez.
3. `500 satıra kadar toplu iş başlat` butonuyla işi kuyruğa ekle.
4. Worker açıkken satır sayıları ilerler. Worker kapanırsa ilerleme kalır. `--watch` ile yeniden açıldığında kaldığı yerden devam eder (kaza sonrası kira süresi geçebilir).
5. `completed` sonrası M4.2 listesinde metraj/poz adayları, filtreler, kayıtlı kanıtlar görüntülenir. Mühendis kararı **otomatik verilmez**.
6. `blocked` durumunda katalog izinlerini veya yeni metraj revizyonunu kontrol et. `failed` durumunda yalnızca transient hata düzeltildiyse yeniden dene.

## API
- `GET /api/projects/{id}/m43/catalogs`: onaylı ve uygun 1–500 poz katalogları
- `POST /api/projects/{id}/m43/jobs`: `{version_id,idempotency_key}`; HTTP 202, kayıtlı kuyruk
- `GET /api/projects/{id}/m43/jobs`: son 20 iş
- `GET /api/projects/{id}/m43/jobs/{job_id}`: ilerleme ve durum
- `POST /api/projects/{id}/m43/jobs/{job_id}/retry`: yalnızca `failed` durumundan güvenli yeniden başlatma
- `python -m app.m43_worker --watch`: yerel işçi; CLI ayrı çalışır

## Kabul ve performans
Otomatik testlerde 100/250/500 metraj × 3 sentetik poz; 45 satırda araya işlem kesintisi koyup yeniden başlatma; lease süresi ve hata sonrası retry; aynı idempotency key; farklı firma reddi; katalog izin iptali sonrası yarım kalanın yayımlanmaması. CI ölçümleri makineye özeldir ve kullanıcı bilgisayarı performansı değildir. Hedef CPU/SSD/RAM üzerinde süre, disk kullanım, worker kapanış ve toparlanma ayrıca ölçülecek.

## Açık riskler
- Sıralama hâlâ CPU-bound sözlük ve metin benzerliği ile yapılır; 500×500 poz karşılaştırma performansı gerçek cihazda ölçülmelidir. 
- 500 pozdan daha büyük resmi katalog veya çok kullanıcılı bulut üretimi bu sprintin kapsamı değildir.
- SQLite bir işçi pilotu, üretimde dayanıklı dağıtık job queue/PostgreSQL ayrı test gerekir.
- Piyasa fiyatı/standartların lisansı, KVKK, gerçek saha precision/recall ve kurum bazlı standart sürüm hakları doğrulanmadan ticari sürüme geçilmemeli.

## Sekmeli ARKEMX çalışma alanı
- Tek uzun sayfa yerine beş sekme: Genel Bakış, Metraj (M1/M2.1), Kataloglar (M3), Toplu Analiz (M4.3), Mühendis İnceleme (M4.2).
- Üstte proje seçici, son toplu işin durumu, son tamamlanan eşleştirmedeki poz sayısı ve onay sayısı; bu değerler mevcut okuma API'lerinden gelir, ayrıca yenilenebilir.
- Aynı anda yalnızca aktif modül görüntülenir. Metraj kayıtları ilk 20 satırla sınırlı görünür; tamamını açmak kullanıcı tercihidir. Revizyonlar isteğe bağlı yüklenir.
- Eski M2/M4 test ekranları yalnız Genel Bakış → Gelişmiş Araçlar altında açılır; eski M3 eşleştirme açık onay gerektirir.
- M4.2'den M4.3'e geçiş, yeni işlem oluşturmadan yalnızca ilgili sekmeyi açar.
- Migration yoktur. Mevcut 500 metraj, kanıtlar ve mühendis kararları saklanır.
