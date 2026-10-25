# M5.1 — Taslak maliyet analizi ve revizyon etkisi (pilot)

M5.0 taslaklarını değiştirmeden fiyat/miktar etkisini ayrıştırır.

## Kaydedilmiş iki taslağı karşılaştır
GET /api/projects/{project_id}/m51/compare?baseline_id=...&target_id=...&page=1&page_size=20

- Yalnız aynı projede ve aynı kullanıcı kuruluşuna ait SHA-256 doğrulanmış iki M5.0 taslağı.
- Poz satırları work_item_id ile eşleştirilir. Yeni içe aktarımdaki benzer açıklamalar aynı fiziksel iş sayılmaz.
- Aynı işte poz kodu, birim, imalat açıklaması veya teknik kanıt SHA-256 değişmişse scope_changed; salt fiyat etkisi diye gösterilmez.
- Miktar etkisi = (yeni miktar - eski miktar) × eski fiyat.
- Fiyat etkisi = yeni miktar × (yeni fiyat - eski fiyat).
- Ara yuvarlama farkı açıkça gösterilir; eklenen/çıkarılan/kapsamı değişen pozların toplam farkı ayrıca raporlanır.
- Satır sayısı ve tutar toplamı uyuşmazsa 409.

## Salt okunur miktar/fiyat simülasyonu
POST /api/projects/{project_id}/m51/simulate

İstek örneği:
    {"estimate_id":"<taslak-id>","changes":[{"candidate_id":"<poz-aday-id>","quantity":"13.0000","unit_price":"1400"}]}

- Alanlardan biri yeterlidir; en az biri girilmeli. Fiyat ve miktar pozitif ve en fazla dört ondalık basamaklı.
- Metraj kaydı, mühendis onayı ve eski taslaklar güncellenmez. Simülasyon nihai teklif, otomatik maliyet kaydı veya teknik onay değildir.
- Her iki API kayıtlı taslakların SHA bütünlüğünü önce doğrular; farklı firma verisini sızdırmaz.
- Pilot sınırı: taslak başına 500 kalem; karşılaştırma 20/100 satırlık sayfalarla gösterilir.
- Bu geliştirme veritabanı migration'ı gerektirmez.
