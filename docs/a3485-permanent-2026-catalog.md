# A3.48.5 — 2026 Pozları Kalıcı Olarak Sakla

## Kullanıcı deneyimi

Bir kez yüklenmiş 2026 Bakanlık fiyat listesi (20.315 kayıt) ve detaylı analiz Cilt 1 (933 kayıt), aynı Windows kullanıcı hesabında program kapanıp açıldığında ya da çalışma klasörü değiştiğinde yeniden yüklenmez. Poz Kütüphanesi'nin sağ üstünde **'2026 pozları yüklü'** görünür; arama, fiyat, girdi ve PDF sayfası detayları kullanılmaya devam eder. PDF yükleme kontrolleri yalnız kaynak eksikse ilk kurulum için görünür. Katalog yıl bilgisi, gerçek kaynak `edition_date` alanından gelir, HTML'ye sabit kodlanmaz.

## Kalıcı kayıt yeri

- Windows varsayılan: `%LOCALAPPDATA%\ARKEMX\catalogs\<organization-id>\price-list\` ve `...\analysis\`.
- Gerekirse `ARKEMX_CATALOG_HOME` ortam değişkeni ile kalıcı klasör değiştirilebilir; bunu değiştirmek eski klasörle bağlantıyı koparabileceğinden sabit tutun.
- Linux: `$XDG_DATA_HOME/ARKEMX/catalogs` (varsayılan `$HOME/.local/share/ARKEMX/catalogs`).
- Kaynak PDF, SHA kimliği, mevcut aktif indeks ve önceki indeks sürümleri korunur. Uygulama bu dizini **yazma yetkisi olan mevcut Windows kullanıcı hesabına** göre seçer.
- Pozların sahibi aynı firma/organizasyon kimliğidir; uygulama DB'sindeki kullanıcı/organizasyon kaydını siler ya da yeni sıfır DB ile açarsanız eski firma id'sine bağlı katalog kendi başına görünmez. İşletim yedeğinde DB ve katalog klasörünü birlikte tutun.

## Önceki 2026 PDF'lerinin ilk açılışta aktarılması

Mevcut `UPLOAD_DIR` değerini ilk A3.48.5 başlatmasında **değiştirmeyin**: `C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\uploads`.

Backend, oturum açıp Poz Kütüphanesi'ni görüntülediğinizde eski `UPLOAD_DIR/_a348_official_price_library/<organization>` ve `UPLOAD_DIR/_a348_official_analysis_library/<organization>` kaynaklarını bulur; `source.pdf`, SHA ve aktif indeks hash'ini doğrular. **Kopyalar, silmez, eski PDF veya indeksin üstüne yazmaz.** Kaynak bozuksa geçiş reddedilir ve uygulama bunu saklamak yerine hata gösterir.

Geçiş başarılı olduğunda, sonraki sürümlerde aynı hesap ve katalog klasörü korunursa `UPLOAD_DIR` yolu değişse bile bu iki kaynağı yeniden seçmeniz gerekmez. Başarılı geçiş gerçekleşmeden eski `uploads` dizinini SİLMEYİN. İleride yedek alırken hem SQLite/veritabanını hem kalıcı katalog klasörünü yedekleyin.

## Windows uygulama adımları (web 3000, API 8000)

API ve web sunucularını `Ctrl+C` ile kapattıktan sonra:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483
git fetch https://github.com/BuseIbsiroglu0637/arkemx-cost-intelligence.git refs/heads/feat/a3485-permanent-catalog-library
git switch -c feat/a3485-permanent-catalog-library FETCH_HEAD
```

API (1. PowerShell):

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\services\cost-api
$env:DATABASE_URL = 'sqlite:///C:/Users/busei/arkemx-dev/arkemx-a3482-runtime/arkemx-a3482-test.db'
$env:UPLOAD_DIR = 'C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\uploads'
$env:CORS_ORIGINS = 'http://127.0.0.1:3000,http://localhost:3000'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Web (2. PowerShell):

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\apps\web
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8000'
npm run dev -- --port 3000
```

Tarayıcı: `http://127.0.0.1:3000/#technical`. Giriş yapıp '2026 pozları yüklü' ibaresini kontrol edin, `15.225.1004` arayın; fiyat ve analiz detayı açılmalı. Ardından sunucuları kapatıp yeniden açın; katalog aynen görünmeli. İsterseniz başarılı geçişi `Test-Path "$env:LOCALAPPDATA\ARKEMX\catalogs"` ile sadece dosya varlığı açısından kontrol edebilirsiniz.

## Güvenlik ve sınırlar

- Katalog kalıcılığı, kullanıcının kendi bilgisayarındaki dosyalara bağlıdır. Bilgisayar/veri diski silinirse bu bilgiler yedekten geri getirilmelidir.
- Telifli PDF veya katalog verileri GitHub'a eklenmez ve diğer tenant'lara dağıtılmaz.
- Mühendis onayları, metraj, M5 maliyet tablosu ve orijinal proje DB bu adımda değiştirilmez.
- Şu anda doğrulanmış belge yılı **2026**. 2027 ve diğer yıllar için ayrı resmî kaynakları doğrulayan okuyucu/sürümlü yönetim ayrıca geliştirilmeli.

## Test

CI: `test_a3485_persistent_catalog.py` eski yükleme klasörü taşınsa bile yeni katalogun kullanıldığını; ilk geçişte SHA doğrulandığını; hatalı legacy PDF'nin reddedildiğini; eski analiz indeksinin korunabildiğini test eder.
