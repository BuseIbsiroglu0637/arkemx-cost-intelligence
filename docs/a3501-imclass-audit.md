# A3.50.1 — İmalat sınıflandırması ve ölçülebilir kapsama

## Ne yapıldı?

Kaydedilmiş Excel metrajındaki iş açıklamaları ile **kalıcı 2026 ÇŞİDB resmî fiyat listesi** aynı kaynak-odaklı imalat sözlüğünde sınıflandırılır. **Poz katalog PDF'si, Cilt 1 analizleri, özgün Excel, onaylar ve maliyet verileri değiştirilmez.** Yeni bir model eğitilmedi ve hiçbir mühendislik poz kararı otomatik verilmez.

Örnek iş nesnesi sınıfları: `gazbeton_wall`, `brick_wall`, `ceramic_surface`, `pvc_floor`, `pvc_profile`, `pvc_pipework`, `pvc_joinery`, `plaster_cement`, `plaster_gypsum`, `plaster_generic`, `cement_surface_coating`, `plumbing_tap`, `waterproofing`, `thermal_insulation`, `paint`, `electrical_work`, `hvac_work`, `unknown`, `multiple`.

Önemli ayrımlar: **seramik musluk kaplama değildir**; **PVC ekstrüde profil, PVC zemin döşemesi değildir**; **marka adı tek başına malzeme türünü kanıtlamaz**; sıva/beton *üzerine yapılan çimento kaplama*, yeni sıva imalatı değildir. Çoklu imalat ve bilinmeyen nesne türü kaynakla kanıtlanmadan doğru aday sayılmaz.

## Kontrol ekranı

Metraj → **Metraj açıklamalarını yorumla** panelini aç. Kaydedilmiş Excel importunu seç ve yeni **İmalat sınıflandırma raporu** bölümünü genişlet. **İmalatları sınıflandır** düğmesine bas.

Ekran **seçili Excel kaynağındaki tüm satırların** sayısını, imalat türü belirlenebilenleri, insan kontrolü gerektirenleri, en çok görülen sınıfları ve kaynaklı örnekleri gösterir. Aynı düğme PDF 2026 pozlarının da sınıf/rol dağılımını hesaplar. 408 veya 20.315 sayıları HTML'ye yazılmamıştır: ilgili kayıtlar gerçekten varsa görünür.

Rapor yalnız **sınıflandırma kapsamasını** ölçer. Bulunan pozun doğru olma olasılığı, ilk üçte eşleşme doğruluğu veya mühendis onayı değildir. Bu değerleri değerlendirmek için uzman tarafından kontrol edilmiş 30–50 satırlık altın test kümesi gereklidir.

## Poz adaylarını nasıl değiştirir?

Eski arama tüm 20.315 PDF satırı arasında ortak kelimelere göre öne seçme yapıyordu. Yeni arama önce aynı imalat sınıfını daraltır; diğer sınıflardan en çok 20 adayı yalnızca **neden elendiğini göstermek amacıyla** inceler.

Kaynağı açıklanmayan sınıf `PDF_WORK_CLASS_UNVERIFIED`, farklı iş sınıfı `WORK_CLASS_MISMATCH`, Excel'de iş sınıfı belirlenememesi `EXCEL_WORK_CLASS_UNVERIFIED` olarak işaretlenir. Önceki teknik kalınlık/birim/malzeme/iş kapsamı engelleri korunur. Otomatik poz seçimi, fiyat hesabı ve mühendis onayı yoktur.

API uçları:

- `GET /api/a350/catalog/classification` — mevcut oturumun firmasına ait PDF kütüphanesinin tüm pozlarını sınıflandırıp gruplar ve 15 kontrol örneğiyle özetler.
- `GET /api/projects/{project_id}/a350/imports/{import_id}/classification?offset=0&limit=20` — yetkili Excel'in bütün satırlarında sınıflandırma sayıları, 20'şer satır ve 12 örnek. Güncel metraj revizyonları okunur.
- Eski `GET /api/projects/{project_id}/a349/imports/{import_id}/items/{work_item_id}/candidates` — şimdi `a3501-class-first-v1` sürümü ve Excel/PDF iş sınıflarıyla birlikte yanıtlar.

## Windows çalışma ve veri koruma

API/web için mevcut terminalde çalışan sunucuları `Ctrl+C` ile kapat. Komutları yeni çalışma dalından çalıştır; *aynı test DB ve kalıcı `%LOCALAPPDATA%\ARKEMX\catalogs`* korunur. PDF'leri tekrar yükleme.

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483
git fetch https://github.com/BuseIbsiroglu0637/arkemx-cost-intelligence.git refs/heads/feat/a3501-work-classification-audit
git switch -c feat/a3501-work-classification-audit FETCH_HEAD
```

API — port **8000**:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\services\cost-api
$env:DATABASE_URL = 'sqlite:///C:/Users/busei/arkemx-dev/arkemx-a3482-runtime/arkemx-a3482-test.db'
$env:UPLOAD_DIR = 'C:\Users\busei\arkemx-dev\arkemx-a3482-runtime\uploads'
$env:CORS_ORIGINS = 'http://127.0.0.1:3000,http://localhost:3000'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Web — ayrı PowerShell, port **3000**:

```powershell
cd C:\Users\busei\arkemx-dev\arkemx-a3483\apps\web
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8000'
npm run dev -- --port 3000
```

Tarayıcıda `http://127.0.0.1:3000/#metraj` → ilgili projenin kayıtlı Excel'i → Metraj açıklamalarını yorumla → İmalat sınıflandırma raporu → İmalatları sınıflandır.

## Sonraki geliştirme

Gerçek import raporundaki bilinemeyen sınıfların sebeplerini inceleyip, 30–50 **uzman doğrulamalı** örnek üzerinde test yapın. Ardından A3.50.2'de sınıf filtreli TF-IDF/BM25/çok dilli embedding aramalarını karşılaştırın. Semantik aramaya geçildiği veya 408 satırın doğru eşleştiği bu adımın sonucu değildir.
