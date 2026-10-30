"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { readWorkspace, rememberImport, rememberProject } from "../workspace-context";
import ReviewWorkspace from "./review-workspace";
import HandoffDecisionPanel from "./handoff-decision-panel";
import styles from "./simple-review.module.css";

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
type Project = { id: string; name: string };
type Imported = { id: string; filename: string; sheet: string; row_count: number };
type Item = { work_item_id: string; source_row: number; effective_description: string; quantity: string | null; unit: string | null; input_review_required: boolean };
type Selection = {
  read_only: true; approval_allowed: false; rows: Item[];
  import_source: { import_id: string; project_id: string; filename: string; sheet_name: string };
  next_offset: number | null;
};
type ReviewRow = {
  work_item_id: string; source_row: number; description: string; status: string; reason: string;
  checks: string[]; evidence_page: number | null; evidence_facts?: Record<string, string | number>;
  evidence_quote?: string | null; saved_candidate: string | null;
  engineering_approved: false; cost_allowed: false;
};
type Readiness = {
  schema: "arkemx.a327.readiness.v1"; read_only: true; approval_allowed: false;
  engineering_approved: false; cost_allowed: false; import_id: string;
  source_sha256: string | null; document_state: string; rows: ReviewRow[];
};
type Decision = { id: string; action: string; reason: string; created_at: string; created_by_id: string; source_current: boolean };
type DecisionState = { work_item_id: string; approval_allowed: false; engineering_approved: false; cost_allowed: false; latest_event: Decision | null };
type Tab = "items" | "missing" | "decisions";

const factLabels: Record<string, string> = {
  gazbeton_strength_n_mm2: "Gazbeton dayanımı (N/mm²)",
  gazbeton_density_kg_m3: "Gazbeton yoğunluğu (kg/m³)",
  glaze: "Sır", surface: "Yüzey", rectified: "Kenar",
  layer_type: "Sıva katmanı", layer_thickness_mm: "Kalınlık (mm)",
  concrete_class: "Beton sınıfı", paint_base: "Boya türü", coat_count: "Kat sayısı",
};
const actionLabels: Record<string, string> = {
  request_information: "Eksik bilgi istendi",
  reject_candidate: "Poz adayı reddedildi",
  submit_for_engineering_review: "Mühendis incelemesine iletildi",
};
function title(row: ReviewRow): string {
  if (row.status === "documented_for_review") return "Poz ön uyumu · Mühendis onayı bekliyor";
  if (row.status === "document_evidence_for_review") return "Belgede kısmi bilgi bulundu";
  if (row.status === "conflicting") return "Çelişen bilgi · İnceleme gerekli";
  if (row.status === "needs_candidate") return "Poz seçimi eksik";
  if (row.status === "stale_candidate") return "Poz veya kaynak değişmiş";
  if (row.status === "input_review") return "Metraj kontrolü gerekli";
  if (row.status === "needs_document") return "Belge bilgisi eksik";
  return "Teknik inceleme gerekli";
}
function isPrechecked(row: ReviewRow): boolean {
  return row.status === "documented_for_review";
}
async function api<T>(path: string, token: string): Promise<T> {
  const response = await fetch(API + path, {
    cache: "no-store", headers: { Authorization: "Bearer " + token },
  });
  if (!response.ok) {
    if (response.status === 401) throw Error("Oturum sona erdi. Yeniden giriş yap.");
    if (response.status === 404) throw Error("Seçilen proje veya Excel kaynağı bulunamadı.");
    throw Error("Bilgiler yüklenemedi (HTTP " + response.status + ").");
  }
  return response.json() as Promise<T>;
}
const endpoint = (projectId: string, importId: string) =>
  "/api/projects/" + encodeURIComponent(projectId) + "/a327/imports/" + encodeURIComponent(importId);

export default function SimpleReviewWorkspace({
  projectScope, onImportSelected, onSessionExpired,
}: {
  projectScope?: string;
  onImportSelected?: (value: string) => void;
  onSessionExpired?: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(projectScope ?? "");
  const [imports, setImports] = useState<Imported[]>([]);
  const [importId, setImportId] = useState("");
  const [source, setSource] = useState<Selection | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [tab, setTab] = useState<Tab>("items");
  const [opened, setOpened] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [decisions, setDecisions] = useState<Record<string, DecisionState | null>>({});
  const [decisionLoading, setDecisionLoading] = useState(false);

  useEffect(() => {
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) { setBusy(false); setError("Oturum gerekli. Ana sayfadan giriş yap."); return; }
    let active = true;
    void api<Project[]>("/api/projects", token).then(data => {
      if (!active) return;
      setProjects(data);
      const saved = readWorkspace(token);
      const id = projectScope ?? (saved && data.some(p => p.id === saved.projectId) ? saved.projectId : "");
      if (id && !data.some(p => p.id === id)) throw Error("Bu projeye erişim bulunamadı.");
      setProjectId(id);
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "Proje okunamadı."); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [projectScope]);

  useEffect(() => {
    const token = sessionStorage.getItem("arkemx_dev_token");
    setImports([]); setImportId(""); setSource(null); setReadiness(null);
    setOpened(null); setDecisions({}); setOffset(0);
    if (!projectId || !token) return;
    let active = true;
    setBusy(true); setError("");
    void api<Imported[]>("/api/projects/" + encodeURIComponent(projectId) + "/imports", token)
      .then(data => {
        if (!active) return;
        setImports(data);
        const saved = readWorkspace(token);
        const remembered = saved?.projectId === projectId ? saved.importId : null;
        const preferred = data.find(item => item.id === remembered) ?? data[0];
        rememberProject(token, projectId);
        if (preferred) setImportId(preferred.id);
        else onImportSelected?.("");
      }).catch(e => { if (active) setError(e instanceof Error ? e.message : "Excel bulunamadı."); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [projectId, onImportSelected]);

  useEffect(() => {
    const token = sessionStorage.getItem("arkemx_dev_token");
    setSource(null); setReadiness(null); setOpened(null); setDecisions({});
    if (!projectId || !importId || !token) return;
    let active = true;
    setBusy(true); setError("");
    const base = "/api/projects/" + encodeURIComponent(projectId);
    void Promise.all([
      api<Selection>(base + "/a3/imports/" + encodeURIComponent(importId) + "/items?limit=20&offset=" + offset, token),
      api<Readiness>(endpoint(projectId, importId) + "/readiness?limit=20&offset=" + offset, token),
    ]).then(([items, review]) => {
      if (!active) return;
      if (items.read_only !== true || items.approval_allowed !== false ||
          items.import_source.import_id !== importId || items.import_source.project_id !== projectId ||
          review.schema !== "arkemx.a327.readiness.v1" || review.read_only !== true ||
          review.import_id !== importId || review.approval_allowed !== false ||
          review.engineering_approved !== false || review.cost_allowed !== false ||
          review.rows.length !== items.rows.length ||
          review.rows.some((r, i) => r.work_item_id !== items.rows[i].work_item_id ||
            r.engineering_approved !== false || r.cost_allowed !== false)) {
        throw Error("Kaynak ve güvenlik doğrulaması başarısız.");
      }
      setSource(items); setReadiness(review);
      rememberImport(token, projectId, importId);
      onImportSelected?.(items.import_source.filename + " · " + items.import_source.sheet_name);
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "Teknik inceleme yüklenemedi."); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [projectId, importId, offset, refresh, onImportSelected]);

  useEffect(() => {
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (tab !== "decisions" || !readiness || !token || !projectId || !importId) return;
    let active = true;
    setDecisionLoading(true);
    const base = endpoint(projectId, importId);
    // At most 20 visible rows. Failed reads remain unknown, not "no decision".
    void Promise.all(readiness.rows.map(async row => {
      try {
        const data = await api<DecisionState>(
          base + "/items/" + encodeURIComponent(row.work_item_id) + "/decision-state", token);
        if (data.work_item_id !== row.work_item_id || data.approval_allowed !== false ||
            data.engineering_approved !== false || data.cost_allowed !== false) return [row.work_item_id, null] as const;
        return [row.work_item_id, data] as const;
      } catch { return [row.work_item_id, null] as const; }
    })).then(entries => { if (active) setDecisions(Object.fromEntries(entries)); })
      .finally(() => { if (active) setDecisionLoading(false); });
    return () => { active = false; };
  }, [tab, readiness, projectId, importId, refresh]);

  const rows = readiness?.rows ?? [];
  const selected = rows.find(row => row.work_item_id === opened);
  const item = source?.rows.find(row => row.work_item_id === opened);
  const verified = rows.filter(isPrechecked).length;
  const missing = rows.length - verified;
  const shown = tab === "missing" ? rows.filter(row => !isPrechecked(row)) : rows;

  return <section className={styles.root} aria-label="Sade teknik inceleme">
    <header className={styles.header}>
      <div><span className={styles.kicker}>ARKEMX · TEKNİK KONTROL</span>
        <h2>İmalatları incele</h2>
        <p>Bir imalat seç; doğru görünen ve eksik kalan bilgileri tek ekranda gör.</p>
      </div>
      <div className={styles.headerActions}>
        <Link className={styles.costLink} href="/#cost">Maliyet aşamasına geç →</Link>
        <button type="button" className="secondary" onClick={() => setAdvanced(v => !v)}>
          {advanced ? "Sade ekrana dön" : "Gelişmiş PDF / poz işlemleri"}
        </button>
      </div>
    </header>
    {advanced ? <ReviewWorkspace projectScope={projectScope ?? projectId}
      onImportSelected={onImportSelected} onSessionExpired={onSessionExpired}/> : <>
      <div className={styles.sourceBar}>
        {!projectScope && <label>Proje
          <select value={projectId} onChange={e => setProjectId(e.target.value)}>
            <option value="">Proje seçin</option>
            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>}
        <label>Excel kaynağı
          <select value={importId} onChange={e => { setOffset(0); setImportId(e.target.value); }}>
            <option value="">Excel seçin</option>
            {imports.map(x => <option key={x.id} value={x.id}>{x.filename} · {x.sheet}</option>)}
          </select>
        </label>
        <button type="button" className="secondary" disabled={busy || !importId} onClick={() => setRefresh(v => v + 1)}>Yenile</button>
      </div>
      {error && <p role="alert" className={styles.error}>{error}{error.includes("Oturum") && <> <Link href="/">Giriş sayfası</Link></>}</p>}
      {busy && <p role="status">Teknik bilgiler yükleniyor…</p>}
      {!busy && !error && !importId && <p className={styles.empty}>Önce bir Excel metrajı seç. Mevcut projenin aktarımları burada görünür.</p>}
      {source && readiness && !busy && <>
        {!opened && <div className={styles.stats} aria-label="Teknik kontrol özeti">
          <div><strong>{source.rows.length}</strong><span>Bu sayfada imalat</span></div>
          <div><strong>{verified}</strong><span>Poz ön uyumu</span></div>
          <div><strong>{missing}</strong><span>Ek inceleme</span></div>
        </div>}
        <nav className={styles.tabs} aria-label="Teknik inceleme bölümleri">
          {([["items","İmalatlar"],["missing","Eksikler"],["decisions","Kararlar"]] as const).map(([key, label]) =>
            <button key={key} type="button" aria-current={tab === key ? "page" : undefined}
              onClick={() => {setTab(key); setOpened(null);}}>
              {label}
            </button>)}
        </nav>
        {selected && item ? <div className={styles.detail}>
          <button type="button" className={styles.back} onClick={() => setOpened(null)}>← Listeye dön</button>
          <div className={styles.detailHeading}>
            <div><span className={styles.kicker}>Excel satırı {selected.source_row}</span>
              <h3>{selected.description}</h3>
              <p>{item.quantity ?? "Miktar eksik"} {item.unit ?? ""} {selected.saved_candidate ? "· Poz " + selected.saved_candidate : ""}</p>
            </div>
            <span className={isPrechecked(selected) ? styles.good : styles.pending}>{title(selected)}</span>
          </div>
          <section className={styles.infoSection}>
            <h4>Belgeden bulunan teknik bilgiler</h4>
            {selected.evidence_facts && Object.entries(selected.evidence_facts).length > 0 ?
              <dl className={styles.factList}>{Object.entries(selected.evidence_facts).map(([key,value]) =>
                <div key={key}><dt>{factLabels[key] ?? key}</dt><dd>{String(value)}</dd></div>)}</dl> :
              <p className={styles.muted}>Bu satır için doğrulanabilir açık belge bilgisi henüz yok.</p>}
            <p className={styles.muted}>Bulunan bilgi tek başına teknik onay değildir.</p>
          </section>
          <section className={styles.infoSection}>
            <h4>Kontrol edilecekler</h4>
            <p>{selected.reason}</p>
            <ul>{selected.checks.map(check => <li key={check}>{check}</li>)}</ul>
          </section>
          <details className={styles.evidence}>
            <summary>Kaynak kanıtları ve PDF sayfası</summary>
            {selected.evidence_page ?
              <p>Proje teknik şartnamesi · PDF sayfa {selected.evidence_page}</p> :
              <p>Bu satır için PDF sayfası belirlenemedi.</p>}
            {selected.evidence_quote ? <blockquote>{selected.evidence_quote}</blockquote> :
              <p className={styles.muted}>Kaynak alıntısı bulunamadı.</p>}
            {readiness.source_sha256 && <small>Şartname SHA-256: {readiness.source_sha256}</small>}
          </details>
          <div className={styles.locked}>Mühendis onayı verilmedi · Kesin maliyet hesabına alınamaz.</div>
          <HandoffDecisionPanel key={selected.work_item_id} projectId={projectId}
            importId={importId} rowId={selected.work_item_id}/>
        </div> : <div className={styles.list}>
          {tab === "decisions" && <p className={styles.muted}>
            {decisionLoading ? "Karar geçmişi yükleniyor…" : "Kayıt varsa tarih ve gerekçesi gösterilir. Ayrıntıları açmak için İncele'ye bas."}
          </p>}
          {shown.length === 0 && <p className={styles.empty}>
            {tab === "missing" ? "Bu sayfadaki imalatlarda ön kontrol bekleyen başka satır yok." : "Bu sayfada imalat bulunamadı."}
          </p>}
          {shown.map(row => {
            const matching = source.rows.find(item => item.work_item_id === row.work_item_id);
            const decision = decisions[row.work_item_id];
            return <article key={row.work_item_id} className={styles.listRow}>
              <div className={styles.rowText}>
                <strong>Satır {row.source_row} · {row.description}</strong>
                <small>{matching?.quantity ?? "—"} {matching?.unit ?? ""} · {row.saved_candidate ?? "Poz bekliyor"}</small>
                <span className={isPrechecked(row) ? styles.good : styles.pending}>{title(row)}</span>
                {tab === "missing" && <p className={styles.muted}>{row.reason}</p>}
                {tab === "decisions" && <p className={styles.muted}>
                  {decision?.latest_event ?
                    actionLabels[decision.latest_event.action] + " · " +
                    new Date(decision.latest_event.created_at).toLocaleString("tr-TR") +
                    " · " + decision.latest_event.reason :
                    decision === undefined ? "Yükleniyor…" : decision === null ? "Karar geçmişi okunamadı." : "Henüz karar kaydı yok."}
                </p>}
              </div>
              <button type="button" className="secondary" onClick={() => setOpened(row.work_item_id)}>İncele</button>
            </article>;
          })}
        </div>}
        <footer className={styles.footer}>
          <span>Her sonuç kaynak kontrolüne tabidir. Otomatik mühendis onayı veya nihai fiyat oluşturulmaz.</span>
          <div className={styles.pager}>
            <button type="button" className="secondary" disabled={busy || offset === 0}
              onClick={() => setOffset(v => Math.max(0, v - 20))}>Önceki</button>
            <span>Sayfa {Math.floor(offset / 20) + 1}</span>
            <button type="button" className="secondary" disabled={busy || source.next_offset === null}
              onClick={() => setOffset(source.next_offset ?? offset)}>Sonraki</button>
          </div>
        </footer>
      </>}
    </>}
  </section>;
}