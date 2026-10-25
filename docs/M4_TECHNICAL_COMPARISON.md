# M4 — Akıllı Teknik Poz Karşılaştırma (v0.1 pilot)

**Amaç:** M2/M3 kelime benzerliğini teknik uyumlulukla karıştırmadan, her aday için açıklanabilir ve kaynağı belirli bir teknik değerlendirme üretmek.

## Nasıl çalışır?

- Kullanıcı mevcut M2 veya M3 eşleştirmesini oluşturur. Ardından M4 panelinden **Teknik karşılaştırmayı çalıştır** der.
- M4 son çalışmanın **aynı katalog sürümünü** ve son metraj dosyasının etkin revizyonlarını kullanır. İzin geri çekilmiş gerçek kataloglarda çalışmaz.
- Yalnızca katalogdaki pozlar aday olur; kod, fiyat, kaynak ve teknik özellik uydurulmaz. En fazla 500 katalog pozu ve 100 metraj kalemi (pilot sınırı).
- Önce yalnızca kelime benzerliği >= 0.18 olan adaylar alınır, her kalemde en yüksek ilk üç adayın teknik özellikleri kontrol edilir. Bu eşik bir doğruluk garantisi değildir ve arama kapsamını sınırlar.
- Her özellik için metraj ve poz tarifi yan yana gösterilir: **malzeme, yüzey, yöntem, iç/dış ortam, kalınlık (mm), ebat ve birim**.
- *blocked*: tespit edilen teknik çelişki veya eksik/hatalı metraj. Mühendis onayı engellenir.
- *review*: kritik bilgi yalnızca bir tarafta var ya da iki tarafta da gerekli bilgi eksik. Otomatik uyum ilan edilmez; bu pilotta doğrudan onay engellenir.
- *compatible*: sadece v0.1 kurallarının görebildiği özellikler uyumludur. **Hâlâ mühendis onayı gerekir.** Tam poz şartnamesi uyumu veya hukukî doğruluk göstermez.
- M4 çalışması ayrı `match_run` olarak saklanır, teknik kanıtları `technical_comparisons` tablosunda aday kimliğine bağlanır; eski M3 koşu ve onayları değişmez.
- Yeni metraj düzeltildiyse M4 baştan çalıştırılmalıdır; M2.1'in kısmi aday kopyalama yolu M4 teknik kanıtları için kapatılmıştır.
- Teknik engelli sonuçlar, metin benzerliği 1.00 olsa bile M4'te onaylanamaz.

## Bağımsız test veri seti

`app/m4_quality.py` yalnızca **tamamen kurgusal 16 ikili** içerir. `GET /api/m4/quality` endpoint'i `precision`, `recall`, `false_positive`, `false_negative` döndürür. Bu metrikler **üretim doğruluğu olarak yayımlanamaz**: gerçek iş kalemleri ve uzman etiketleriyle bağımsız ve stratifiye bir test veri seti gerekli (ilk hedef en az 300 çift; farklı malzeme, kurum, yıl, ebat, metraj biçimleri ve kapsam).

## Yerel sıfır ücretli çalışma

```powershell
# API ve web sunucularını Ctrl+C ile durdur
cd "$HOME\arkemx-dev\arkemx-cost-intelligence"
git status --short
git fetch origin "refs/heads/feat/m4-technical-comparison:refs/remotes/origin/feat/m4-technical-comparison"
git switch --no-track -c feat/m4-technical-comparison refs/remotes/origin/feat/m4-technical-comparison

cd services\cost-api
Copy-Item .\arkemx-dev.db ".\arkemx-dev-before-m4-$(Get-Date -Format 'yyyyMMdd-HHmmss').db" -ErrorAction Stop
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Beklenen Alembic sürümü: `0005_m4_comparison (head)`.

İkinci PowerShell:

```powershell
cd "$HOME\arkemx-dev\arkemx-cost-intelligence\apps\web"
npm run typecheck
npm run dev
```

## M4 kabul senaryosu

1. Mevcut `DEMO-2026-TEST` onaylı katalogla M3 eşleştirmesini başlat. İptal edilen `DEMO-2026-REVOKE-TEST` kataloğunu **kullanma**.
2. M4 kartındaki **Teknik karşılaştırmayı çalıştır** butonuna bas. Beş kalem için rapor üret; eski mühendis onayları tarihî çalışmada korunmalı, yenisine aktarılmamalı.
3. Teknik özellikleri yan yana karşılaştır. Metrikler yalnızca sentetik test çifti için.
4. Kritik kalınlık farkı testi: `gazbeton duvar 10 cm` ve `gazbeton duvar 15 cm` M4 kararı **blocked** olmalı.
5. Eksik yüzey testi: `porselen seramik kaplama 60x60` ve `porselen seramik zemin kaplama 60x60` M4 kararı **review** olmalı; otomatik onaylanmamalı.
6. **compatible** sonuçta dahi mühendis onayı ayrı işlem olmalı. İzin iptali sonrasında M4 de kaynak kullanımını reddetmeli.
7. `F5` sonrasında teknik rapor kaybolmamalı.

## API ve tablolar

- `POST /api/projects/{project_id}/m4/run`: Son M2/M3 kataloğuyla yeni teknik analiz, sıralama ve dondurulmuş teknik kanıt.
- `GET /api/projects/{project_id}/m4/latest`: M4 son koşusunun kanıtları; diğer firma erişimi reddedilir.
- `GET /api/m4/quality`: Bağımsız **sentetik** mini-fixture karşılaştırma istatistikleri.
- `technical_comparisons`: Aday ID, kural sürümü, durum, JSON kanıt, oluşturma zamanı.

## Sınırlar / üretime geçiş kapısı

- Kurum teknik şartnameleri, poz alt analizleri, kapsam notları ve yeni yıl/poz revizyonları v0.1 ayrıştırıcısında yoktur.
- Türkçe dil varyantları, kısaltmalar, mm/cm ebat standartları ve kompleks imalat kombinasyonları için uzman doğrulaması gerekir.
- Lokal Ollama M2 sıralamasında opsiyonel yardımcıdır; M4 deterministik denetimlerinin yerine geçmez.
- Tam metin arama, embedding veya öğrenen model için kullanıcının yükleme hakları ve KVKK veri sınırları ayrıca ele alınmalıdır.
- Üretim için PostgreSQL testleri, yetki/kota, tanımlı kaynak kullanım hakları, ölçülmüş gerçek örneklerde precision/recall, güvenlik incelemesi ve uzman denetimi zorunludur.
