# M2 — AI Poz Eşleştirme Motoru (geliştirici pilotu)

**Hedef:** M1'de yüklenmiş metraj cetveline kaynaklı ve denetlenebilir poz adayları üretmek, riskli sonuçları onaylatmamak ve insan kararını kalıcı kayıt olarak tutmak.

## Çalışma koşulları

- M1 metraj ve kullanıcı oturumu gereklidir; aynı SQLite veritabanı kullanılabilir.
- Önce migration: `cd services/cost-api && python -m alembic upgrade head`
- Frontend: `cd apps/web && npm run dev`.
- Projeyi seç, aşağıdaki M2 panelindeki **Sentetik katalogla poz önerilerini oluştur** butonuna bas.
- Motor yalnızca beş adet kendi oluşturduğumuz **DEMO-** pozuyla çalışır. Kamu birim fiyatları, Bakanlık pozları, lisanslı katalog indirme ve gerçek AI karar doğrulaması yoktur.
- Her satır için en fazla 3 aday; malzeme ailesi, kalınlık, ebat, birim ve M1 metraj uyarıları kontrol edilir.
- Yalnızca teknik uyarısız sonuç **Mühendis onayı** alabilir. Reddedilen ve onaylanan kararlar `match_decisions` tablosuna yeni kayıt olarak eklenir; geçmiş silinmez.
- Benzerlik puanı, sözcük/karakter örtüşmesini ölçer; **% doğruluk**, mevzuat uyumu veya gerçek fiyat bilgisi değildir.
- Metraj dosyası ve katalog versiyonu her çalıştırma için sabitlenir; sonraki dosya yüklemesi eski sonuçları değiştirmez.

## Sıfır ücretli mod

Varsayılan eşleştirme, çevrimdışı **lexical-gated-v0.2** metin benzerliği + deterministik teknik kontrollerle çalışır. Haricî AI API'sine veri göndermez.

**Gerçek yerel LLM ile yardımcı sıralama** istenirse: Windows üzerinde Ollama çalıştır; kurulu modele göre `M2_OLLAMA_MODEL` ortam değişkenini örneğin `qwen3.5:4b` yap ve hem API'yi yeniden başlat hem de arayüzde **Yerel Ollama** kutusunu seç. Önceden getirilen aday kodlarını yalnızca yeniden sıralayabilir; teknik engelleri kaldıramaz, yeni poz/fiyat uyduramaz. Yalnızca `127.0.0.1:11434` adresine bağlanır. Model bulunamaz/yanıt vermezse çevrimdışı sıralamaya döner. Ücretsiz yerel model de donanım belleği/işlemci tüketir.

## API

| Yöntem | Adres | İşlem |
|---|---|---|
| POST | `/api/m2/demo-catalog` | Organizasyon için sentetik katalog oluştur (idempotent) |
| POST | `/api/projects/{project_id}/m2/run` | Son M1 importunu eşleştir (en çok 100 satır) |
| GET | `/api/projects/{project_id}/m2/latest` | Son çalıştırmanın öneri ve kararlarını görüntüle |
| POST | `/api/projects/{project_id}/m2/decisions` | Adayı onayla/reddet, denetim kaydı oluştur |

## Kabul kapıları

- [ ] Yeni migration SQLite üzerinde geçti
- [ ] Yeni migration PostgreSQL üzerinde geçti
- [ ] `pytest` M1 + M2 testleri geçti
- [ ] Web `npm run typecheck` ve `npm run build` geçti
- [ ] M1 örnek Excel: seramik, gazbeton, beton, kapı ve boya için test raporu alındı
- [ ] `1.234` belirsiz gazbeton kalemi **onaylanamıyor**
- [ ] `kutu` birimli boya kalemi **onaylanamıyor**
- [ ] Diğer organizasyonun eşleştirmeleri ve kararları **erişilemez**
- [ ] Dosya yenilendiğinde tarihî eşleştirme aynı importu göstermeye devam ediyor
- [ ] Yapay zekâ uydurma poz kodu veya fiyat üretmiyor

## Sınırlamalar

Ürün henüz müşteri verisiyle internete açılmamalı. Önce ticari poz kullanım hakları, güvenli oturum, kota/saldırı kontrolleri, üretim veritabanı, eşleştirme doğruluk test seti (>=300 etiketli kalem), model değerlendirmesi, fiyat sürümleme ve mühendis onayı iş akışı tamamlanmalı. M2 kapsamına **yaklaşık maliyet ve gerçek poz içe aktarma dahil değildir**.
