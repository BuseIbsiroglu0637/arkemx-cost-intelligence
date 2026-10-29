"use client";

import Link from "next/link";
import { clearWorkspace, readWorkspace, rememberImport, rememberProject } from "../workspace-context";
import WorkflowNav from "../workflow-nav";
import workflow from "../workflow-nav.module.css";
import { useEffect, useRef, useState } from "react";
import styles from "./review.module.css";

type Project = { id: string; name: string };
type Import = { id: string; filename: string; row_count: number; sheet: string; sha256: string };
type Source = { import_id: string; project_id: string; filename: string; sha256: string; sheet_name: string; row_count: number };
type Item = { work_item_id: string; source_row: number; original_description: string; effective_description: string; quantity: string | null; unit: string | null; revision_id: string | null; input_review_required: boolean };
type Selection = { schema: string; read_only: boolean; approval_allowed: boolean; import_source: Source; rows: Item[]; next_offset: number | null };
type Evidence = { quote: string; start?: number; end?: number };
type Check = { layer?: number; field: string; status: string; code: string | null; metraj_value: unknown; catalog_value: unknown; metraj_evidence: Evidence | Evidence[] | null; catalog_evidence: Evidence | Evidence[] | null };
type Row = {
  identity: { work_item_id: string; import_id: string; sheet_name: string; source_row: number; revision_id: string | null };
  original_description: string; effective_description: string; quantity: string | null; unit: string | null;
  candidate_code: string | null; technical_status: string; price_source_status: string;
  approval_allowed: boolean; flags: string[];
  comparison: { status: string; approval_allowed: boolean; blockers: string[]; review_flags: string[]; checks: Check[]; technical_checks: Check[] } | null;
  source_price: { value: string; currency: string; unit: string; source: { filename: string; sha256: string; pdf_page: number; printed_page: number; price_date: string } } | null;
};
type Report = { schema: string; read_only: boolean; approval_allowed: boolean; row_count: number; rows: Row[]; import_source: Source };
type View = "attention" | "all" | "checked_features_match" | "incompatible" | "review_required" | "out_of_scope";
const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const LABELS: Record<string, string> = {
  checked_features_match: "Kontrol edilen özellikler eşleşti", incompatible: "Teknik uyumsuzluk",
  review_required: "İnceleme gerekli", out_of_scope: "Kapsam dışı", verified: "Kaynak doğrulandı",
  not_available: "Kaynak yok", not_configured: "Kaynak tanımlanmamış", unverified: "Kaynak doğrulanamadı",
  match: "Eşleşiyor", block: "Uyuşmazlık", review: "İnceleme gerekli",
  work_type: "İmalat türü", thickness_mm: "Kalınlık (mm)", materials: "Malzeme",
  cement_dosage_kg: "Çimento miktarı (kg; tarifteki kum dayanağıyla)", environment: "Uygulama yeri",
  material_scope: "Malzeme kapsamı", work_scope_ince_siva: "İnce sıva kapsamı", work_scope_kaba_siva: "Kaba sıva kapsamı",
  included: "Kapsamda", excluded: "Kapsam dışı", kaba_siva: "Kaba sıva", ince_siva: "İnce sıva",
  siva: "Sıva", cimento: "Çimento", alci: "Alçı", gazbeton: "Gazbeton", ic: "İç", dis: "Dış",
  CANDIDATE_NOT_SELECTED: "Aday poz seçilmedi.", POSITION_NOT_SUPPORTED: "Bu poz mevcut teknik destek kapsamının dışında.",
  UNIT_UNVERIFIED: "Metraj birimi doğrulanamadı.", UNIT_MISMATCH: "Metraj birimi ile poz birimi uyuşmuyor.",
  PRICE_SOURCE_NOT_VERIFIED: "PDF fiyat kaynağı doğrulanamadı.", COMPARISON_UNVERIFIED: "Teknik karşılaştırma doğrulanamadı.",
  INPUT_REQUIRES_REVIEW: "Excel girdisinde inceleme gerektiren bilgi var.", QUANTITY_UNVERIFIED: "Metraj miktarı doğrulanamadı.",
  LAYERS_NOT_EXTRACTED: "Tariflerden en az birinin katmanları ayrıştırılamadı.",
  LAYER_COUNT_UNVERIFIED: "İki tarifteki katman sayısı aynı değil; katmanlar incelenmeli.",
  CEMENT_DOSAGE_KG_UNASSIGNED: "Çimento miktarlarından biri katmana güvenilir biçimde bağlanamadı.",
};
function label(value: string): string {
  if (LABELS[value]) return LABELS[value];
  const reason = /^(?:LAYER_(\d+)_)?(.+)_(MISMATCH|UNVERIFIED|AMBIGUOUS)$/.exec(value);
  if (reason && LABELS[reason[2].toLowerCase()]) {
    const outcome: Record<string, string> = { MISMATCH: "uyuşmuyor", UNVERIFIED: "doğrulanamadı", AMBIGUOUS: "belirsiz veya çelişkili" };
    return `${reason[1] ? `Katman ${reason[1]}: ` : ""}${LABELS[reason[2].toLowerCase()]} ${outcome[reason[3]]}.`;
  }
  return value;
}
function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Belirtilmemiş";
  if (Array.isArray(value)) return value.length ? value.map(display).join(", ") : "Belirtilmemiş";
  return typeof value === "string" ? label(value) : typeof value === "object" ? JSON.stringify(value) : String(value);
}
function badgeClass(value: string): string {
  if (value === "incompatible" || value === "block") return styles.block;
  if (value === "checked_features_match" || value === "verified" || value === "match") return styles.match;
  return styles.review;
}
function EvidenceView({ title, value }: { title: string; value: Evidence | Evidence[] | null }) {
  const items = value ? Array.isArray(value) ? value : [value] : [];
  return <div><strong>{title}</strong>{items.length ? items.map((item, i) => <blockquote key={i}>{item.quote}</blockquote>) : <p>Kaynak ifadesi yok. Eksik bilgi tamamlanmadı.</p>}</div>;
}
function RowDetail({ row }: { row: Row }) {
  const [differencesOnly, setDifferencesOnly] = useState(true);
  const checks = row.comparison ? [...row.comparison.checks, ...row.comparison.technical_checks] : [];
  const visible = differencesOnly ? checks.filter(check => check.status !== "match") : checks;
  const reasons = [...row.flags, ...(row.comparison?.blockers ?? []), ...(row.comparison?.review_flags ?? [])];
  const price = row.source_price;
  return <section className={`${styles.card} ${styles.detail}`} aria-label={`Excel satırı ${row.identity.source_row} ayrıntıları`}>
    <h2>Excel satırı {row.identity.source_row}</h2>
    <div className={styles.tags}><span className={`${styles.badge} ${badgeClass(row.technical_status)}`}>{label(row.technical_status)}</span><span className={`${styles.badge} ${badgeClass(row.price_source_status)}`}>{label(row.price_source_status)}</span></div>
    <p>Bu önizleme mühendis onayı vermez. Kaynak fiyat, metraj maliyetine uygulanmış değildir.</p>
    {reasons.length > 0 && <div className={styles.notice}><strong>İnceleme gerekçeleri</strong><ul>{[...new Set(reasons)].map(reason => <li key={reason}>{label(reason)}</li>)}</ul></div>}
    <details><summary>Metraj tarifi ve revizyon</summary><p className={styles.quote}>{row.effective_description}</p>
      {row.original_description !== row.effective_description && <><h3>Özgün Excel tarifi</h3><p className={styles.quote}>{row.original_description}</p></>}
      <dl><dt>Çalışma sayfası</dt><dd>{row.identity.sheet_name}</dd><dt>Kayıt kimliği</dt><dd><code>{row.identity.work_item_id}</code></dd><dt>Revizyon</dt><dd>{row.identity.revision_id ?? "Özgün kayıt"}</dd></dl>
    </details>
    {price && <details><summary>PDF’de yayımlanan kaynak fiyatı ve belge kanıtı</summary>
      <p><strong>{Number.isFinite(Number(price.value)) ? new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(price.value)) : price.value} {price.currency}/{price.unit}</strong></p>
      <p>Kaynak doğrulaması teknik uygunluk onayı değildir. Bu tutar için metraj toplamı hesaplanmadı.</p>
      <dl><dt>Belge</dt><dd>{price.source.filename}</dd><dt>Fiyat tarihi</dt><dd>{price.source.price_date}</dd><dt>PDF / basılı sayfa</dt><dd>{price.source.pdf_page} / {price.source.printed_page}</dd><dt>SHA-256</dt><dd><code>{price.source.sha256}</code></dd></dl>
    </details>}
    {checks.length > 0 ? <><div className={styles.toolbar}><h3>Özellik karşılaştırması</h3><label className={styles.checkLabel}><input type="checkbox" checked={differencesOnly} onChange={e => setDifferencesOnly(e.target.checked)} />Yalnızca farklar ve eksikler</label></div>
      {visible.length === 0 ? <p>Kontrol edilen özelliklerde fark bulunmadı. Tümünü görmek için filtreyi kaldırabilirsin.</p> : <div className={styles.featureList}>{visible.map((check, index) => <article className={styles.featureCard} key={`${check.layer ?? 0}-${check.field}-${index}`}>
        <div className={styles.featureHeading}><h4>{check.layer ? `Katman ${check.layer} · ` : ""}{label(check.field)}</h4><span className={`${styles.badge} ${badgeClass(check.status)}`}>{label(check.status)}</span></div>
        <dl className={styles.values}><div><dt>Metraj</dt><dd>{display(check.metraj_value)}</dd></div><div><dt>Poz tarifi</dt><dd>{display(check.catalog_value)}</dd></div></dl>
        <details><summary>Kaynak ifadelerini aç</summary><EvidenceView title="Metraj ifadesi" value={check.metraj_evidence} /><EvidenceView title="Poz ifadesi" value={check.catalog_evidence} />{check.code && <small>{check.code}</small>}</details>
      </article>)}</div>}</> : <p>Bu satır için teknik özellik karşılaştırması üretilemedi. Gerekçeler yukarıda gösteriliyor.</p>}
  </section>;
}

export default function BatchTechnicalReviewPage() {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [imports, setImports] = useState<Import[]>([]);
  const [importId, setImportId] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [candidates, setCandidates] = useState<Record<string, string>>({});
  const [bulkCode, setBulkCode] = useState("");
  const [bulkMode, setBulkMode] = useState<"empty" | "replace">("empty");
  const [report, setReport] = useState<Report | null>(null);
  const [view, setView] = useState<View>("attention");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const requestRef = useRef<AbortController | null>(null);

  function clearResult() { setReport(null); setDetailId(null); }
  function invalidate() {
    requestRef.current?.abort(); requestRef.current = null;
    setBusy(""); setError(""); clearResult();
  }
  async function request<T>(path: string, apply: (data: T) => void, task: string, init: RequestInit = {}) {
    requestRef.current?.abort();
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) { clearWorkspace(); setAuthenticated(false); clearResult(); setSelection(null); return; }
    const controller = new AbortController(); requestRef.current = controller;
    setBusy(task); setError("");
    try {
      const response = await fetch(`${API}${path}`, { ...init, cache: "no-store", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, ...(init.body ? { "Content-Type": "application/json" } : {}) } });
      if (controller.signal.aborted || requestRef.current !== controller || sessionStorage.getItem("arkemx_dev_token") !== token) return;
      if (response.status === 401) {
        sessionStorage.removeItem("arkemx_dev_token"); clearWorkspace(); setAuthenticated(false);
        setSelection(null); setProjects([]); setImports([]); setSelected([]); clearResult();
        throw new Error("Oturum süresi doldu. Ana çalışma alanından yeniden giriş yap.");
      }
      if (!response.ok) {
        if ((response.status === 403 || response.status === 404 || response.status === 409) && task === "items") {
          const currentProject = readWorkspace(token)?.projectId;
          if (currentProject) rememberImport(token, currentProject, null);
          setImportId(""); setSelection(null);
        }
        const messages: Record<number, string> = {
          403: "Bu işlem için erişim izni bulunmuyor.", 404: "Proje, aktarım veya seçilen satır bulunamadı.",
          409: "Revizyon değişmiş veya aktarım incelemeye kapatılmış olabilir. Satırları yeniden yükle.",
          422: "Seçimi kontrol et. Bir incelemede 1–20 farklı satır ve geçerli aday kodları kullanılmalı.",
          503: "Kaynak hizmeti şu anda kullanılamıyor.",
        };
        throw new Error(messages[response.status] ?? `İşlem tamamlanamadı (HTTP ${response.status}).`);
      }
      const data: T = await response.json();
      if (!controller.signal.aborted && requestRef.current === controller && sessionStorage.getItem("arkemx_dev_token") === token) apply(data);
    } catch (err) {
      if (!controller.signal.aborted && requestRef.current === controller) setError(err instanceof Error ? err.message : "Bağlantı kurulamadı.");
    } finally {
      if (requestRef.current === controller) { setBusy(""); requestRef.current = null; }
    }
  }
  useEffect(() => {
    setReady(true);
    if (sessionStorage.getItem("arkemx_dev_token")) {
      setAuthenticated(true);
      void request<Project[]>("/api/projects", data => {
        setProjects(data);
        const token = sessionStorage.getItem("arkemx_dev_token");
        const saved = token ? readWorkspace(token) : null;
        if (saved && data.some(project => project.id === saved.projectId)) chooseProject(saved.projectId, saved.importId);
        else if (saved) clearWorkspace();
      }, "projects");
    }
    return () => { requestRef.current?.abort(); requestRef.current = null; };
    // The initial request reads the current session; later reloads are explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function chooseProject(id: string, rememberedImport: string | null = null) {
    invalidate(); setProjectId(id); setImports([]); setImportId(""); setSelection(null); setSelected([]); setCandidates({}); setOffset(0);
    setBulkCode("");
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (token) rememberProject(token, id);
    if (id) void request<Import[]>(`/api/projects/${encodeURIComponent(id)}/imports`, data => {
      setImports(data);
      if (rememberedImport && data.some(item => item.id === rememberedImport)) loadItems(rememberedImport, 0, id);
      else if (token) rememberImport(token, id, null);
    }, "imports");
  }
  function loadItems(id: string, pageOffset = 0, sourceProject = projectId) {
    invalidate(); setImportId(id); setSelection(null); setSelected([]); setCandidates({}); setOffset(pageOffset);
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (token) rememberImport(token, sourceProject, null);
    if (id) void request<Selection>(`/api/projects/${encodeURIComponent(sourceProject)}/a3/imports/${encodeURIComponent(id)}/items?limit=20&offset=${pageOffset}`, data => {
      if (data.read_only !== true || data.approval_allowed !== false || data.import_source.import_id !== id || data.import_source.project_id !== sourceProject || data.rows.length > 20) throw new Error("Satır kaynağı doğrulanamadı.");
      setSelection(data);
      if (token) rememberImport(token, sourceProject, id);
    }, "items");
  }
  function toggle(id: string, checked: boolean) {
    invalidate(); setSelected(prev => checked ? [...new Set([...prev, id])] : prev.filter(value => value !== id));
  }
  function candidate(id: string, value: string) {
    invalidate(); setCandidates(prev => ({ ...prev, [id]: value }));
  }
  const selectedRows = selection?.rows.filter(
    row => selected.includes(row.work_item_id)
  ) ?? [];

  const trimmedBulkCode = bulkCode.trim();

  const affectedRows = selectedRows.filter(row => {
    if (!trimmedBulkCode) return false;

    const current = (candidates[row.work_item_id] ?? "").trim();

    return bulkMode === "empty"
      ? !current
      : Boolean(current) && current !== trimmedBulkCode;
  });

  function applyBulkCandidate() {
    if (
      busy ||
      !trimmedBulkCode ||
      trimmedBulkCode.length > 80 ||
      affectedRows.length === 0
    ) return;

    const ids = affectedRows.map(row => row.work_item_id);

    invalidate();

    setCandidates(previous => {
      const next = { ...previous };

      for (const id of ids) {
        next[id] = trimmedBulkCode;
      }

      return next;
    });
  }
  function compare() {
    if (!selection || selected.length === 0 || selected.length > 20) return;
    const source = selection;
    const submitted = source.rows.filter(row => selected.includes(row.work_item_id));
    clearResult(); setView("attention");
    const rows = submitted.map(row => ({ work_item_id: row.work_item_id, candidate_code: candidates[row.work_item_id]?.trim() || null, expected_revision_id: row.revision_id }));
    void request<Report>(`/api/projects/${encodeURIComponent(projectId)}/a3/imports/${encodeURIComponent(importId)}/technical-review`, data => {
      const returned = new Set(data.rows.map(row => row.identity.work_item_id));
      if (data.read_only !== true || data.approval_allowed !== false || data.row_count !== submitted.length || data.rows.length !== submitted.length || returned.size !== submitted.length || data.import_source.import_id !== source.import_source.import_id || data.import_source.sha256 !== source.import_source.sha256 || data.rows.some(row => {
        const original = submitted.find(item => item.work_item_id === row.identity.work_item_id);
        return !original || row.approval_allowed !== false || (row.comparison !== null && row.comparison.approval_allowed !== false) || row.identity.import_id !== source.import_source.import_id || row.identity.source_row !== original.source_row || row.identity.revision_id !== original.revision_id || row.candidate_code !== (candidates[row.identity.work_item_id]?.trim() || null) || row.effective_description !== original.effective_description;
      })) throw new Error("Önizleme yanıtının kaynak kimliği veya salt okunur durumu doğrulanamadı.");
      setReport(data);
    }, "compare", { method: "POST", body: JSON.stringify({ rows }) });
  }
  const selectedProject = projects.find(project => project.id === projectId);
  const detail = report?.rows.find(row => row.identity.work_item_id === detailId);
  const filtered = report?.rows.filter(row => view === "all" || (view === "attention" ? row.technical_status !== "checked_features_match" : row.technical_status === view)) ?? [];
  const views: { key: View; title: string }[] = [{ key: "attention", title: "Farklar ve inceleme" }, { key: "all", title: "Tümü" }, ...["incompatible", "review_required", "out_of_scope", "checked_features_match"].map(key => ({ key: key as View, title: label(key) }))];
  return <main className={`page ${styles.page}`}>
    <WorkflowNav active="technical" />
    <div className={styles.journey} aria-label="Proje çalışma adımları"><Link href="/#metraj">1. Metrajı hazırla</Link><strong aria-current="step">2. Pozları incele</strong><span>3. Mühendis kararı</span><span>4. Maliyet taslağı</span></div>
    <Link href="/#technical">← Teknik inceleme seçenekleri</Link>
    <div><span className={styles.eyebrow}>ARKEMX · TEKNİK İNCELEME</span><h1>Excel teknik incelemesi</h1><p>Proje ve aktarımı seç, en fazla 20 satırı açıkça belirlediğin aday pozlarla karşılaştır.</p></div>
    <div className={styles.notice}>Bu ekran salt okunurdur. Kaynak fiyat doğrulaması mühendis onayı değildir; metraj toplamı veya alternatif maliyet hesaplanmaz.</div>
    {!ready ? <p role="status">Oturum kontrol ediliyor…</p> : !authenticated ? <section className={styles.card}><h2>ARKEMX oturumu gerekli</h2><p>Tarayıcıdaki ana çalışma alanından giriş yapıp buraya dön. PowerShell oturumu tarayıcıya aktarılmaz.</p><Link href="/">Giriş ekranına git</Link></section> : <>
      <section className={styles.card} aria-labelledby="source-heading"><h2 id="source-heading">1. Kaynağı seç</h2><div className={styles.fields}>
        <label>Proje<select value={projectId} onChange={e => chooseProject(e.target.value)}><option value="">Proje seç</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        <label>Excel aktarımı<select value={importId} disabled={!projectId || busy === "imports"} onChange={e => loadItems(e.target.value)}><option value="">Aktarım seç</option>{imports.map(item => <option key={item.id} value={item.id}>{item.filename} · {item.row_count} satır · {item.id.slice(0, 8)}</option>)}</select></label>
        <button type="button" className="secondary" disabled={Boolean(busy) || !importId} onClick={() => loadItems(importId, offset)}>Satırları yeniden yükle</button>
      </div>{projectId && !busy && imports.length === 0 && <p>Bu projede Excel aktarımı bulunmuyor.</p>}
      {!busy && projects.length === 0 && <p>Hesabında proje yok. Ana çalışma alanından proje ve Excel aktarımı oluşturabilirsin.</p>}
      {selectedProject?.name.toLowerCase().includes("sentetik") && <p className={styles.testNote}>Sentetik test projesi seçili. Sonuçlar gerçek proje doğruluğunu ölçmez.</p>}
      {selection && <div className={workflow.context} aria-label="İncelenen kaynak"><span><strong>Proje:</strong> {selectedProject?.name}</span><span><strong>Excel:</strong> {selection.import_source.filename}</span><span><strong>Sayfa:</strong> {selection.import_source.sheet_name}</span></div>}
      <p className="hint">Proje ve doğrulanan Excel seçimi bu tarayıcı sekmesinde hatırlanır. Proje, aktarım veya sayfa değiştiğinde ve satırlar yeniden yüklendiğinde aday girişleri sıfırlanır. Adayları düzenledikten sonra doğrudan inceleme düğmesini kullan.</p>
      {selection && <details><summary>Excel kaynak kimliği</summary><dl><dt>Dosya / sayfa</dt><dd>{selection.import_source.filename} / {selection.import_source.sheet_name}</dd><dt>Aktarım kimliği</dt><dd><code>{selection.import_source.import_id}</code></dd><dt>SHA-256</dt><dd><code>{selection.import_source.sha256}</code></dd></dl></details>}</section>
      {busy && <p role="status">{busy === "compare" ? "Teknik karşılaştırma hazırlanıyor…" : "Kaynak kayıtları yükleniyor…"}</p>}
      {error && <div role="alert" className="error">{error}</div>}
      {selection && <section className={styles.card} aria-labelledby="rows-heading"><div className={styles.toolbar}><h2 id="rows-heading">2. Satırları ve adayları belirle</h2><span>{selected.length} / 20 satır seçili</span></div>
        <p>Teknik destek kapsamı: <strong>15.275.1111</strong>. Diğer kodlar kapsam dışı olarak raporlanır. Aday poz, karşılaştırmak istediğin poz kodudur; onay anlamına gelmez. Boş bırakılırsa aday seçilmemiş olur.</p>
        <div className={styles.bulkPanel} role="group" aria-label="Toplu aday poz atama">
          <div className={styles.bulkFields}>
            <label>
              Toplu aday poz kodu
              <input
                type="text"
                list="supported-positions"
                maxLength={80}
                placeholder="15.275.1111"
                value={bulkCode}
                disabled={Boolean(busy)}
                onChange={e => setBulkCode(e.target.value)}
              />
            </label>
            <label>
              Uygulama kapsamı
              <select
                value={bulkMode}
                disabled={Boolean(busy)}
                onChange={e => setBulkMode(
                  e.target.value === "replace" ? "replace" : "empty"
                )}
              >
                <option value="empty">Yalnızca boş adayları doldur</option>
                <option value="replace">Yalnızca mevcut adayları değiştir</option>
              </select>
            </label>
          </div>
          <p role="status" aria-live="polite">
            {selectedRows.length} satır seçili ·{" "}
            <strong>{affectedRows.length} satır etkilenecek.</strong>
          </p>
          <button
            type="button"
            disabled={Boolean(busy) || !trimmedBulkCode ||
              trimmedBulkCode.length > 80 || affectedRows.length === 0}
            onClick={applyBulkCandidate}
          >
            Seçilen {affectedRows.length} satıra aday uygula
          </button>
          <p className={styles.testNote}>
            Bu işlem yalnızca aday kodunu belirler.
            Eski inceleme sonucu temizlenir.
            Mühendislik onayı verilmez.
          </p>
        </div>
        <div className={styles.tableScroll}><table><caption className={styles.srOnly}>Seçilen Excel aktarımındaki satırlar ve aday poz alanları</caption><thead><tr>
          <th><input type="checkbox" aria-label="Görünen tüm satırları seç" checked={selection.rows.length > 0 && selected.length === selection.rows.length} onChange={e => { invalidate(); setSelected(e.target.checked ? selection.rows.map(row => row.work_item_id) : []); }} /></th><th>Excel satırı</th><th>İmalat tarifi</th><th>Miktar / birim</th><th>Aday poz</th>
        </tr></thead><tbody>{selection.rows.map(row => <tr key={row.work_item_id}>
          <td><input type="checkbox" aria-label={`Excel satırı ${row.source_row} seç`} checked={selected.includes(row.work_item_id)} onChange={e => toggle(row.work_item_id, e.target.checked)} /></td><td>{row.source_row}{row.revision_id && <small className={styles.meta}>Revizyon var</small>}</td>
          <td className={styles.description}><details><summary>{row.effective_description.slice(0, 150)}{row.effective_description.length > 150 ? "…" : ""}</summary><p className={styles.quote}>{row.effective_description}</p>{row.original_description !== row.effective_description && <><strong>Özgün Excel tarifi</strong><p className={styles.quote}>{row.original_description}</p></>}</details>{row.input_review_required && <small className={styles.meta}>Girdi incelemesi gerekli</small>}</td>
          <td>{row.quantity ?? "Miktar eksik"}<br />{row.unit ?? "Birim eksik"}</td>
          <td><label><span className={styles.srOnly}>Excel satırı {row.source_row} aday poz</span><input className={styles.codeInput} list="supported-positions" maxLength={80} placeholder="Poz kodu yaz" value={candidates[row.work_item_id] ?? ""} onChange={e => candidate(row.work_item_id, e.target.value)} /></label></td>
        </tr>)}</tbody></table></div><datalist id="supported-positions"><option value="15.275.1111" /></datalist>
        <div className={styles.toolbar}><div className={styles.tags}><button type="button" className="secondary" disabled={Boolean(busy) || offset === 0} onClick={() => loadItems(importId, Math.max(0, offset - 20))}>Önceki 20</button><button type="button" className="secondary" disabled={Boolean(busy) || selection.next_offset === null} onClick={() => loadItems(importId, selection.next_offset ?? 0)}>Sonraki 20</button></div><span>Sayfa değiştiğinde seçimler sıfırlanır.</span><button type="button" disabled={Boolean(busy) || selected.length === 0} onClick={compare}>Seçilen {selected.length} satırı incele</button></div>
      </section>}
      {report && <div className={styles.workbench}><section className={styles.card} aria-labelledby="results-heading"><h2 id="results-heading">3. İnceleme sonucu</h2><p>{report.row_count} seçili satır değerlendirildi. “Kontrol edilen özellikler eşleşti” tam teknik uygunluk veya onay anlamına gelmez.</p>
        <div className={styles.filters} role="group" aria-label="Teknik sonuç filtreleri">{views.map(option => {
          const count = report.rows.filter(row => option.key === "all" || (option.key === "attention" ? row.technical_status !== "checked_features_match" : row.technical_status === option.key)).length;
          return <button type="button" key={option.key} aria-pressed={view === option.key} onClick={() => setView(option.key)}>{option.title} <strong>{count}</strong></button>;
        })}</div>
        {filtered.length ? <ul className={styles.resultList} aria-label="İncelenen Excel satırları">{filtered.map(row => <li className={styles.resultCard} key={row.identity.work_item_id} data-active={detailId === row.identity.work_item_id ? "true" : undefined}>
          <div className={styles.resultHeading}><strong>Excel satırı {row.identity.source_row}</strong><span className={styles.positionCode}>{row.candidate_code ?? "Aday seçilmedi"}</span></div>
          <div className={styles.resultStatuses}><div><small>Teknik durum</small><span className={`${styles.badge} ${badgeClass(row.technical_status)}`}>{label(row.technical_status)}</span></div><div><small>Fiyat kaynağı</small><span className={`${styles.badge} ${badgeClass(row.price_source_status)}`}>{label(row.price_source_status)}</span></div></div>
          <button type="button" className="secondary" aria-label={`Excel satırı ${row.identity.source_row} kanıtlarını aç`} aria-pressed={detailId === row.identity.work_item_id} onClick={() => { setDetailId(row.identity.work_item_id); requestAnimationFrame(() => document.getElementById("batch-detail")?.focus()); }}>{detailId === row.identity.work_item_id ? "Kanıtlar gösteriliyor" : "Kanıtları aç"}</button>
        </li>)}</ul> : <p>Bu filtrede satır bulunmuyor. Diğer sonuçları görmek için “Tümü” filtresini seç.</p>}
      </section>
      <aside id="batch-detail" tabIndex={-1} aria-label="Seçili satırın teknik kanıtları" className={styles.evidencePane}>
        {detail ? <><div className={styles.nextAction}><strong>Excel satırı {detail.identity.source_row} · Sonraki işlem</strong><p>{detail.flags.includes("CANDIDATE_NOT_SELECTED") ? "Bu satır için aday poz kodu belirle ve yeniden incele." : detail.technical_status === "incompatible" ? "Uyuşmazlığı incele; tarifi veya aday pozu değiştirmek gerekiyorsa kaynak kaydı düzelt." : detail.technical_status === "out_of_scope" ? "Bu aday pilot kapsamının dışında. Bağımsız mühendis incelemesi gerekir." : detail.technical_status === "review_required" ? "Eksik veya belirsiz bilgileri aşağıdaki gerekçelerden kontrol et." : "Kontrol edilen özellikler eşleşti. Bu önizleme henüz mühendis kararına veya maliyet taslağına aktarılamaz."}</p><p className="hint">Bu adımda sonuç ve aday girişleri kalıcı kaydedilmez. Mühendis kararı bağlantısı sonraki geliştirmedir.</p></div><RowDetail key={detail.identity.work_item_id} row={detail} /></> : <div className={styles.card}><h2>Satırın kanıtları</h2><p>Soldaki listeden “Kanıtları aç” seç. Teknik farklar ve özgün ifadeler burada görünecek.</p></div>}
      </aside></div>}
    </>}
  </main>;
}
