# A3.49.2 — Metraj satırından kalıcı 2026 poz adayı arama

## Çalışma şekli

Mimarın kaydedilmiş Excel satırı A3.49.1 tarafından teknik alanlarına ayrılır. A3.49.2, **yalnız ilgili firmanın Windows'ta kalıcı kayıtlı 2026 resmî PDF Poz Kütüphanesi** içinde çalışır; yeni PDF yükleme gerekmez. Gerçek poz kodu, PDF sayfası, birimi ve fiyatı kaynaktan alınır. 933 analizlik Cilt 1'de varsa analiz bağlantısı ayrıca belirtilir.

Arama kuralları:

1. Poz numarası açıkça metrajda varsa birebir kaynak koduna bakılır; yine de teknik çelişkiler atlanmaz.
2. Türkçe teknik anahtar kelimelere göre en fazla 180 PDF kayıt ön seçilir; tekrar eden genel kelimeler yerine ayırt edici terimler ağırlıklandırılır.
3. Poz ve metraj kalınlığı/ölçü birimi/ebat/iş kapsamı/malzeme/çimento-alçı bağlayıcısı karşılaştırılır; açık çelişkiler `blocked_examples` içinde açıklanır.
4. Aday listesinde teknik olarak açıkça çelişkili olmayan en çok 3 gerçek kaynak kodu gösterilir. Eksik teknik özellikler `review_flags` olarak korunur.
5. Tek satırda gazbeton+sıva gibi iki imalat varsa tek poz seçilmez; satırın ayrıştırılması gerektiği bildirilir.

Hiçbir aday **mühendis onayı**, **fiyat kesinliği** veya **maliyet hesabı** anlamına gelmez. Benzerlik puanları doğruluk yüzdesi değildir. Bu ilk aşama deterministik token araması ve teknik kurallar kullanır; semantik embedding ve toplu kalite denetimi sonraki gelişmelerdir.

## Uygulamada

**Metraj** sayfasına git; seçili 408 kalemlik projede **Metraj açıklamalarını yorumla** bölümünü aç. Önce 10 kalemlik örnek Excel varsa onu seçip **Metrajı yorumla** butonuna bas. Her satırdaki **Adayları gör** düğmesi gerçek 2026 PDF'de arama yapar. Üstte en fazla 3 aday, altta açılır **Teknik nedenle elenen örnekler** bölümü vardır. Satırlar sayfalıdır; 408 satır için tek seferde eşleştirme kararı üretilmez.

## API ve kanıt

`GET /api/projects/{project_id}/a349/imports/{import_id}/items/{work_item_id}/candidates`

API yanıtında Excel dosyası SHA-256, satır numarası, son revizyon kimliği ve 2026 PDF SHA-256, kod, açıklama, PDF sayfası, ayrı fiyat/anl. bağlantısı bulunur. Farklı firma/proje Excel'ine erişim engellenir. Her yanıt `read_only=true`, `approval_allowed=false`, `candidate_selected=false`, `cost_allowed=false` döner. Kaynak poz JSON/PDF'lerine veya maliyet/karar veritabanına yazma yok.

## Windows'ta test için

Mevcut ARKEMX API ve web sunucularını **Ctrl + C** ile kapat. API portu **8000**, web portu **3000** değişmiyor.

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483
git fetch https://github.com/BuseIbsiroglu0637/arkemx-cost-intelligence.git refs/heads/feat/a3492-catalog-candidate-search
git switch -c feat/a3492-catalog-candidate-search FETCH_HEAD
```

API terminalinde:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\services\cost-api
$env:DATABASE_URL = 'sqlite:///C:/Users/busei/arkemx-dev/arkemx-a3482-runtime/arkemx-a3482-test.db'
$env:UPLOAD_DIR = 'C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\uploads'
$env:CORS_ORIGINS = 'http://127.0.0.1:3000,http://localhost:3000'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Web terminalinde:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\apps\web
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8000'
npm run dev -- --port 3000
```

Aç: `http://127.0.0.1:3000/#metraj`. Mevcut aynı test veritabanı, organizasyon ve `%LOCALAPPDATA%\ARKEMX\catalogs` korunur. P01 orijinal DB'ye gitme, PDF dosyalarını tekrar yükleme.

## Geliştirme kabul kriterleri

- 10 cm gazbeton, 15 cm yanlış kalınlığı doğru diye sunmaz; bu poz teknik engelli listesinde gösterilebilir.
- 2 cm çimento sıvayı 2,5 cm alçı sıvaya otomatik bağlamaz.
- 60×60 seramik ile 30×60 ebat farkını bloklar.
- PVC yalnız işçilik ile malzeme alımını/yapımını ve söküm ile yeni kaplamayı ayırır.
- Listede fiyat olmayan pozun fiyatını `0` olarak üretmez.
- Excel satırı çoklu imalat içeriyorsa tek poz seçmez.
- Kaynak PDF/Excel SHA ve sayfa/satır kanıtı saklanır.

**A3.49.2 geliştirme ortamında test edilmeden gerçek 408 satırın doğru eşleştiği iddia edilmez.** Sonraki aşamada 408 satırın tamamı için kapsama ve hata nedenleri raporu oluşturulmalıdır.
