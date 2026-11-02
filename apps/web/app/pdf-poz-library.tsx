"use client";

import { useEffect, useState, type FormEvent } from "react";
import styles from "./pdf-poz-library.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const labels: Record<string, string> = {
  all: "Tüm gruplar",
  rayic: "Rayiçler (10.*)",
  insaat: "İnşaat imalatları (15.*)",
  mekanik: "Mekanik tesisat (25.*)",
  elektrik: "Elektrik tesisatı (35.*)",
};

type SourceSummary = {
  present: boolean;
  read_only: true; approval_allowed: false; cost_allowed: false;
  source_sha256?: string; edition_date?: string; pdf_pages?: number;
  total_records?: number;
  audit?: {
    codes_seen: number; records_extracted: number; unparsed_count: number;
    unpriced_count: number; price_cells_extracted: number;
    ambiguous_price_count: number; duplicate_code_count: number;
    by_kind: Record<string, number>;
  };
};
type PdfPosition = {
  code: string; description: string; kind: string;
  unit: string | null; unit_price: string | null;
  installation_price: string | null;
  price_status: string; pdf_page: number; cost_allowed: false;
  parent_code: string | null; parent_description: string | null;
  unit_hint: string | null;
};
type Results = {
  read_only: true; approval_allowed: false; cost_allowed: false;
  source_sha256: string; total: number; page: number; page_size: number;
  items: PdfPosition[];
};
const trNumber = (value: number) => value.toLocaleString("tr-TR");
const priceLabel = (value: string | null) =>
  value !== null && Number.isFinite(Number(value))
    ? Number(value).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " TL"
    : "—";

async function decodeError(response: Response): Promise<string> {
  const data = await response.json().catch(() => null) as {detail?: unknown} | null;
  return typeof data?.detail === "string" ? data.detail :
    "Kaynak okunamadı (HTTP " + response.status + ").";
}

export default function PdfPozLibrary({ token }: {token: string}) {
  const [source, setSource] = useState<SourceSummary | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [loadingSource, setLoadingSource] = useState(true);
  const [sourceError, setSourceError] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [page, setPage] = useState(1);
  const [results, setResults] = useState<Results | null>(null);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsError, setRowsError] = useState("");
  const [selected, setSelected] = useState<PdfPosition | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingSource(true); setSourceError("");
    void fetch(API + "/api/a348/catalog/source", {
      cache: "no-store", signal: controller.signal,
      headers: { Authorization: "Bearer " + token },
    }).then(async res => {
      if (!res.ok) throw Error(await decodeError(res));
      return await res.json() as SourceSummary;
    }).then(data => {
      if (controller.signal.aborted) return;
      if (data.read_only !== true || data.approval_allowed !== false ||
        data.cost_allowed !== false) throw Error("Poz kütüphanesi salt okunur değil.");
      setSource(data);
    }).catch(error => {
      if (!controller.signal.aborted) setSourceError(error instanceof Error ? error.message : "Kaynak yüklenemedi.");
    }).finally(() => { if (!controller.signal.aborted) setLoadingSource(false); });
    return () => controller.abort();
  }, [token, refresh]);

  useEffect(() => {
    if (!source?.present || !source.source_sha256) {
      setResults(null); setRowsLoading(false);
      return;
    }
    const controller = new AbortController();
    const expectedSha = source.source_sha256;
    setRowsLoading(true); setRowsError("");
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ q: query, kind, page: String(page), page_size: "40" });
      void fetch(API + "/api/a348/catalog/positions?" + params, {
        cache: "no-store", signal: controller.signal,
        headers: { Authorization: "Bearer " + token },
      }).then(async res => {
        if (!res.ok) throw Error(await decodeError(res));
        return await res.json() as Results;
      }).then(data => {
        if (controller.signal.aborted) return;
        if (data.read_only !== true || data.approval_allowed !== false ||
          data.cost_allowed !== false || data.source_sha256 !== expectedSha ||
          data.page !== page || data.items.length > data.page_size ||
          data.items.some(record => record.cost_allowed !== false)) {
          throw Error("Katalog kaynağı veya sonuçları doğrulanamadı.");
        }
        setResults(data);
      }).catch(error => {
        if (!controller.signal.aborted) setRowsError(error instanceof Error ? error.message : "Poz listesi yüklenemedi.");
      }).finally(() => {
        if (!controller.signal.aborted) setRowsLoading(false);
      });
    }, query ? 250 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [token, source?.present, source?.source_sha256, query, kind, page]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || uploading) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setSourceError("Lütfen 2026 Bakanlık fiyat listesi PDF dosyasını seçin."); return;
    }
    setUploading(true); setSourceError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch(API + "/api/a348/catalog/source", {
        method: "POST", cache: "no-store",
        headers: { Authorization: "Bearer " + token }, body: form,
      });
      if (!response.ok) throw Error(await decodeError(response));
      const data = await response.json() as SourceSummary;
      if (!data.present || data.read_only !== true || data.approval_allowed !== false ||
        data.cost_allowed !== false || !data.source_sha256) throw Error("Yüklenen PDF kaynak doğrulamasını geçemedi.");
      setSource(data);
      setResults(null); setSelected(null);
      setFile(null); setQuery(""); setKind("all"); setPage(1);
      setRefresh(value => value + 1);
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : "PDF aktarılamadı.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className={styles.library}>
      <div className={styles.heading}>
        <div>
          <h1>PDF Poz Kütüphanesi</h1>
          <p>2026 ÇŞİDB / Yüksek Fen Kurulu · Resmî fiyat listesi</p>
        </div>
        {source?.present && <strong className={styles.count}>{trNumber(source.total_records ?? 0)} poz kaydı</strong>}
      </div>

      {loadingSource && <p role="status" className={styles.empty}>Kaynak kontrol ediliyor…</p>}
      {sourceError && <p role="alert" className={styles.error}>{sourceError}</p>}

      {!loadingSource && !source?.present && <section className={styles.upload}>
        <h2>2026 fiyat listesi PDF'sini yükle</h2>
        <p>ARKEMX poz numaralarını, tarifleri, birimleri, fiyat hücrelerini ve PDF sayfalarını otomatik çıkaracak.</p>
        <form onSubmit={event => void upload(event)}>
          <input aria-label="2026 Bakanlık fiyat listesi PDF" type="file" accept=".pdf,application/pdf"
            onChange={event => setFile(event.target.files?.[0] ?? null)}/>
          <button type="submit" disabled={!file || uploading}>
            {uploading ? "PDF okunuyor…" : "PDF'den pozları al"}
          </button>
        </form>
        <small>İnşaat Birim Fiyat Tarifleri Eki Fiyat Listesi'ni seç. Ayrıntılı analiz Cilt 1 PDF'si bu ekranın kaynağı değildir.</small>
      </section>}

      {source?.present && <>
        <div className={styles.source}>
          <span><b>{source.edition_date}</b> tarihli PDF</span>
          <span>{trNumber(source.pdf_pages ?? 0)} sayfa</span>
          <span>Okunamayan: <b>{source.audit?.unparsed_count ?? "—"}</b></span>
          <details>
            <summary>Başka PDF yükle</summary>
            <form onSubmit={event => void upload(event)}>
              <input aria-label="Yeni fiyat listesi PDF" type="file" accept=".pdf,application/pdf"
                onChange={event => setFile(event.target.files?.[0] ?? null)}/>
              <button type="submit" disabled={!file || uploading}>
                {uploading ? "PDF okunuyor…" : "PDF kaynağını güncelle"}
              </button>
            </form>
          </details>
        </div>

        <div className={styles.filters}>
          <label>PDF'de ara
            <input type="search" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }}
              placeholder="Poz numarası veya açıklaması"/>
          </label>
          <label>Poz grubu
            <select value={kind} onChange={event => {setKind(event.target.value);setPage(1);}}>
              {Object.entries(labels).map(([key, value]) => <option value={key} key={key}>{value}</option>)}
            </select>
          </label>
        </div>

        <div className={styles.columns}>
          <section className={styles.list} aria-label="PDF poz listesi">
            <div className={styles.listHeading}>
              <strong>{rowsLoading ? "Pozlar aranıyor…" : trNumber(results?.total ?? 0) + " kayıt"}</strong>
              <span>PDF kaynak verisi</span>
            </div>
            {rowsError && <p role="alert" className={styles.error}>{rowsError}</p>}
            {results?.items.length ? (
              <div className={styles.tableWrap}>
                <table>
                  <thead><tr><th>Poz No.</th><th>PDF açıklaması</th><th>Birim</th><th>Fiyat</th><th>Sayfa</th></tr></thead>
                  <tbody>{results.items.map(record =>
                    <tr key={record.code} className={selected?.code === record.code ? styles.active : undefined}>
                      <td><button type="button" className={styles.codeButton} onClick={() => setSelected(record)}>{record.code}</button></td>
                      <td><button type="button" className={styles.descriptionButton} onClick={() => setSelected(record)}>{record.description}</button></td>
                      <td>{record.unit || "—"}</td>
                      <td className={styles.amount}>{priceLabel(record.unit_price)}</td>
                      <td>{record.pdf_page}</td>
                    </tr>)}</tbody>
                </table>
              </div>
            ) : !rowsLoading && !rowsError ? <p className={styles.empty}>Bu arama için PDF poz kaydı bulunamadı.</p> : null}
            <div className={styles.pagination}>
              <button type="button" className={styles.secondary} disabled={page <= 1 || rowsLoading}
                onClick={() => setPage(value => Math.max(1, value - 1))}>Önceki</button>
              <span>{page} / {Math.max(1, Math.ceil((results?.total ?? 0) / 40))}</span>
              <button type="button" className={styles.secondary}
                disabled={rowsLoading || !results || page * 40 >= results.total}
                onClick={() => setPage(value => value + 1)}>Sonraki</button>
            </div>
          </section>

          <aside className={styles.detail} aria-label="Seçilen PDF poz kaydı">
            {selected ? <>
              <span className={styles.overline}>PDF POZ KAYDI</span>
              <h2>{selected.code}</h2>
              <p className={styles.description}>{selected.description}</p>
              <dl>
                <div><dt>Poz grubu</dt><dd>{labels[selected.kind] ?? selected.kind}</dd></div>
                <div><dt>Birim</dt><dd>{selected.unit || selected.unit_hint || "PDF satırında belirtilmemiş"}</dd></div>
                <div><dt>2026 birim fiyat</dt><dd>{priceLabel(selected.unit_price)}</dd></div>
                {selected.installation_price !== null && <div>
                  <dt>Ayrı montaj bedeli</dt><dd>{priceLabel(selected.installation_price)}</dd>
                </div>}
                <div><dt>PDF sayfası</dt><dd>{selected.pdf_page}</dd></div>
                {selected.parent_code && <div><dt>Üst tarif</dt><dd>{selected.parent_code} · {selected.parent_description}</dd></div>}
                <div><dt>Fiyat hücresi</dt><dd>{selected.price_status === "cell_extracted" ?
                  "PDF tablosundan okundu" : selected.price_status === "ambiguous_price" ?
                  "Belirsiz · kontrol gerekli" : "PDF'de fiyat bulunamadı"}</dd></div>
              </dl>
              <small>Kaynak: 2026 fiyat listesi · {source.source_sha256?.slice(0,12)}…</small>
            </> : <div className={styles.selectHint}>PDF kaydını görmek için listeden bir poz numarasına tıkla.</div>}
          </aside>
        </div>
        <p className={styles.footnote}>Bu sayfa yalnızca PDF'den çıkarılan poz verilerini gösterir. Burada eşleştirme, teknik onay veya maliyet işlemi yapılmaz.</p>
      </>}
    </div>
  );
}
