# A3.48.1 — 2026 resmî poz kataloğu: ilk adım

Bu aşama **poz listesini okumak** içindir; metraj eşleştirme, onay, M5 maliyet veya fiyat teklifi oluşturmaz.

## Kaynak

Kullanıcının kendi cihazında bulunan 2026 tarihli ÇŞİDB / YFK "İnşaat Birim Fiyat Tarifleri Eki Fiyat Listesi" PDF'si. Ayrıntılı "İnşaat Birim Fiyat Analizleri Cilt 1" PDF'si **farklı** bir belgedir; bu okuyucuya analiz PDF'si verilmemelidir.

2026 belgesi tek başına inşaat, 10.x rayiç, 25.x mekanik ve 35.x elektrik tabloları barındırır. Tablolar aynı sütun düzenini kullanmaz.

## Nasıl kullanılır? (Windows, ayrı test ortamı)

1. A3.48 dalını ayrı bir worktree'de aç.
2. Komutları *a348* dalındaki \`services\cost-api\` klasöründen, bağımlılıkların yüklü olduğu Python sanal ortamında çalıştır.
3. Kullanıcıya ait resmi fiyat listesi PDF'sinin tam yolunu \`$pdf\` değişkenine yaz.

\`\`\`powershell
cd C:\Users\busei\arkemx-dev\arkemx-a348\services\cost-api
$pdf = "C:\Users\busei\Downloads\1-BF-202619011535-20260119155143.pdf"
$out = "C:\Users\busei\arkemx-dev\arkemx-a348-runtime\2026-poz-katalog.json"
Test-Path $pdf
python -m app.a348_official_price_list "$pdf" --out "$out"
\`\`\`

Bu araç kaynak PDF'yi ve mevcut P01 veritabanını **değiştirmez**. Hedef JSON zaten varsa üzerine yazmayı reddeder. JSON'u GitHub'a yüklemeyin: kaynak dosyaya ait uzun poz tarifleri içerir. Yalnız özel kullanım/test için yerelde saklayın.

## Çıktı sözleşmesi

- \`records[]\`: poz numarası, açıklaması, birim (varsa), fiyat hücresi (varsa), montaj bedeli (varsa), PDF sayfa numarası, kaynak türü ve \`cost_allowed=false\`.
- \`audit\`: PDF'de görülen kod sayısı, ayrıştırılan satır sayısı, ayrıştırılamayan kod/sayfalar, fiyatı alınan ve fiyatı boş kayıtlar, yinelenen numaralar.
- \`source_sha256\`: katalog kaynağının kimliği, \`edition_date\`: 01.01.2026.
- Fiyat hücresinin okunabilmesi = **yalnızca bir hücre değerinin çıkarılması**; doğru poz seçimi veya onay değildir.

## Kullanıcı PDF'si ile ilk örnek sonuç

**Baskı sürümüne ve kaynak dosyanın SHA'sına bağlıdır.** Hazırlık sırasında incelenen 741 sayfalık fiyat listesi:

| Gözlem | Sonuç |
|---|---:|
| PDF sayfası | 741 |
| Görülen poz kodu | 20.315 |
| Sınırlarıyla çıkarılan katalog kaydı | 20.297 |
| Denetimde bırakılan / çıkarılamayan | 18 |
| Fiyat hücresi okunabilen | 18.757 |
| Fiyatı boş veya başlık olan | 1.540 |
| Ayrıştırılmış kodlar arasında mükerrer | 0 |

Kaynak belgenin SHA-256 özeti: \`d8495a6b117111a4d2c9ed975527512c1dccd8371c2bb40c6d21700af0aeb307\`.

**Sınırlamalar:** Bu sayılar doğrulanmış yaklaşık maliyet kalemi sayısı değildir. Bazı satırlar genel başlıklar, alternatif ürün tipleri veya yalnız montaj bilgisi olabilir. Mekanik/elektrik kalemlerinin ölçü birimi birçok satırda üst başlıkta bulunur ve ayrıca doğrulanmalıdır. Denetimdeki 18 kod manuel PDF kontrolü gerektirir. Bu aşama farklı kurum kataloglarını veya 2026'ya ait sonradan yayımlanmış olabilecek düzeltmeleri kapsamaz.

## Sonraki adım

A3.48.2: Yerel JSON kataloğu **sürüm/kaynak kimliği ile arama indeksine** bağlamak. 10 kalemlik test metrajının hepsini taratmak, teknik uyuşmazlıkları ayırmak, analiz PDF'sini aynı poz numarası üzerinden bağlamak. Ardından 408 kaleme geçmek. Poz bulunamadığı için otomatik özel poz veya TL=0 üretilmez.
