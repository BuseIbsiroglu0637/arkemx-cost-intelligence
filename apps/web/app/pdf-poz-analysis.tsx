"use client";

import { useEffect, useState, type FormEvent } from "react";
import styles from "./pdf-poz-library.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type AnalysisSource = {
  present: boolean; read_only: true; approval_allowed: false; cost_allowed: false;
  source_sha256?: string; edition_date?: string; pdf_pages?: number; position_count?: number;
  audit?: {
    headers_detected: number; positions_extracted: number; unparsed_header_count: number;
    analysis_price_reconciled_count: number; analysis_price_needs_review_count: number;
    parameterized_formula_count?: number; missing_analysis_title_count?: number;
  };
};
type Input = {
  code: string; description: string; unit: string;
  quantity: string | null; unit_price: string | null; amount: string | null;
};
type Analysis = {
  code: string; description: string; unit: string; analysis_price: string | null;
  analysis_kind?: "fixed_price" | "parameterized_formula";
  description_status?: "from_analysis_pdf" | "blank_pdf_title";
  formula?: string | null;
  formula_parameters?: {M: string; H: null; K: null} | null;
  analysis_price_reconciled: boolean; pdf_page: number;
  scope: string; inputs: Input[]; cost_allowed: false;
  analysis_audit: null | {
    inputs_total: string; reconciliation_addition_percent: number;
    reconciliation_addition: string; calculated_price: string; pdf_price: string;
    difference: string; status: string;
  };
};
type Detail = {
  code: string; available: boolean; reason: string | null;
  read_only: true; approval_allowed: false; cost_allowed: false;
  price_list_sha256: string; analysis_source_sha256: string | null;
  list_price: string | null; list_unit: string | null; price_list_pdf_page: number;
  analysis: Analysis | null; list_analysis_price_equal?: boolean | null;
};

const checkSafety = (source: {read_only: boolean; approval_allowed: boolean; cost_allowed: boolean}) =>
  source.read_only === true && source.approval_allowed === false && source.cost_allowed === false;

const money = (value: string | null | undefined) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? "—" : Number(value).toLocaleString("tr-TR", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " TL";

async function failure(res: Response): Promise<string> {
  const data = await res.json().catch(() => null) as {detail?: unknown} | null;
  return typeof data?.detail === "string" ? data.detail : "HTTP " + res.status + " · Analiz PDF isteği başarısız.";
}

export function PdfAnalysisSource({ token, onChange }: {token: string; onChange: () => void}) {
  const [source, setSource] = useState<AnalysisSource | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void fetch(API + "/api/a348/catalog/analysis/source", {
      headers: {Authorization: "Bearer " + token}, cache: "no-store", signal: controller.signal,
    }).then(async res => {
      if (!res.ok) throw Error(await failure(res));
      return await res.json() as AnalysisSource;
    }).then(data => {
      if (controller.signal.aborted) return;
      if (!checkSafety(data)) throw Error("Analiz kaynağı yalnız okunabilir olmalıdır.");
      setSource(data);
    }).catch(err => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Analiz kaynağı okunamadı.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refresh]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy) return;
    if (!file.name.toLocaleLowerCase("tr-TR").endsWith(".pdf")) {
      setError("Lütfen Analizler Cilt 1 PDF dosyasını seç."); return;
    }
    setBusy(true); setError("");
    const payload = new FormData();
    payload.append("file", file);
    try {
      const res = await fetch(API + "/api/a348/catalog/analysis/source", {
        method: "POST", headers: {Authorization: "Bearer " + token},
        cache: "no-store", body: payload,
      });
      if (!res.ok) throw Error(await failure(res));
      const data = await res.json() as AnalysisSource;
      if (!checkSafety(data) || !data.present || !data.source_sha256) {
        throw Error("Analiz kaynağı doğrulanamadı.");
      }
      setSource(data); setFile(null); setRefresh(n => n + 1); onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analiz PDF yüklenemedi.");
    } finally { setBusy(false); }
  }

  // The user has already taught ARKEMX this catalog. Do not ask for it
  // again or clutter the poz library with upload/update controls.
  if (loading || (source?.present && !error)) return null;

  return <section className={styles.analysisSource} aria-label="İlk analiz PDF kurulumu">
    <strong>Analiz PDF'si henüz kaydedilmemiş</strong>
    <p>Bir kez yükledikten sonra program yeniden açıldığında otomatik kullanılacak.</p>
    <form onSubmit={event => void upload(event)}>
      <input type="file" accept=".pdf,application/pdf"
        aria-label="2026 İnşaat Birim Fiyat Analizleri Cilt 1"
        onChange={event => setFile(event.target.files?.[0] ?? null)}/>
      <button type="submit" disabled={busy || !file}>
        {busy ? "Analizler kaydediliyor…" : "Analiz PDF'sini ilk kez yükle"}
      </button>
    </form>
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </section>;
}

export function PdfAnalysisDetail({token, code, priceListSourceSha, revision}: {
  token: string; code: string | null; priceListSourceSha: string | null; revision: number;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!code || !priceListSourceSha || !/^15\.\d{3}\.\d{4}$/.test(code)) {
      setDetail(null); setLoading(false); setError(""); return;
    }
    const controller = new AbortController();
    setLoading(true); setError(""); setDetail(null);
    void fetch(API + "/api/a348/catalog/positions/" + encodeURIComponent(code) + "/analysis", {
      headers: {Authorization: "Bearer " + token}, cache: "no-store", signal: controller.signal,
    }).then(async res => {
      if (!res.ok) throw Error(await failure(res));
      return await res.json() as Detail;
    }).then(data => {
      if (controller.signal.aborted) return;
      if (!checkSafety(data) || data.code !== code ||
          data.price_list_sha256 !== priceListSourceSha ||
          (data.analysis && data.analysis.cost_allowed !== false)) {
        throw Error("Analiz ve fiyat listesi kaynakları uyuşmuyor.");
      }
      setDetail(data);
    }).catch(err => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Poz analizi okunamadı.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, code, priceListSourceSha, revision]);

  if (!code) return null;
  if (!/^15\.\d{3}\.\d{4}$/.test(code)) {
    return <div className={styles.analysisDetail}><strong>Detaylı analiz</strong>
      <p>Bu Cilt 1 PDF'si inşaat analizlerini içerir. Bu poz grubu için ayrı analiz kaynağı gerekir.</p>
    </div>;
  }
  return <section className={styles.analysisDetail} aria-label="Seçilen pozun detaylı PDF analizi">
    <strong>Detaylı analiz · Cilt 1</strong>
    {loading && <p role="status">Pozun analizi aranıyor…</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {detail && !detail.available && <p>
      {detail.reason === "analysis_pdf_not_uploaded" ?
        "Analiz PDF'si henüz yüklenmedi." :
        "Bu pozun analizi Cilt 1'de bulunamadı veya PDF okuyucu tarafından ayrıştırılamadı."}
    </p>}
    {detail?.available && detail.analysis && <>
      {detail.analysis.analysis_kind === "parameterized_formula" ? <>
        <p className={styles.analysisPrice}><b>Bu poz sabit fiyatlı değil, formülle hesaplanır.</b></p>
        <p>PDF formülü: <b>{detail.analysis.formula}</b></p>
        <p>M: {detail.analysis.formula_parameters?.M ?? "—"} · H: proje kazı derinliği ·
          K: düz işçi saat ücreti. Bu değerler olmadan TL fiyatı hesaplanmaz.</p>
      </> : <p className={styles.analysisPrice}>Analiz PDF fiyatı: <b>{money(detail.analysis.analysis_price)}</b></p>}
      {detail.analysis.description_status === "blank_pdf_title" && <p>
        Analiz PDF'sinde poz başlığı boş; açıklama fiyat listesi kaynağından gösteriliyor.
      </p>}
      <p>PDF sayfa: <b>{detail.analysis.pdf_page}</b> · Birim: <b>{detail.analysis.unit || "—"}</b></p>
      <p>{detail.analysis.analysis_kind === "parameterized_formula" ?
        "Formül sonucu proje parametreleri olmadan fiyatla karşılaştırılmaz." :
        detail.list_analysis_price_equal === true ? "Liste ve analiz fiyatı eşit." :
        detail.list_analysis_price_equal === false ? "Liste ve analiz fiyatı farklı; kaynak kontrolü gerekli." :
        "Liste fiyatı olmadığı için fiyatlar karşılaştırılamadı."}</p>
      <p>{detail.analysis.analysis_kind === "parameterized_formula" ?
        "Değişkenli fiyat hesabı; mühendislik ve proje verileri gerekiyor." :
        detail.analysis.analysis_price_reconciled ?
        "Analiz girdileri ve PDF toplamı mevcut ayrıştırma kuralıyla tutarlı." :
        "Analiz girdileri / toplamı ayrıca kontrol edilmeli; otomatik doğrulanmış sayılmaz."}</p>
      {detail.analysis.inputs.length > 0 && <details>
        <summary>Malzeme ve işçilik girdileri ({detail.analysis.inputs.length})</summary>
        <div className={styles.analysisTableWrap}>
          <table>
            <thead><tr><th>Girdi poz</th><th>Açıklama</th><th>Birim</th><th>Miktar</th><th>Birim fiyat</th><th>Tutar</th></tr></thead>
            <tbody>{detail.analysis.inputs.map((entry, i) => <tr key={entry.code + "-" + i}>
              <td>{entry.code}</td><td>{entry.description}</td><td>{entry.unit}</td>
              <td>{entry.quantity ?? "—"}</td><td>{entry.unit_price ?? "—"}</td><td>{entry.amount ?? "—"}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </details>}
      {detail.analysis.analysis_audit && <details>
        <summary>Analiz hesabı</summary>
        <p>Girdi toplamı: {money(detail.analysis.analysis_audit.inputs_total)} ·
          Kâr ve genel giderler (%{detail.analysis.analysis_audit.reconciliation_addition_percent}):
          {" "}{money(detail.analysis.analysis_audit.reconciliation_addition)}</p>
        <p>Hesaplanan: {money(detail.analysis.analysis_audit.calculated_price)} ·
          PDF: {money(detail.analysis.analysis_audit.pdf_price)}</p>
      </details>}
      {detail.analysis.scope && <details>
        <summary>PDF'deki teknik tarif / ölçü bilgisi</summary>
        <p className={styles.analysisScope}>{detail.analysis.scope}</p>
      </details>}
      <small>Analiz kaynağı: {detail.analysis_source_sha256?.slice(0, 12)}…</small>
    </>}
    <small>Bu bağlantı sadece iki PDF'deki aynı poz numarasını birleştirir; teknik onay veya maliyet hesabı değildir.</small>
  </section>;
}


type LinkageAudit = {
  ready: boolean; read_only: true; approval_allowed: false; cost_allowed: false;
  price_list_present: boolean; analysis_present: boolean;
  price_list_sha256?: string; analysis_source_sha256?: string;
  catalog_total: number; analysis_total: number; linked_count: number;
  catalog_without_cilt1_analysis_count?: number;
  analyses_without_catalog_code_count?: number;
  linked_without_list_price_count?: number; linked_price_difference_count?: number;
  example_link?: string | null;
  linked_formula_only_count?: number;
  analyses_without_catalog_code_sample?: string[];
};

export function PdfLinkageAudit({token, priceListSha, revision}: {
  token: string; priceListSha: string | null; revision: number;
}) {
  const [audit, setAudit] = useState<LinkageAudit | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setAudit(null); setError(""); setLoading(true);
    void fetch(API + "/api/a348/catalog/linkage", {
      headers: {Authorization: "Bearer " + token},
      cache: "no-store", signal: controller.signal,
    }).then(async res => {
      if (!res.ok) throw Error(await failure(res));
      return await res.json() as LinkageAudit;
    }).then(data => {
      if (controller.signal.aborted) return;
      if (!checkSafety(data) || data.price_list_present !== Boolean(priceListSha) ||
          (priceListSha && data.price_list_sha256 && data.price_list_sha256 !== priceListSha)) {
        throw Error("PDF kaynakları değişti; bağlantı denetimi yenilenmeli.");
      }
      setAudit(data);
    }).catch(err => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "PDF bağlantıları kontrol edilemedi.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, priceListSha, revision]);

  return <section className={styles.linkageAudit} aria-label="İki PDF arası bağlantı kontrolü">
    <strong>İki PDF'nin gerçek bağlantı sonucu</strong>
    {loading && <p role="status">Poz numaraları karşılaştırılıyor…</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {audit && !audit.ready && <p>
      Bağlantı kontrolü için hem fiyat listesi hem analiz PDF'si yüklenmiş olmalı.
    </p>}
    {audit?.ready && <>
      <div className={styles.linkStats}>
        <span>Fiyat listesi: <b>{audit.catalog_total.toLocaleString("tr-TR")}</b></span>
        <span>Analiz Cilt 1: <b>{audit.analysis_total.toLocaleString("tr-TR")}</b></span>
        <span>Gerçekten bağlanan: <b>{audit.linked_count.toLocaleString("tr-TR")}</b></span>
      </div>
      <p>
        Cilt 1 analizi bulunmayan liste kayıtları: {audit.catalog_without_cilt1_analysis_count?.toLocaleString("tr-TR")} ·
        Fiyat listesinde kodu olmayan analiz: {audit.analyses_without_catalog_code_count?.toLocaleString("tr-TR")} ·
        Fiyatı farklı bağlı poz: {audit.linked_price_difference_count?.toLocaleString("tr-TR")}
        {audit.linked_formula_only_count ? " · Formülle hesaplanan: " + audit.linked_formula_only_count : ""}
      </p>
      {!!audit.analyses_without_catalog_code_sample?.length && <p>
        Analiz PDF'sinde olup fiyat listesinde bulunmayan kodlar:
        {" "}{audit.analyses_without_catalog_code_sample.join(", ")}.
        Bunlar otomatik olarak yeni resmî fiyat pozuna dönüştürülmez.
      </p>}
      <small>Yalnız birebir poz numarası bağlantısı sayılır; teknik onay anlamına gelmez.</small>
    </>}
  </section>;
}
