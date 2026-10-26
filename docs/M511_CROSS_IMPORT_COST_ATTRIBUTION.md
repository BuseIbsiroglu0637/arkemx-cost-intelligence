# M5.1.1 — Doğrulanmış çapraz Excel poz ilişkisi

## Sebep
R01'daki ve R02'deki aynı beton pozuna farklı M1 WorkItem kimlikleri atanır. Eski M5.1 yalnız WorkItem UUID eşleştirdiğinden toplam +625,00 TL farkın tamamını çıkarılan/eklenen kalemlere atfederdi.

## Yeni algoritma
- İlk önce aynı WorkItem ID varsa mevcut davranış devam eder (kapsam SHA farklıysa scope_changed).
- Eşleşmeyen iki taslağın katalog `version_id` ve `catalog_sha256` değeri aynı olmalıdır.
- Farklı WorkItem ID'sindeki çift yalnızca aynı `position_id`, poz kodu, normalize imalat açıklaması, normalize birim ve **her iki taslakta da benzersiz** satır kimliği ile adaydır. Kaynak satır numarası eşleştirme anahtarı değildir.
- CostEstimate SHA/aritmetik kontrolleri ve belge/katalog kaynak SHA kontrolü korunur. Teknik kanıtların SHA/özgün kaynak bağları bağımsız denetlenir. Sadece kaynak import kimliği değişmesinden doğan Evidence SHA farkı kapsam farkı sayılmaz; teknik sınıf ve kapsam olguları da eşit olmalıdır.
- Bir tarafta yinelenen imalat, kapsam değiştiren açıklama, başka katalog/poz veya farklı teknik iddia varsa otomatik eşleştirme **yoktur**. Belirsiz kalem miktar etkisine yazılmaz, açık şekilde gider/gelir etkisi açıklanamayan olarak kalır.
- Tüm sonuçlar GET /m51/compare okumasıdır. DB migration yok; hiçbir eski fiyat, mühendis kararı, import veya SHA-256 değişmez.

## Kabul
- Eski: 12,5 m³ * 1250 TL = 15.625 TL; R02: 13 m³ * 1250 = 16.250 TL.
- Miktar etkisi +625 TL, fiyat etkisi 0, açıklanamayan kapsam 0; 1 doğrulanmış çapraz-import çift.
- Ayrı katalog veya doğrulanmayan teknik kapsam `unattributed_effect` altında kalır.
- Çoklu eşleşmeler bire bir olmadığı için otomatik bağlanmaz; taslaklar değişmez.

## Windows güncelleme
Dalda `feat/m5-1-1-cross-import-matching`, en güncel commit alındıktan sonra API ve web sunucuları yeniden başlatılmalıdır. Migration gerekmez. Mevcut iki eski M5 taslağı ve R02 taslağı aynı şekilde seçilerek karşılaştırma tekrarlanır.
