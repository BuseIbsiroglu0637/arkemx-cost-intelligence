# M4.3.1 — Güvenilir poz kimliği / yanlış eşleşme koruması

## Sorunun kapsamı
100 adet benzer sentetik beton tarifi için mevcut M4.3 her satırda en fazla 3 aday oluşturur. C25/30 ve nakliye kapsamı aynı olduğu için kalem 001'in poz 002 ve 003 ile eşleşmesi eski teknik kanıtlarda 'compatible' olabiliyordu.

## Güvenli kontrollü test kuralı
- Sadece \`DEMO-M512-NNN\` **sentetik test kataloğu** için açıkça belirtilen \`kalem NNN\` metraj/katalog etiketleri poz koduyla karşılaştırılır.
- Üç kimlik aynıysa yalnızca *bu ek kontrol* PASS olur. Teknik kapsam ve mühendis onayı hâlâ bağımsızdır.
- Farklı kimlik → \`M512_ITEM_ID_MISMATCH\` onay engeli.
- Tek tarafta yok veya aynı tarifte birden çok farklı kimlik → \`M512_ITEM_ID_UNVERIFIED\` uzman incelemesi. Otomatik onay yok.
- Diğer gerçek kataloglarda rastgele satır numaraları ya da \`kalem\` kelimesi evrensel poz kimliği kabul edilmez.
- Yeni M4.3 karşılaştırmasında ek kontrol ve alıntı kaynakları TechnicalEvidence SHA'ya dahil edilir; geçmiş teknik kanıtlar **değiştirilmez**.

## Eski çalışmalardaki koruma
- Daha önce üretilen 300 aday için eski kanıtlar silinmez, SHA'lar yeniden hesaplanmaz.
- Kullanıcı 'Mühendis olarak onayla' dediğinde, sunucu M512 tanımına özgü kimlik kontrolünü **yeniden** yapar ve eski kanıtında \`fixture_item_identity\` yoksa HTTP 409 ile reddeder.
- M4.2 liste ve kanıt ekranları ek \`identity_issue\` ile uyarır; \`can_approve=false\` olarak döner.
- Eski raporun \`compatible\` sayıları geçmiş snapshot'tır, yeni güvenlik kontrolünün sonucu değildir. Yeni M4.3 çalışması oluşturulduğunda sayılar güncellenir.

## Kabul
- Yeniden işlenen 100 sentetik metraj ve 100 poz: 300 aday, **100 compatible / 200 blocked**, **0 otomatik mühendis onayı**.
- Tek satırın gerçek kodunun da en yüksek 3 aday arasında yer aldığı ayrıca doğrulanır.
- Normal, bu sentetik namespace'e ait olmayan katalogların eski davranışı korunur.
- M5'te ancak doğru adaylara uzman kararı verildikten sonra fiyatlandırmaya geçilir.

## Operasyon
Yeni \`feat/m4-3-1-position-identity-guard\` dalını alıp sunucuları ve Worker'ı **aynı dalın koduyla** yeniden başlat. Önceden M4.3 ile tamamlanan rapora karar verme. R01 için aynı onaylı 100 poz kataloğuyla **yeni bir M4.3 işi** oluştur; Worker'ı çalıştır, M4.2'de yeni kanıtta 100 uyumlu / 200 engelli gör. Mühendis kararları kesinlikle otomatik verilmez. Migration gerekmiyor.
