# A3.48.4 — 2026 Cilt 1 analiz istisnaları

**Kaynak incelemesi (2 Kasım 2026):** 2026 İnşaat Birim Fiyat Analizleri Cilt 1 PDF 704 sayfadır; 933 analiz başlığı tespit edilmiştir. Önceki okuyucu 930 sabit fiyatlı analizi çıkarmış ve 3 başlığı atlamıştı:

| Analiz poz | PDF sayfası | Gerçek durum | A3.48.4 |
|---|---:|---|---|
| `15.110.1001` | 43 | Derinlik zammı, **F=M×(H−2)×K**, M=0,50; parasal hücre boş | Formül saklanır, `analysis_price=null` |
| `15.110.1002` | 44 | Aynı tür, M=1,00; parasal hücre boş | Formül saklanır, `analysis_price=null` |
| `15.341.5001` | 596 | Analiz adı üst hücrede boş, ancak dört girdi ve 153,76 TL/m² fiyatı var | Girdiler/fiyat çıkarılır, başlık eksikliği işaretlenir |

2026 Fiyat Listesi PDF'sinde bulunmayan **`15.130.1001`** analizi, Cilt 1 sayfa 88'de vardır. Fiyat listesi aynı işin `15.130.1002/1003/1004` imalat pozlarını içerir. Bu kodu kendi başına yeni bir resmî fiyat listesi pozu olarak uydurmayın. İlgili analiz girdilerinde kaynak kodu olarak görünmesi normaldir.

## Kayıtların güvenli tekrar analizi

Mevcut A3.48.3 test `DATABASE_URL` ve `UPLOAD_DIR` değerleri korunur. Uygulama güncel kodla çalışınca **'Kayıtlı analizleri yeniden kontrol et'** düğmesine tıklayın. Sistem mevcut analiz PDF'sini yeniden okumak için tekrar yüklemenizi istemez. PDF SHA-256 doğrulanır; `analysis-a3484.json` yeni sürüm olarak yazılır ve yalnız `current.json` pointer güncellenir. Önceki `analysis.json`, orijinal `source.pdf`, fiyat listesi, proje/metraj, mühendis onayı ve M5 maliyet verilerine dokunulmaz.

Beklenen kaynak tarama sonucunda 933 başlık işlenmiş olur; 931 sabit fiyatlı, 2 formüllü analiz bulunur. En az 1 analiz kodunun (`15.130.1001`) Fiyat Listesi PDF'sinde bulunmaması kaynağa dayalı bir farktır; otomatik yeni fiyat pozuna dönüştürülmez. Gerçek işletim sonucu arayüzdeki 'Bağlanan' sayaçlarından yeniden doğrulanmalıdır.

## Windows sabit portlar

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483
git fetch https://github.com/BuseIbsiroglu0637/arkemx-cost-intelligence.git refs/heads/fix/a3484-analysis-source-exceptions
git switch -c fix/a3484-analysis-source-exceptions FETCH_HEAD
```

API'yi yine port **8000**, web'i port **3000** ile, aynı test DB ve uploads değişkenleriyle başlat. `http://127.0.0.1:3000/#technical` adresinde iki PDF'nin kaynaklarını ve yeni yeniden kontrol butonunu görürsün.

**Doğrulama:** `15.110.1001` ve `15.110.1002` açınca formül/katsayı görünmeli; `15.341.5001` açınca 153,76 TL ve girdiler görünmeli; `15.130.1001` bağlantısız kaynak analiz kodu olarak ayrıca raporlanmalı. Formül girdisi olmayan hiçbir kaleme 0 TL atanmaz.

Bu modül M5 fiyatlandırma, parametre doldurma ya da mühendis onayı oluşturmaz.
