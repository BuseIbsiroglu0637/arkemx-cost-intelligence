# ARKEMX küçük maliyet pilotu

Bu sürümün amacı, 1–500 satırlık Excel metrajını kaynak ve tarihi belirtilmiş
birim fiyatlarla hesaplamak, kullanıcının kontrol ettiği sonucu kalıcı rapora
dönüştürmektir. Birim fiyatın gerçek projeye uygunluğu kullanıcı tarafından
kontrol edilir. Otomatik mühendislik onayı veya bütün Bakanlık kataloğunun
doğrulandığı iddiası yoktur.

## Windows'ta başlatma

1. Paketi yazılabilir bir klasöre çıkarın. Python 3.11+ ve Node.js 22+ kurulu olmalı.
2. `PILOTU_BASLAT.cmd` dosyasını açın. İlk kurulum internet gerektirir ve birkaç dakika sürebilir.
3. Tarayıcı `http://127.0.0.1:13010` adresinde açılır. Yerel pilot hesabı oluşturun.
4. Proje oluşturun, Metraj adımında Excel'i önizleyip kaydedin. Belirsiz miktar/birimleri düzeltin.
5. Maliyet ekranında ortak fiyat kaynağı ve tarihi girin; satırlara birim fiyat yazın.
   İstenirse satıra özel kaynak/tarih girilebilir. Fiyatlar TRY / gösterilen birim olmalıdır.
6. **Maliyeti hesapla** ile önizleyin. Kaynakları, miktarları, birimleri ve eksikleri
   kontrol edip kutuyu işaretleyin; raporu kaydedin. CSV çıktısını indirin.
7. Kapatmak için başlatma penceresinde Ctrl+C kullanın.

Başlatıcı mevcut `arkemx-dev.db` dosyasına dokunmaz. Ayrı `arkemx-pilot.db` ve
`data/pilot-uploads` kullanır. Sonraki açılışlarda pilot verileri korunur; migration
öncesinde SQLite'ın tutarlı backup işlemiyle `data/pilot-backups` altına yedek alınır.
Mevcut geliştirme veritabanına bu kodu uygulamak isteyen geliştirici, kendi yedeğini
alarak normal API ortamında `python -m alembic upgrade head` çalıştırmalıdır.
Başlatıcıdaki ayrı veritabanına eski projeler otomatik aktarılmaz.

## Hesap ve kapsam

- Miktar: kaydedilen Excel veya son açık metraj düzeltmesi.
- Birim fiyat: kullanıcının kaynak ve tarih vererek girdiği fiyat. `1250,50`,
  `1250.50` ve `1.250,50` kabul edilir. Belirsiz `1.234` reddedilir.
- Her satır `Decimal(miktar) × Decimal(fiyat)` ile hesaplanır; kuruşa HALF_UP
  yuvarlanır. Toplam yuvarlanmış satır tutarlarının toplamıdır.
- KDV, ilave kâr veya genel gider eklenmez. Bunların birim fiyat kaynağına
  dahil olup olmadığı kontrol edilmelidir. Fiyatlı satırlar için miktarlar pozitif olmalıdır.
- Eksik fiyatlı veya hatalı metrajlı satırlar sıfır sayılmaz, **hesap dışı** gösterilir.
  Eksik varsa çıktı **KISMİ ARA TOPLAM** olarak etiketlenir.
- Tüm satırların fiyatlanması fiziksel proje kapsamının eksiksiz olduğu veya teknik
  uygunluğun onaylandığı anlamına gelmez. Mükerrer fiziksel imalatları kullanıcı inceler.
- 501+ satır sessizce kesilmez; pilot hesap isteği bütün olarak reddedilir.
- Yeni rapor sadece son, hariç tutulmamış Excel'den oluşturulur. Önizleme ve kayıt
  arasında miktar, birim veya kaynak değişirse yeni önizleme gerekir.
- Kayıtlı rapor; bütün kalemleri, hesap dışı nedenleri, fiyat kaynak/tarihlerini,
  Excel SHA-256'sını ve metraj revizyon kimliklerini dondurur. Eski rapor değişmez.
- Kullanıcı inceleme beyanı, mesleki mühendis onayından ayrı kaydedilir. M5'in
  teknik onay kapıları veya mevcut PDF/analiz kaynakları değiştirilmez.
- Fiyat girişleri kaydedilmeden ekrandan ayrılmak bu geçici girişleri siler.
  Kaydedilmiş raporlar yeniden açılabilir ve CSV olarak indirilebilir.

## Mevcut PDF'den fiyat alma

Pozları incele ekranında kullanıcının yetkili olduğu 2026/01 analiz PDF'siyle
seçilmiş, güncel ve fiyat aritmetiği uzlaştırılmış pozlar varsa **Seçili PDF
fiyatlarını boş alanlara aktar** bunları fiyat önerisi olarak kopyalar.
Mevcut kullanıcı fiyatlarının üzerine yazmaz. Her fiyat referansında poz, sayfa,
dönem ve PDF SHA-256'sı yer alır. Kullanıcı yine miktar/birim ve kapsamı kontrol eder.
Kaynağın resmîliği veya bugünkü güncelliği bu işlemle doğrulanmaz. Yeni yüklenen PDF,
önceden kopyalanmış tarihsel fiyatı otomatik değiştirmez; kaynak referansını yenilemek
için ilgili fiyatı temizleyip yeniden aktarın. Düzenlenmiş analiz teklifleri bu
düğmeyle otomatik fiyat yapılmaz; kullanıcı bunların fiyatını ayrı referansla girebilir.

## Geliştirici doğrulaması

API: proje ortamında `python -m pytest -q -m "not external_pdf"`.
Web: `npm ci`, `npm run typecheck`, `npm run build`.
Migration: boş SQLite üzerinde `python -m alembic upgrade head`, sonra
`python -m alembic current` → `0017_pilot_cost_snapshots`.

Özel, hash'i sabitlenmiş gerçek PDF'lere bağlı eski testler **external_pdf**
olarak açıkça işaretlenmiştir. CI bunları çalıştırmaz ve sonuçları doğrulanmış
saymaz. Belge kabulünü ayrıca çalıştırmak için hak sahibi belgeleri yerel ortamda
`ARKEMX_ANALYSIS_PDF`, `ARKEMX_AUXILIARY_PDF` ve `ARKEMX_ALT_PDF` ile belirtip
`python -m pytest -q -m external_pdf` çalıştırın. Belgeler olmadan bu kabul kapısı
başarısız olur; sentetik belgeyle gerçek belge kabulü taklit edilmez.

Tarayıcı kabulünde 12,5 × 1250 + 3 × 0,335 = **15.626,01 TRY**;
ikinci fiyat kaldırılınca **15.625,00 TRY kısmi toplam** beklenir.
100/500 farklı satırda Excel → fiyat → hesap → kayıt → tekrar okuma testleri vardır.
Bu testler, gerçek piyasa fiyatı veya genel poz eşleştirme doğruluğu kanıtı değildir.

Bu yerel pilotun PostgreSQL üretim kurulumu, çok kullanıcılı yükü ve tüm resmî
katalogla doğruluğu ayrıca kabul edilmelidir.
