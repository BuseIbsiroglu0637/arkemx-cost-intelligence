# M5.1.2 — 100–500 kalemli maliyet revizyonu güvenlik testi

## İlk geliştirme
- Karşılaştırma kodu M5 taslaklarının eski SHA ve parasal bütünlük kontrollerini korur.
- 500 farklı pozun teknik kaynakları satır bazında yüzlerce sorguyla değil, 400 kimliklik sınırlandırılmış gruplarla alınır; eski SQLite bağ değişkeni limitleriyle uyumludur.
- Tekrarlı pozlar, farklı açıklama/kapsam, farklı poz kimliği, kodu veya birim otomatik fiyat/miktar değişimi sayılmaz.
- Sentetik 100 ve 500 eşsiz poz örneğinde deterministik eşleştirme ve toplam miktar etkisi kontrol edilir.
- Tam 500 satırlı Excel yükleme/M4.3 işleme/M4.2 uzman inceleme/M5 kaydetme uçtan uca performans ve kabul testi **henüz yapılmadı**.

## Sentetik kontrol örneği
Her satırda miktar 12.5 → 13.0 m³, fiyat sabit 1.250 TL.
- 100 ayrı poz: toplam miktar etkisi +62.500 TL.
- 500 ayrı poz: toplam miktar etkisi +312.500 TL.
- Fiyat etkisi ve yuvarlama düzeltmesi: sıfır.

## Sonraki kalite kapısı
1. 100 satırlı gerçek XLSX formatında sentetik veri: bağımsız M1 importları, katalog onayı, M4.3 Worker, M4.2 uzman kararı ve M5 taslağı.
2. 500 satırda kaynak koruma, sıralama, sayfalama (20, 50), SHA bütünlüğü.
3. Karışık senaryo: aynı poz, tekrarlı/çakışan kod, miktar artışı, fiyat düşüşü, yeni/çıkarılan kalem, teknik kapsam değişimi.
4. Uçtan uca zaman, CPU, RAM ve sorgu sayısı gerçek pilot cihazında ölçülmeli; limit uygunluğu iddia edilmemeli.
5. GitHub CI ve Windows yerel kabulü olmadan kullanıcı gerçek müşteri dosyası yüklememeli.

## Güvenlik sınırları
- Eski maliyet taslakları, mühendis kararları, import SHA-256 ve veritabanı satırları değiştirilmez.
- Kayıtlı veya gerçek resmî birim fiyat kullanılmaz; sentetik manuel fiyat.
- Otomatik mühendis onayı veya taslak üretimi yapılmaz.
