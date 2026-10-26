# M4.2.2 — Kontrollü inceleme UX ve karar gerekçesi

Kapsam: \`M512-100-SENTETIK\`, mevcut M4.2.1 panelinin kullanım güvenliği.

1. **Onay kutusu:** Global \`input{width:100%}\` checkbox'ları da büyütüyordu. Scoped CSS ile 18×18 piksel ve yan yana açıklama; dar ekranda satır kırılır. Önceki görünümde sağa taşma böyle giderilir.
2. **Gerekçe:** Eski kontrol sadece 10 karakterdi, \`...........\` gibi sahte gerekçe kayıt edilebiliyordu. Yeni \`decision_reason.py\` hem tekli M2 kararı hem M4.2.1 seri karar için ortak doğrulama yapar. En az 12 harf ve birbirinden farklı en az 3 (üç veya daha uzun) kelime, önceden bilinen placeholder metinleri reddetme. UI da bunu açıkça gösterir. Bu yalnızca asgari biçimsel kontrol sağlar; gerçek mühendislik kanıt değerlendirmesinin yerine geçmez.
3. **Güncel/tarihî:** M4.2 özetinde yalnız **son run** kararları açıkça belirtilir. Her adayda güncel çalışma kararları ayrı, önceki M4.3 çalışması kararları kapalı bir tarihî denetim bölümündedir. Tarihî onaylar yeni çalışmaya otomatik aktarılmaz.

Değişmeyenler: veritabanı şeması, tarihî gerekçeler, önceki mühendis kararları, metraj ve maliyet taslakları. Anlamsız gerekçe içeren eski kararlar bile denetim geçmişinden silinmez. Yeni testler backend'de saklama/ret ve geçmiş filtreleme kontratını kapsar. CSS görsel kabulü **yerel Windows tarayıcısında** ayrıca yapılmalıdır.

Önemli: Bu geliştirme temel olarak PR #16 → PR #15 → PR #14 üzerine kuruludur. Ana dala doğrudan rastgele merge yapmayın. UI ve gerekçe doğrulamasını yerelde doğrulayarak ilerleyin.
