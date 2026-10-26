# M4.2.1 — Kontrollü seri mühendis inceleme (ilk pilot)

## Amaç
M512-100-SENTETIK senaryosunda M4.3.1 sonrası 100 teknik uyumlu aday ve 200 engelli aday oluşur. M4.2.1, 100 adayı tek tek kanıtla incelemeyi kolaylaştırır. 100 karar tek tıkla otomatik verilmez.

## UI işlemi
1. M4.2'de **Kontrollü seri incelemeyi aç** düğmesine bas.
2. İnceleme görünümü yalnızca **compatible + undecided** adaylara ve 10 satırlık sayfaya geçer. Engelli adaylar bu listeye alınamaz.
3. **Kanıt ve karar** içinde C25/30, nakliye, \`fixture_item_identity\` ve SHA-256'yı oku.
4. Adayın kendine özgü 10–500 karakterlik inceleme gerekçesini yaz; incelemeyi onayla; **İncelediğim adayı listeye ekle**.
5. En fazla 10 incelenmiş aday birikir. İstersen herhangi birini kaydetmeden kaldırabilirsin.
6. Son listeyi okuyup açık onay kutusunu işaretle, ardından kararları sırayla kaydet.
7. Her aday için backend **tekrar** güncel proje, kanıt SHA, rights, teknik kapsam, kimlik ve stale durumunu denetler. Her işlem mevcut M2'nin kendi karar geçmişine tekil "approve" olayı ekler. Biri reddedilirse durur ve önceki başarıları ayrı sayar.

## Güvenlik ve kapsam
- Sunucunun \`/api/projects/{project_id}/m42/controlled-decisions\` endpoint'i tek çağrıda **sadece bir aday** kabul eder.
- M2 kararı ve SHA-256 doğrulaması atlanmaz; önceki kararları silmez.
- Eski çalışmalar, onay engelli adaylar, başka tenant ve değişmiş kanıt reddedilir.
- Aynı adayın mevcut kararını tekrar yazmaz; yeniden değerlendirme gerekiyorsa M4.2 normal karar ekranı kullanılır.
- Gerçek mühendislik yetkisi veya hukukî imza otomatik doğrulanmış sayılmaz: mevcut ürün pilotu giriş yapan kullanıcıya dayanır.
- Sistemin kullanılabilirliği ve UI performansı 100 satırlık Windows yerel deneyimiyle doğrulanmalıdır.
