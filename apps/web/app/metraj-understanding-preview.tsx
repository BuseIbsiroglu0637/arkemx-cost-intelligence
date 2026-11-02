"use client";

import {useEffect, useState} from "react";
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

  useEffect(() => {
    const controller = new AbortController();
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

  return <details className={styles.panel}>
    <summary>Metraj açıklamalarını yorumla <span>Yeni · A3.49.1</span></summary>
    <p className={styles.hint}>Excel'deki imalat türünü, kalınlığı ve iş kapsamını çıkarır.
      Henüz poz eşleştirme veya maliyet hesabı yapmaz.</p>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {imports.length > 0 ? <div className={styles.controls}>
      <label>Excel kaynağı
        <select value={importId} onChange={event => {setImportId(event.target.value); setResult(null);}}>
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
            <th>Excel</th><th>İmalat açıklaması</th><th>ARKEMX ne anladı?</th><th>İnceleme durumu</th>
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
            </tr>;
          })}</tbody>
        </table>
      </div>
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
