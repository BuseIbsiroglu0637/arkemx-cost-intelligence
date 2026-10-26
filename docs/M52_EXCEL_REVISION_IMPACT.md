# ARKEMX M5.2 — Excel Metraj Revizyonu ve Maliyet Etkisi (yerel pilot)

## Özellikler
- **Önizleme:** Tek bir projenin son M1 metrajı ve yüklenen revize .xlsx karşılaştırılır. Henüz hiçbir veritabanı kaydı oluşturulmaz.
- **Alan eşleştirme:** Aynı M1 Excel okuyucu ile sayfa, başlık satırı ve imalat/miktar/birim sütunları seçilir.
- **Satır ilişkisi:** Satır sıra numarası, birebir açıklama ve birim koşulları birlikte değerlendirilir. Tekrar eden imalatlar, tarifi/ölçü birimi değişen veya eklenen/kaldırılan satırlar **belirsiz** işaretlenir; asla kesin poz kimliği kabul edilmez.
- **Maliyet etkisi:** Yalnızca kaydedilmiş ve bütünlük doğrulanmış M5 maliyet taslağında o orijinal satırın açıklaması, miktarı ve birimi aynıysa, bilinen manuel fiyatla miktar farkının *öngörü niteliğindeki* etkisi hesaplanır. Bilinmeyen etki varsa toplam maliyet değişti denilemez.
- **Kontrollü kaydet:** Kullanıcı revizyon gerekçesini girip açık onay verirse yeniden okunan dosyanın SHA-256'sı önizleme ile eşleşmeli; beklenen eski import hâlâ son import olmalı. Yeni ve önceki Excel dosyaları ayrı immutable ImportBatch kayıtlarında saklanır, iki SHA ve karşılaştırma özeti M5.2 olayına eklenir.
- **Yeniden mühendis kontrolü:** Yeni import sonrası önceki M4.3/M4.2 çalışmasının onayları yeni metrajda geçerli değildir. M4.3 yeniden çalıştırılıp M4.2'de pozlar tekrar onaylanmalıdır. Eski M5 taslakları değişmez.

## Kullanıcı kabul senaryosu
1. M5-TEST-01 projesinde M5.0 taslaklarının 15.625 TL olduğunu kontrol edin.
2. Bir satır "Hazır beton döküm C25/30 nakliye dahildir", miktar 13, birim m3 içeren revize Excel oluşturun.
3. Metraj sekmesindeki M5.2 panelinden dosyayı yükleyin, başlıkları eşleştirin, eski 15.625 TL taslağını seçin.
4. Önizleme: 1 eski/1 yeni, 1 miktar değişimi, +625 TL **indicative** miktar etkisi, iki kaynak SHA.
5. Gerekçe ve açık onay olmadan kayıt oluşturulmadığını test edin. Kabul edildikten sonra yeni import eklenmeli ve M5/eligible geçersiz eski çalışmayı engellemelidir.
6. Eski iki M5 taslağı ve tarihî SHA-256 değerleri korunmalıdır.

## Sınırlar ve güvenlik
- En fazla 500 satır / .xlsx en fazla 10 MB. Yalnız yerel sentetik verilerle test edilmeli.
- Teknik kapsam değişiminde ya da yinelenen isimli/satırları taşınmış metrajda **otomatik satır eşleştirmesi, otomatik mühendis onayı veya otomatik kesin maliyet** yoktur.
- M5.2 karşılaştırması M2.1 satır düzeltmelerini sessizce kopyalamaz; yeni import açık kullanıcı eylemidir.
- Metraj fiyat kaynağı resmî tarife değildir; kullanıcı M5'te girdiği manuel fiyat öngörüdür.
- Migration 0009_m52_excel_revisions önce veritabanı yedeği alınarak uygulanmalıdır.
