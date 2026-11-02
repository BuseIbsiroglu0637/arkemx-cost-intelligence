"use client";

import {useEffect, useRef, useState} from "react";
import {readWorkspace} from "./workspace-context";
import styles from "./metraj-understanding-preview.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PAGE_SIZE = 20;
const scopeLabels: Record<string, string> = {
  demolition: "Söküm / yıkım",
  material_only: "Yalnız malzeme",
  labor_only: "Yalnız işçilik",
  material_and_labor: "Malzeme + işçilik",
  execution_unspecified: "Uygulama (kapsam belirsiz)",
  unspecified: "Kapsam belirtilmemiş",
};
const statusLabels: Record<string, string> = {
  structured_for_retrieval: "Aday aramaya hazırlanmış",
  needs_review: "Eksik / belirsiz bilgi",
  multiple_works_for_review: "Birden fazla imalat",
  insufficient_input: "Açıklama eksik",
};
const flagLabels: Record<string, string> = {
  MATERIAL_FAMILY_UNRECOGNIZED: "Malzeme/imalat türü belirlenemedi",
  DESCRIPTION_MISSING: "Açıklama eksik",
  UNIT_MISSING: "Birim eksik",
  QUANTITY_MISSING: "Miktar eksik",
  METRAJ_INPUT_REVIEW_REQUIRED: "Excel girdi kontrolü gerekli",
  MULTIPLE_WORK_TYPES: "Tek satırda birden fazla imalat",
  MATERIAL_BINDER_AMBIGUOUS: "Bağlayıcı malzeme belirsiz",
  LAYER_ASSOCIATION_UNCERTAIN: "Katman ilişkisi belirsiz",
  THICKNESS_CONTEXT_UNCERTAIN: "Kalınlık bağlamı belirsiz",
  WORK_SCOPE_UNCLEAR: "İş kapsamı açık değil",
};
type ImportEntry = {id: string; filename: string; sheet: string; row_count: number};
type PdfCandidate = {
  code: string; description: string; kind: string; unit: string | null;
  unit_price: string | null; price_status: string; pdf_page: number;
  pdf_source_sha256: string; analysis_cilt1_linked: boolean;
  lexical_similarity: number; score_is_probability: false;
  technical_compliance_verified: false; technical_review_required: true;
  technical_status: "review" | "blocked";
  blockers: string[]; review_flags: string[];
  approval_allowed: false; cost_allowed: false;
};
type CandidateSearch = {
  read_only: true; approval_allowed: false; cost_allowed: false;
  catalog_matching_performed: true; candidate_selected: false;
  excel: {source_sha256: string; source_row: number; work_item_id: string; description: string};
  catalog: {edition_date: string; source_sha256: string; position_count: number};
  status: string; reason: string | null; scanned_count: number;
  candidates: PdfCandidate[]; blocked_examples: PdfCandidate[];
};
const issueLabels: Record<string, string> = {
  THICKNESS_MM_MISMATCH: "Kalınlık uyuşmuyor",
  DIMENSIONS_MISMATCH: "Ebatlar uyuşmuyor",
  MATERIAL_MISMATCH: "Malzeme uyuşmuyor",
  MATERIAL_FAMILY_MISMATCH: "İmalat malzemesi farklı",
  PLASTER_BINDER_MISMATCH: "Çimento / alçı türü farklı",
  UNIT_MISMATCH: "Metraj ve poz birimi farklı",
  WORK_SCOPE_DEMOLITION_MISMATCH: "Söküm ile imalat birbirine karışıyor",
  WORK_SCOPE_MATERIAL_ONLY_MISMATCH: "Malzeme alımı ile uygulama kapsamı farklı",
  WORK_SCOPE_LABOR_ONLY_MISMATCH: "Yalnız işçilik kapsamı farklı",
  WORK_SCOPE_COMBINED_MISMATCH: "Malzeme + işçilik kapsamı farklı",
  PDF_MATERIAL_FAMILY_UNVERIFIED: "PDF'de malzeme açık değil",
  EXCEL_MATERIAL_FAMILY_UNVERIFIED: "Excel'de malzeme açık değil",
  PLASTER_BINDER_UNVERIFIED: "Sıva bağlayıcısı doğrulanmalı",
  PDF_LABOR_ONLY_SCOPE_UNVERIFIED: "PDF'nin yalnız işçilik kapsamı doğrulanmalı",
  PDF_UNIT_UNVERIFIED: "PDF'de birim doğrulanamadı",
  PDF_PRICE_UNAVAILABLE: "PDF'de sayısal birim fiyat yok",
};
type Understanding = {
  status: string; description: string; unit: string | null; quantity: string | null;
  material_families: string[]; binder_materials: string[];
  work_scope: string; thicknesses_mm: string[];
  technical_facts: {
    dimensions: number[][]; joint_width_mm: number | null;
  };
  layers: {work_type: string | null; thickness_mm: string | null; evidence: {quote: string}}[];
  review_flags: string[]; match_selected: false; approval_allowed: false; cost_allowed: false;
};
type Preview = {
  read_only: true; catalog_matching_performed: false;
  approval_allowed: false; cost_allowed: false;
  source: {import_id: string; excel_sha256: string};
  total_rows: number; offset: number; limit: number; returned: number; has_more: boolean;
  rows: {work_item_id: string; source_row: number; understanding: Understanding}[];
};

async function getJson<T>(url: string, token: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(API + url, {
    headers: {Authorization: "Bearer " + token}, cache: "no-store", signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null) as {detail?: unknown} | null;
    throw Error(typeof data?.detail === "string" ? data.detail : "HTTP " + response.status);
  }
  return await response.json() as T;
}

export default function MetrajUnderstandingPreview({
  token, project, revision,
}: {token: string; project: string; revision: number}) {
  const [imports, setImports] = useState<ImportEntry[]>([]);
  const [importId, setImportId] = useState("");
  const [result, setResult] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [candidateFor, setCandidateFor] = useState<string>("");
  const [candidateData, setCandidateData] = useState<CandidateSearch | null>(null);
  const [candidateError, setCandidateError] = useState("");
  const [candidateBusy, setCandidateBusy] = useState(false);
  const candidateController = useRef<AbortController | null>(null);
  useEffect(() => () => candidateController.current?.abort(), []);

  function clearCandidates() {
    candidateController.current?.abort();
    candidateController.current = null;
    setCandidateFor("");
    setCandidateData(null);
    setCandidateError("");
    setCandidateBusy(false);
  }

  useEffect(() => {
    const controller = new AbortController();
    clearCandidates();
    setResult(null); setImports([]); setImportId(""); setError("");
    void getJson<ImportEntry[]>("/api/projects/" + project + "/imports", token, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return;
        setImports(data);
        const stored = readWorkspace(token);
        const requested = stored?.projectId === project ? stored.importId : null;
        setImportId(data.some(item => item.id === requested) ? (requested ?? "") : (data[0]?.id ?? ""));
      }).catch(err => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Excel kayıtları açılamadı.");
      });
    return () => controller.abort();
  }, [token, project, revision]);

  async function load(offset: number) {
    if (!importId || busy) return;
    clearCandidates();
    setBusy(true); setError("");
    try {
      const url = "/api/projects/" + project + "/a349/imports/" + importId +
        "/understanding?offset=" + offset + "&limit=" + PAGE_SIZE;
      const data = await getJson<Preview>(url, token);
      if (data.read_only !== true || data.approval_allowed !== false ||
          data.cost_allowed !== false || data.catalog_matching_performed !== false ||
          data.source.import_id !== importId ||
          data.rows.some(row => row.understanding.approval_allowed !== false ||
            row.understanding.match_selected !== false || row.understanding.cost_allowed !== false)) {
        throw Error("Metraj yorumlama sonuçları güvenli değil.");
      }
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Metraj açıklamaları okunamadı.");
    } finally {
      setBusy(false);
    }
  }

  async function lookupCandidates(row: Preview["rows"][number]) {
    if (!importId || candidateBusy) return;
    candidateController.current?.abort();
    const controller = new AbortController();
    candidateController.current = controller;
    setCandidateFor(row.work_item_id);
    setCandidateData(null); setCandidateError(""); setCandidateBusy(true);
    try {
      const url = "/api/projects/" + project + "/a349/imports/" + importId +
        "/items/" + row.work_item_id + "/candidates";
      const data = await getJson<CandidateSearch>(url, token, controller.signal);
      if (controller.signal.aborted) return;
      if (data.read_only !== true || data.approval_allowed !== false ||
          data.cost_allowed !== false || data.candidate_selected !== false ||
          data.catalog_matching_performed !== true ||
          data.excel.work_item_id !== row.work_item_id ||
          data.catalog.edition_date !== "01.01.2026" ||
          [...data.candidates, ...data.blocked_examples].some(
            item => item.approval_allowed !== false ||
              item.cost_allowed !== false || item.technical_compliance_verified !== false ||
              item.pdf_source_sha256 !== data.catalog.source_sha256 ||
              item.score_is_probability !== false)) {
        throw Error("Kaynak veya eşleştirme güvenliği doğrulanamadı.");
      }
      setCandidateData(data);
    } catch (err) {
      if (!controller.signal.aborted) {
        setCandidateError(err instanceof Error ? err.message : "Poz adayları aranamadı.");
      }
    } finally {
      if (!controller.signal.aborted) setCandidateBusy(false);
    }
  }

  return <details className={styles.panel}>
    <summary>Metraj açıklamalarını yorumla <span>A3.49.2 · Poz adayları</span></summary>
    <p className={styles.hint}>Excel'deki imalat türünü, kalınlığı ve iş kapsamını çıkarır.
      Her satırda gerçek 2026 PDF poz adaylarını da salt okunur olarak araştırabilirsin. Adaylar henüz onaylı değildir.</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {imports.length > 0 ? <div className={styles.controls}>
      <label>Excel kaynağı
        <select value={importId} onChange={event => {clearCandidates(); setImportId(event.target.value); setResult(null);}}>
          {imports.map(item => <option value={item.id} key={item.id}>
            {item.filename} · {item.sheet} ({item.row_count} kalem)
          </option>)}
        </select>
      </label>
      <button type="button" disabled={busy || !importId} onClick={() => void load(0)}>
        {busy ? "Okunuyor…" : "Metrajı yorumla"}
      </button>
    </div> : <p className={styles.hint}>Bu projeye Excel metrajı kaydedildiğinde burada görünecek.</p>}
    {result && <>
      <p className={styles.hint}>
        {result.total_rows.toLocaleString("tr-TR")} Excel satırından {result.offset + 1}–{result.offset + result.returned} arası.
        Kaynak açıklamalar değiştirilmiyor.
      </p>
      <div className={styles.tableWrap}>
        <table>
          <thead><tr>
            <th>Excel</th><th>İmalat açıklaması</th><th>ARKEMX ne anladı?</th><th>İnceleme durumu</th><th>Poz arama</th>
          </tr></thead>
          <tbody>{result.rows.map(row => {
            const u = row.understanding;
            const dims = u.technical_facts.dimensions.map(pair => pair.join("×")).join(", ");
            return <tr key={row.work_item_id}>
              <td>{row.source_row}</td>
              <td>{u.description}<small>{u.quantity ?? "—"} {u.unit ?? ""}</small></td>
              <td>
                <strong>{u.material_families.join(" + ") || "Belirlenemedi"}</strong>
                <small>{scopeLabels[u.work_scope] ?? u.work_scope}</small>
                {!!u.binder_materials.length && <small>Malzeme: {u.binder_materials.join(", ")}</small>}
                {!!u.thicknesses_mm.length && <small>Kalınlık: {u.thicknesses_mm.join(", ")} mm</small>}
                {dims && <small>Ölçü: {dims}</small>}
                {!!u.layers.length && <details className={styles.layers}>
                  <summary>Katman kaynakları ({u.layers.length})</summary>
                  {u.layers.map((layer, idx) => <small key={idx}>
                    {layer.work_type ?? "Katman"}: {layer.thickness_mm ?? "?"} mm —
                    “{layer.evidence.quote}”
                  </small>)}
                </details>}
              </td>
              <td>
                <strong className={u.review_flags.length ? styles.warn : styles.ok}>
                  {statusLabels[u.status] ?? u.status}
                </strong>
                {u.review_flags.map(flag => <small key={flag}>
                  {flagLabels[flag] ?? flag}
                </small>)}
              </td>
              <td>
                <button type="button" className={styles.searchButton}
                  disabled={candidateBusy} onClick={() => void lookupCandidates(row)}>
                  {candidateBusy && candidateFor === row.work_item_id ? "Aranıyor…" : "Adayları gör"}
                </button>
              </td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {(candidateFor || candidateData) && <section className={styles.candidateCard} aria-label="2026 poz adayları">
        <div className={styles.candidateHead}>
          <div><strong>2026 poz adayı kontrolü</strong>
            <p>Bu arama yalnızca kaynak PDF'deki kayıtları önerir; mühendis onayı veya maliyet kaydı yapmaz.</p>
          </div>
          <button type="button" className="secondary" onClick={clearCandidates}>Kapat</button>
        </div>
        {candidateBusy && <p role="status">Resmî poz tarifleri teknik açıdan karşılaştırılıyor…</p>}
        {candidateError && <p role="alert" className={styles.error}>{candidateError}</p>}
        {candidateData && <>
          <p className={styles.hint}>Excel satırı {candidateData.excel.source_row} ·
            2026 kaynağından {candidateData.catalog.position_count.toLocaleString("tr-TR")} kayıt ·
            {candidateData.scanned_count} aday ön taramadan geçti</p>
          {candidateData.reason && <p className={styles.warn}>{candidateData.reason}</p>}
          {candidateData.candidates.length > 0 && <div className={styles.candidateList}>
            {candidateData.candidates.map(candidate => <article className={styles.candidate} key={candidate.code}>
              <div className={styles.candidateHead}>
                <strong>{candidate.code}</strong>
                <span className={styles.reviewFlag}>Teknik inceleme gerekli</span>
              </div>
              <p>{candidate.description}</p>
              <p>{candidate.unit ?? "Birimi eksik"} ·
                {candidate.unit_price === null ? "Fiyatı belirtilmemiş" : " 2026 birim fiyatı: " + candidate.unit_price + " TL"} ·
                PDF s. {candidate.pdf_page}</p>
              <small>{candidate.analysis_cilt1_linked ? "Cilt 1 analiz bağlantısı mevcut" :
                "Cilt 1 analizi bağlı değil"}</small>
              {!!candidate.review_flags.length && <small>
                Kontrol: {candidate.review_flags.map(issue => issueLabels[issue] ?? issue).join(" · ")}
              </small>}
            </article>)}
          </div>}
          {candidateData.blocked_examples.length > 0 && <details className={styles.blocked}>
            <summary>Teknik nedenle elenen örnekler ({candidateData.blocked_examples.length})</summary>
            {candidateData.blocked_examples.map(candidate => <div key={candidate.code}>
              <strong>{candidate.code}</strong> — {candidate.description}
              <small>Engel: {candidate.blockers.map(issue => issueLabels[issue] ?? issue).join(" · ")}</small>
            </div>)}
          </details>}
          <small>Benzerlik puanları onay olasılığı değildir; sonuçlar hiçbir poz seçimi oluşturmaz.</small>
        </>}
      </section>}
      <div className={styles.pager}>
        <button type="button" className="secondary" disabled={busy || result.offset === 0}
          onClick={() => void load(Math.max(0, result.offset - PAGE_SIZE))}>Önceki</button>
        <span>{Math.floor(result.offset / PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(result.total_rows / PAGE_SIZE))}</span>
        <button type="button" className="secondary" disabled={busy || !result.has_more}
          onClick={() => void load(result.offset + PAGE_SIZE)}>Sonraki</button>
      </div>
    </>}
  </details>;
}
