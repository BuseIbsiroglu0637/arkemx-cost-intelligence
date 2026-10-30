"use client";

import Link from "next/link";
import { reviewFingerprint } from "../review-fingerprint";
import { clearWorkspace, readWorkspace, rememberImport, rememberProject } from "../workspace-context";
import WorkflowNav from "../workflow-nav";
import { useEffect, useRef, useState } from "react";
import styles from "./review.module.css";
import AssessmentPanel from "./assessment-panel";
import M4LinkPanel from "./m4-link-panel";
import HandoffDecisionPanel from "./handoff-decision-panel";

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
  technical_source?: { kind: string; sha256: string; source_id: string; description: string; unit: string; official: boolean } | null;
  source_verification_status?: string; source_rights_status?: string; engineering_status?: string;
  comparison: { status: string; approval_allowed: boolean; blockers: string[]; review_flags: string[]; checks: Check[]; technical_checks: Check[] } | null;
  source_price: { value: string; currency: string; unit: string; source: { filename: string; sha256: string; pdf_page: number; printed_page: number; price_date: string } } | null;
};
type Report = { schema: string; read_only: boolean; approval_allowed: boolean; row_count: number; rows: Row[]; import_source: Source };
type PdfSource = { present: boolean; read_only: boolean; sha256?: string; year?: number; volume?: number; position_count?: number; verified_price_count?: number; uncertain_price_count?: number };
type CandidateCatalog = { version_id: string; institution: string; period: string; year: number; position_count: number; synthetic: boolean };
type CandidateChoice = { code: string; description: string; unit: string; similarity: number; technical_status: "compatible" | "review" | "blocked"; blockers: string[]; review_flags: string[]; source_version_id: string; possible_shared_scope: boolean; source_page?: number; source_price?: string | null; source_price_verified?: boolean; analysis_inputs?: {code:string;description:string;unit:string;quantity:string;unit_price:string;amount:string}[]; scope_excerpt?: string };
type SavedCandidate = { code: string | null; current: boolean; stale: boolean; revision_id: string | null; pdf_sha256: string | null; saved_at: string | null; engineering_approved: false; cost_allowed: false };
type CandidateSaveResponse = { saved: true; approval_allowed: false; engineering_approved: false; cost_allowed: false; work_item_id: string; import_id: string; selection: SavedCandidate };
type CeramicClarification = {
  key: "ceramic_finish"; prompt: string; hint: string;
  options: { code: string; label: string; source_page?: number | null }[];
  approval_allowed: false; cost_allowed: false;
};
type ReviewTriage = {
  group: "needs_info" | "needs_review" | "prechecked";
  reason: string; missing_fields: string[];
  engineering_approved: false; cost_allowed: false;
};
type QueueView = "attention" | "prechecked" | "all";
type ProjectSpec = { present: boolean; filename?: string; sha256?: string; page_count?: number; read_only: true };
type DocumentEvidence = {
  status: "no_document" | "not_found" | "unreadable_text" | "found_for_review" | "conflicting";
  source_row?: number; source_sha256?: string;
  saved_candidate?: string | null;
  candidate_consistency?: "unverified" | "matches_examined_facts" | "conflicts";
  candidate_link_status?: "no_saved_candidate" | "analysis_pdf_missing" | "source_or_revision_changed" | "candidate_not_in_pdf" | "current";
  evidence: { page: number; quote: string; facts: Record<string, string | number | null> }[];
  additional_evidence_count?: number;
  engineering_approved: false; cost_allowed: false;
};
type EngineerHandoff = {
  schema: "arkemx.a327.readiness.v1";
  read_only: true;
  approval_allowed: false;
  engineering_approved: false;
  cost_allowed: false;
  import_id: string;
  source_sha256: string | null;
  document_state: string;
  rows: {
    work_item_id: string;
    source_row: number;
    description: string;
    status: string;
    reason: string;
    checks: string[];
    evidence_page: number | null;
    evidence_facts?: Record<string, string | number>;
    evidence_quote?: string | null;
    saved_candidate: string | null;
    engineering_approved: false;
    cost_allowed: false;
  }[];
};
const handoffFactLabels: Record<string,string> = {
  layer_type: "Sıva türü",
  layer_thickness_mm: "Katman kalınlığı (mm)",
  concrete_class: "Beton sınıfı",
  paint_base: "Boya türü",
  coat_count: "Boya kat sayısı",
};
type CandidateResponse = { read_only: boolean; approval_allowed: boolean; cost_allowed: boolean; import_source: Source; catalog: { version_id: string; synthetic: boolean }; rows: { work_item_id: string; source_row: number; revision_id: string | null; suggestions: CandidateChoice[]; saved_selection?: SavedCandidate | null; clarification?: CeramicClarification | null; triage?: ReviewTriage; related_excel_rows?: number[]; review_summary?: string | null }[] };
type SavedList = { read_only: boolean; approval_allowed: boolean; records: { id: string; title: string; created_at: string; row_count: number }[]; next_offset: number | null };
type SavedReview = { schema: string; read_only: boolean; approval_allowed: boolean; record: { id: string; title: string; created_at: string; snapshot_sha256: string; row_count: number }; report: Report; currentness: { status: string; flags: string[]; engineering_approval: boolean }; resume_allowed: boolean; resume_rows: Item[] };
const freshnessLabels: Record<string, string> = {
  SYNTHETIC_SOURCE_CHANGED: "ARKEMX sentetik test tarifinin sürümü değişti.",
  METRAJ_CHANGED: "Metraj veya satır revizyonu değişti.", PDF_CHANGED: "PDF kaynak dosyası değişti.",
  PDF_UNVERIFIED: "Güncel PDF kaynağı doğrulanamadı.", ENGINE_CHANGED: "Karşılaştırma kuralları değişti.",
  ENGINE_UNVERIFIED: "Motor sürümü doğrulanamadı.", IMPORT_CHANGED: "Excel kaynak kimliği değişti.",
  IMPORT_EXCLUDED: "Bu Excel yeni analizlere kapatılmış.", IMPORT_NOT_AVAILABLE: "Excel kaynağı bulunamadı.", ROW_NOT_AVAILABLE: "Kaydedilen satırlardan biri artık bulunamıyor.",
};
type View = "attention" | "all" | "checked_features_match" | "incompatible" | "review_required" | "out_of_scope";
const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const LABELS: Record<string, string> = {
  checked_features_match: "Kontrol edilen özellikler eşleşti", incompatible: "Teknik uyumsuzluk",
  review_required: "İnceleme gerekli", out_of_scope: "Kapsam dışı", verified: "Kaynak kimliği doğrulandı", not_applicable: "Test kaynağı · fiyat yok",
  not_available: "Kaynak yok", not_configured: "Kaynak tanımlanmamış", unverified: "Kaynak doğrulanamadı",
  match: "Eşleşiyor", block: "Uyuşmazlık", review: "İnceleme gerekli",
  work_type: "İmalat türü", thickness_mm: "Kalınlık (mm)", materials: "Malzeme",
  cement_dosage_kg: "Çimento miktarı (kg; tarifteki kum dayanağıyla)", environment: "Uygulama yeri",
  material_scope: "Malzeme kapsamı", work_scope_ince_siva: "İnce sıva kapsamı", work_scope_kaba_siva: "Kaba sıva kapsamı",
  included: "Kapsamda", excluded: "Kapsam dışı", kaba_siva: "Kaba sıva", ince_siva: "İnce sıva",
  siva: "Sıva", cimento: "Çimento", alci: "Alçı", gazbeton: "Gazbeton", ic: "İç", dis: "Dış",
  gazbeton_strength_n_mm2: "Gazbeton dayanımı (N/mm²)",
  gazbeton_density_kg_m3: "Gazbeton yoğunluğu (kg/m³)",
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
    <details className={styles.notice} aria-label="Kaynak ve onay durumu"><summary>Kaynak doğrulaması ve onay ayrıntıları</summary>
      <strong>{row.technical_source?.kind === "synthetic_owned" ? "ARKEMX'e ait sentetik test verisi" : row.technical_source?.kind === "analysis_pdf" || row.source_price ? "Gerçek PDF analiz kaynağı" : "Teknik kaynak doğrulanmadı"}</strong>
      <p>Belge / tarif doğrulaması: {label(row.source_verification_status ?? row.price_source_status)}</p>
      <p>Kullanım durumu: {row.source_rights_status === "owned_synthetic_fixture" ? "Sabit ARKEMX test tarifi; yalnızca sentetik pilotta kullanılır." : "Bu A3 sonucu kullanım iznini doğrulamaz. Katalog kullanım onayı ayrı kontrol edilir."}</p>
      <p>Mühendis onayı: Verilmedi.</p>
      {row.technical_source?.kind === "synthetic_owned" && <p>Resmî poz veya fiyat değildir. PDF'den alınmamıştır ve maliyet fiyatı içermez.</p>}
      {row.technical_source && <details><summary>Teknik tarif kaynak kimliği</summary><p>{row.technical_source.source_id}</p><code>{row.technical_source.sha256}</code></details>}
    </details>
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

type ReviewWorkspaceProps = {
  projectScope?: string;
  onImportSelected?: (label: string) => void;
  onSessionExpired?: () => void;
};

export default function ReviewWorkspace({ projectScope, onImportSelected, onSessionExpired }: ReviewWorkspaceProps = {}) {
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
  const [savedCandidates, setSavedCandidates] = useState<Record<string, string>>({});
  const [pdfSource, setPdfSource] = useState<PdfSource | null>(null);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [specFile, setSpecFile] = useState<File | null>(null);
  const [projectSpec, setProjectSpec] = useState<ProjectSpec | null>(null);
  const [specEvidence, setSpecEvidence] = useState<{ rowId: string; data: DocumentEvidence } | null>(null);
  const [engineerHandoff, setEngineerHandoff] = useState<EngineerHandoff | null>(null);
  const [pdfRightsConfirmed, setPdfRightsConfirmed] = useState(false);
  const [catalogs, setCatalogs] = useState<CandidateCatalog[]>([]);
  const [catalogVersion, setCatalogVersion] = useState("");
  const [autoCandidates, setAutoCandidates] = useState<CandidateResponse | null>(null);
  const [queueView, setQueueView] = useState<QueueView>("attention");
  const [autoMessage, setAutoMessage] = useState("");
  const [rowSearch, setRowSearch] = useState("");
  const [autoFilter, setAutoFilter] = useState<"all" | "suggested" | "review" | "none">("all");
  const [candidateDetailId, setCandidateDetailId] = useState<string | null>(null);
  const [bulkCode, setBulkCode] = useState("");
  const [bulkMode, setBulkMode] = useState<"empty" | "replace">("empty");
  const [report, setReport] = useState<Report | null>(null);
  const [view, setView] = useState<View>("attention");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const requestRef = useRef<AbortController | null>(null);
  const automaticRunKeyRef = useRef("");
  const saveGeneration = useRef(0);
  const saveAttempt = useRef<{ basis: string; key: string } | null>(null);
  const [recordTitle, setRecordTitle] = useState("");
  const [savedList, setSavedList] = useState<SavedList | null>(null);
  const [archive, setArchive] = useState<SavedReview | null>(null);
  const [archiveRow, setArchiveRow] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState("");

  function clearResult() { saveGeneration.current += 1; setReport(null); setDetailId(null); setSaveNotice(""); }
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
        headers: { Authorization: `Bearer ${token}`, ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) } });
      if (controller.signal.aborted || requestRef.current !== controller || sessionStorage.getItem("arkemx_dev_token") !== token) return;
      if (response.status === 401) {
        sessionStorage.removeItem("arkemx_dev_token"); clearWorkspace(); setAuthenticated(false);
        setSelection(null); setProjects([]); setImports([]); setSelected([]); setArchive(null); setSavedList(null); clearResult();
        onSessionExpired?.();
        throw new Error("Oturum süresi doldu. Ana çalışma alanından yeniden giriş yap.");
      }
      if (!response.ok) {
        if ((response.status === 403 || response.status === 404 || response.status === 409) && task === "items") {
          const currentProject = readWorkspace(token)?.projectId;
          if (currentProject) rememberImport(token, currentProject, null);
          setImportId(""); setSelection(null);
        }
        const messages: Record<number, string> = task === "pdf-upload" ? {
          403: "PDF için gerekli işleme izni ve yönetici yetkisi doğrulanmalı.",
          413: "PDF dosyası 16 MB sınırını aşıyor.",
          422: "PDF dosyası okunamadı veya 2026 analiz yapısı doğrulanamadı.",
          409: "PDF kaynak klasöründe güvenlik kontrolü başarısız.",
        } : task === "spec-upload" ? {
          403: "Şartnameyi yalnızca yetkili yönetici yerel ortamda bağlayabilir.",
          413: "Şartname PDF dosyası 8 MB sınırını aşıyor.",
          415: "Yalnızca PDF şartname yüklenebilir.",
          422: "PDF okunamadı, taranmış veya desteklenmeyen bir belge olabilir.",
        } : {
          403: "Bu işlem için erişim izni bulunmuyor.", 404: "Proje, aktarım veya seçilen satır bulunamadı.",
          409: task === "candidate-save" ? "PDF veya metraj revizyonu değişti. Yenileyip yeniden seç." : task === "save" ? "Önizleme veya kaynak değişmiş olabilir. Güncel teknik incelemeyi yeniden çalıştırıp kaydet." : task === "archive" ? "Kayıt bütünlüğü doğrulanamadı; eski sonuç gösterilmedi." : "Revizyon değişmiş veya aktarım incelemeye kapatılmış olabilir. Satırları yeniden yükle.",
          422: task === "candidate-save" ? "Bu poz metrajla teknik olarak uyuşmuyor veya PDF’de bulunmuyor. Farklı bir aday seç." : "Seçimi kontrol et. Bir incelemede 1–20 farklı satır ve geçerli aday kodları kullanılmalı.",
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
        if (projectScope) {
          if (!data.some(project => project.id === projectScope)) throw new Error("Seçili projeye erişim doğrulanamadı.");
          chooseProject(projectScope, saved?.projectId === projectScope ? saved.importId : null);
        } else if (saved && data.some(project => project.id === saved.projectId)) chooseProject(saved.projectId, saved.importId);
        else if (saved) clearWorkspace();
      }, "projects");
    }
    return () => { requestRef.current?.abort(); requestRef.current = null; };
    // The initial request reads the current session; later reloads are explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function chooseProject(id: string, rememberedImport: string | null = null) {
    setArchive(null); setSavedList(null); setArchiveRow(null);
    invalidate(); setProjectId(id); setImports([]); setImportId(""); setSelection(null); setSelected([]); setCandidates({}); setSavedCandidates({}); setOffset(0);
    setCatalogs([]); setCatalogVersion(""); setPdfSource(null); setPdfFile(null); setPdfRightsConfirmed(false); setSpecFile(null); setProjectSpec(null); setSpecEvidence(null); setEngineerHandoff(null); setAutoCandidates(null); setAutoMessage(""); automaticRunKeyRef.current = "";
    setCandidateDetailId(null); setRowSearch(""); setAutoFilter("all");
    setBulkCode("");
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (token) rememberProject(token, id);
    if (id) void request<Import[]>(`/api/projects/${encodeURIComponent(id)}/imports`, data => {
      setImports(data);
      if (rememberedImport && data.some(item => item.id === rememberedImport)) loadItems(rememberedImport, 0, id);
      else if (projectScope && data.length) loadItems(data[0].id, 0, id);
      else if (token) rememberImport(token, id, null);
    }, "imports");
  }
  function loadItems(id: string, pageOffset = 0, sourceProject = projectId) {
    setArchive(null); setSavedList(null); setArchiveRow(null);
    invalidate(); setImportId(id); setSelection(null); setSelected([]); setCandidates({}); setSavedCandidates({}); setOffset(pageOffset);
    setAutoCandidates(null); setAutoMessage(""); setSpecEvidence(null); setEngineerHandoff(null); automaticRunKeyRef.current = "";
    setCandidateDetailId(null); setRowSearch(""); setAutoFilter("all");
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (token) rememberImport(token, sourceProject, null);
    if (id) void request<Selection>(`/api/projects/${encodeURIComponent(sourceProject)}/a3/imports/${encodeURIComponent(id)}/items?limit=20&offset=${pageOffset}`, data => {
      if (data.read_only !== true || data.approval_allowed !== false || data.import_source.import_id !== id || data.import_source.project_id !== sourceProject || data.rows.length > 20) throw new Error("Satır kaynağı doğrulanamadı.");
      setSelection(data);
      if (token) rememberImport(token, sourceProject, id);
      loadPdfSource(sourceProject);
    }, "items");
  }
  function loadPdfSource(id: string) {
    void request<PdfSource>(`/api/projects/${encodeURIComponent(id)}/a318/source`, data => {
      if (data.read_only !== true) throw new Error("PDF kaynak doğrulaması başarısız.");
      setPdfSource(data);
    }, "pdf-source");
  }

  function uploadSpecification() {
    if (!projectId || !specFile || busy) return;
    const form = new FormData();
    form.append("file", specFile);
    void request<ProjectSpec>(
      `/api/projects/${encodeURIComponent(projectId)}/a326/source`,
      data => {
        if (!data.present || !data.sha256 || data.read_only !== true) {
          throw new Error("Teknik şartname doğrulanamadı.");
        }
        setProjectSpec(data);
        setSpecFile(null);
        setSpecEvidence(null);
        setEngineerHandoff(null);
        setSaveNotice("Proje şartnamesi bağlandı. 'Belgede ara' ile kanıtları kontrol et.");
      }, "spec-upload", { method: "POST", body: form },
    );
  }
  function findSpecificationEvidence(id: string) {
    if (!projectId || !importId || busy) return;
    setSpecEvidence(null);
    void request<DocumentEvidence>(
      `/api/projects/${encodeURIComponent(projectId)}/a326/imports/${encodeURIComponent(importId)}/items/${encodeURIComponent(id)}/evidence`,
      data => {
        if (data.engineering_approved !== false || data.cost_allowed !== false) {
          throw new Error("Teknik doğrulama sonucu beklenmeyen onay içeriyor.");
        }
        setSpecEvidence({ rowId: id, data });
        if (data.source_sha256) setProjectSpec(old =>
          old?.sha256 === data.source_sha256 ? old : {
            present: true, sha256: data.source_sha256, filename: "Proje şartnamesi.pdf",
            read_only: true,
          });
      }, "spec-evidence",
    );
  }
  function loadEngineerHandoff() {
    if (!projectId || !importId || !selection || busy) return;
    setEngineerHandoff(null);
    void request<EngineerHandoff>(
      `/api/projects/${encodeURIComponent(projectId)}/a327/imports/${encodeURIComponent(importId)}/readiness?offset=${offset}&limit=20`,
      data => {
        if (data.schema !== "arkemx.a327.readiness.v1" ||
            data.import_id !== importId || data.read_only !== true ||
            data.approval_allowed !== false || data.engineering_approved !== false ||
            data.cost_allowed !== false ||
            data.rows.some(row => row.engineering_approved !== false || row.cost_allowed !== false) ||
            data.rows.length !== selection.rows.length ||
            data.rows.some((row, index) => row.work_item_id !== selection.rows[index].work_item_id)) {
          throw new Error("Mühendis hazırlık listesi aktif Excel ile doğrulanamadı.");
        }
        setEngineerHandoff(data);
      }, "engineer-readiness",
    );
  }
  function attachPdf() {
    if (!projectId || !pdfFile || !pdfRightsConfirmed || busy) return;
    const form = new FormData();
    form.append("file", pdfFile);
    form.append("rights_confirmed", "true");
    void request<PdfSource>(`/api/projects/${encodeURIComponent(projectId)}/a318/source`, data => {
      if (!data.present || !data.sha256 || !data.position_count || data.read_only !== true) {
        throw new Error("PDF analizi doğrulanamadı.");
      }
      automaticRunKeyRef.current = "";
      setPdfSource(data);
      setPdfFile(null);
      setPdfRightsConfirmed(false);
      // Old source candidates must never survive an explicit PDF replacement.
      setCandidates({});
      setSavedCandidates({});
      setSelected([]);
      setAutoCandidates(null);
      setEngineerHandoff(null);
      setQueueView("attention");
      setCandidateDetailId(null);
      setAutoMessage("PDF bağlandı. Excel satırları otomatik eşleştiriliyor.");
    }, "pdf-upload", { method: "POST", body: form });
  }
  function findAutomaticCandidates() {
    if (!selection || !projectId || !importId || !pdfSource?.present || !pdfSource.sha256 || busy) return;
    const source = selection;
    const sourceSha = pdfSource.sha256;
    clearResult();
    setAutoCandidates(null);
    void request<CandidateResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/a318/imports/${encodeURIComponent(importId)}/suggestions?offset=${offset}`,
      data => {
        const expected = new Map(source.rows.map(row => [row.work_item_id, row]));
        if (
          data.read_only !== true || data.approval_allowed !== false || data.cost_allowed !== false
          || data.import_source.import_id !== source.import_source.import_id
          || data.import_source.sha256 !== source.import_source.sha256
          || data.catalog.version_id !== sourceSha || data.catalog.synthetic !== false
          || data.rows.length !== source.rows.length
          || new Set(data.rows.map(row => row.work_item_id)).size !== source.rows.length
          || data.rows.some(row => {
            const original = expected.get(row.work_item_id);
            return !original || original.revision_id !== row.revision_id
              || original.source_row !== row.source_row || row.suggestions.length > 3
              || !row.triage
              || !["needs_info", "needs_review", "prechecked"].includes(row.triage.group)
              || row.triage.engineering_approved !== false || row.triage.cost_allowed !== false
              || (row.triage.group === "prechecked" && !row.saved_selection?.current);
          })
        ) throw new Error("Öneriler özgün Excel kaynağıyla uyuşmuyor.");
        setAutoCandidates(data);
        setCandidateDetailId(prev => prev && data.rows.some(row => row.work_item_id === prev) ? prev : null);
        setAutoFilter("all");
        const restored = data.rows.flatMap(row => {
          const saved = row.saved_selection;
          return saved?.current && saved.code && saved.pdf_sha256 === sourceSha &&
            saved.revision_id === row.revision_id && !saved.engineering_approved && !saved.cost_allowed
            ? [{ id: row.work_item_id, code: saved.code }] : [];
        });
        setSavedCandidates(Object.fromEntries(restored.map(row => [row.id, row.code])));
        // Only preselect unambiguous, strongly similar, non-blocked candidates.
        // Rows with technical unknowns remain visible but are never approved.
        const selectedCandidates = data.rows.flatMap(row => {
          const [top, second] = row.suggestions;
          return !row.clarification && top && top.technical_status === "compatible" &&
            !top.possible_shared_scope && top.similarity >= 0.5 &&
            (!second || top.similarity - second.similarity >= 0.12)
            ? [{ id: row.work_item_id, code: top.code }] : [];
        });
        setCandidates(Object.fromEntries([
          ...selectedCandidates.map(item => [item.id, item.code] as const),
          ...restored.map(item => [item.id, item.code] as const),
        ]));
        setSelected([...new Set([...selectedCandidates.map(item => item.id), ...restored.map(item => item.id)])]);
        setAutoMessage("Otomatik poz taraması tamamlandı. Teknik açıdan belirsiz eşleşmeler inceleme için ayrıldı.");
      }, "auto"
    );
  }

  // Run automatically once per Excel import, page, source revision and catalog.
  // Never create a synthetic catalog or accept a cost decision automatically.
  useEffect(() => {
    if (!selection || !projectId || !importId || !pdfSource?.present || !pdfSource.sha256 || !authenticated || !ready || busy) return;
    const key = [
      projectId, importId, selection.import_source.sha256,
      offset, pdfSource.sha256, ...selection.rows.map(row => row.work_item_id + ":" + (row.revision_id ?? "")),
    ].join("|");
    if (automaticRunKeyRef.current === key) return;
    automaticRunKeyRef.current = key;
    findAutomaticCandidates();
    // The trigger is the verified source and catalog identity, not manual inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, projectId, importId, pdfSource, offset, busy, authenticated, ready]);

  function toggle(id: string, checked: boolean) {
    invalidate(); setSelected(prev => checked ? [...new Set([...prev, id])] : prev.filter(value => value !== id));
  }
  function saveCandidate(id: string, code: string) {
    if (!selection || !projectId || !importId || !pdfSource?.sha256 || busy) return;
    const item = selection.rows.find(row => row.work_item_id === id);
    if (!item || !code.trim()) return;
    const sourceSha = pdfSource.sha256;
    const targetCode = code.trim();
    clearResult();
    void request<CandidateSaveResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/a318/imports/${encodeURIComponent(importId)}/items/${encodeURIComponent(id)}/candidate`,
      data => {
        if (data.saved !== true || data.approval_allowed !== false ||
            data.engineering_approved !== false || data.cost_allowed !== false ||
            data.work_item_id !== id || data.import_id !== importId ||
            data.selection.current !== true || data.selection.code !== targetCode ||
            data.selection.pdf_sha256 !== sourceSha || data.selection.revision_id !== item.revision_id) {
          throw new Error("Kaydedilen pozun kaynak doğrulaması başarısız.");
        }
        setCandidates(prev => ({ ...prev, [id]: targetCode }));
        setSavedCandidates(prev => ({ ...prev, [id]: targetCode }));
        setSpecEvidence(null); // Old evidence comparison was for the previous chosen code.
        setEngineerHandoff(null);
        setSelected(prev => [...new Set([...prev, id])]);
        setSaveNotice(`${targetCode} inceleme için kaydedildi. Mühendis onayı verilmedi.`);
        automaticRunKeyRef.current = ""; // Read current triage from the server after saving.
      }, "candidate-save", {
        method: "POST", body: JSON.stringify({
          position_code: targetCode, expected_revision_id: item.revision_id,
          expected_pdf_sha256: sourceSha,
        }),
      }
    );
  }
  function candidate(id: string, value: string) {
    invalidate(); setCandidates(prev => ({ ...prev, [id]: value }));
    setSelected(prev => [...new Set([...prev, id])]);
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
  function listSaved(offset = 0) {
    if (!projectId || !importId) return;
    void request<SavedList>(`/api/projects/${encodeURIComponent(projectId)}/a3/imports/${encodeURIComponent(importId)}/reviews?offset=${offset}`, data => {
      if (data.read_only !== true || data.approval_allowed !== false || data.records.length > 20) throw new Error("Kayıt listesi doğrulanamadı.");
      setSavedList(previous => offset && previous ? { ...data, records: [...previous.records, ...data.records] } : data);
    }, "history");
  }
  function acceptArchive(data: SavedReview) {
    if (data.read_only !== true || data.approval_allowed !== false || data.currentness.engineering_approval !== false ||
        data.report.approval_allowed !== false || data.report.import_source.project_id !== projectId || data.report.import_source.import_id !== importId ||
        data.report.rows.some(row => row.approval_allowed !== false)) throw new Error("Kayıtlı inceleme doğrulanamadı.");
    setArchive(data); setArchiveRow(data.report.rows[0]?.identity.work_item_id ?? null);
  }
  async function saveReview() {
    if (!report || busy || recordTitle.trim().length < 3) return;
    const source = report;
    const generation = saveGeneration.current;
    const token = sessionStorage.getItem("arkemx_dev_token");
    setBusy("preparing-save"); setError(""); setSaveNotice("");
    try {
      const hash = await reviewFingerprint(source);
      if (saveGeneration.current !== generation || sessionStorage.getItem("arkemx_dev_token") !== token) return;
      const title = recordTitle.trim();
      const basis = `${hash}:${title}`;
      if (saveAttempt.current?.basis !== basis) saveAttempt.current = { basis, key: crypto.randomUUID() };
      const rows = source.rows.map(row => ({ work_item_id: row.identity.work_item_id, candidate_code: row.candidate_code, expected_revision_id: row.identity.revision_id }));
      void request<SavedReview>(`/api/projects/${encodeURIComponent(projectId)}/a3/imports/${encodeURIComponent(importId)}/reviews`, data => {
        acceptArchive(data);
        setSaveNotice("İnceleme sunucuya kaydedildi. Bu kayıt mühendis onayı değildir.");
      }, "save", { method: "POST", body: JSON.stringify({ title, rows, expected_report_sha256: hash, request_key: saveAttempt.current!.key }) });
    } catch (err) {
      if (saveGeneration.current === generation) { setBusy(""); setError(err instanceof Error ? err.message : "Kayıt hazırlanamadı."); }
    }
  }
  function prepareResume() {
    if (!archive?.resume_allowed || busy || archive.resume_rows.length !== archive.record.row_count) return;
    const saved = archive;
    const ids = new Set(saved.report.rows.map(row => row.identity.work_item_id));
    if (saved.resume_rows.some(row => !ids.has(row.work_item_id)) || ids.size !== saved.resume_rows.length) return;
    invalidate();
    setSelection({ schema: "arkemx.batch_review_selection.v1", read_only: true, approval_allowed: false, import_source: saved.report.import_source, rows: saved.resume_rows, next_offset: null });
    setSelected(saved.resume_rows.map(row => row.work_item_id));
    setCandidates(Object.fromEntries(saved.report.rows.map(row => [row.identity.work_item_id, row.candidate_code ?? ""])));
    setOffset(0); setArchive(null); setArchiveRow(null);
    setSaveNotice("Kayıtlı adaylar ve satırların güncel revizyonları yüklendi. Yeni sonucu görmek için ‘Seçilen satırları incele’ düğmesine bas. Eski sonuç aktif sonuca aktarılmadı.");
  }
  function expireSavedSession() {
    invalidate(); clearWorkspace(); setAuthenticated(false); setArchive(null); setSavedList(null);
    setSelection(null); setProjects([]); setImports([]); setSelected([]);
    onSessionExpired?.();
  }
  useEffect(() => {
    onImportSelected?.(selection ? `${selection.import_source.filename} · ${selection.import_source.sheet_name}` : "");
  }, [selection, onImportSelected]);
  const archivedDetail = archive?.report.rows.find(row => row.identity.work_item_id === archiveRow);
  const selectedProject = projects.find(project => project.id === projectId);
  const detail = report?.rows.find(row => row.identity.work_item_id === detailId);
  const filtered = report?.rows.filter(row => view === "all" || (view === "attention" ? row.technical_status !== "checked_features_match" : row.technical_status === view)) ?? [];
  const suggestionsFor = (id: string) =>
    autoCandidates?.rows.find(item => item.work_item_id === id)?.suggestions ?? [];
  const countSuggested = selection?.rows.filter(row => suggestionsFor(row.work_item_id).some(item => item.technical_status !== 'blocked')).length ?? 0;
  const countMissing = autoCandidates ? (selection?.rows.length ?? 0) - countSuggested : 0;
  const triageFor = (id: string): ReviewTriage | undefined =>
    autoCandidates?.rows.find(row => row.work_item_id === id)?.triage;
  const queueCounts = { needs_info: 0, needs_review: 0, prechecked: 0 };
  for (const row of selection?.rows ?? []) {
    const group = triageFor(row.work_item_id)?.group ?? "needs_review";
    queueCounts[group] += 1;
  }
  const visibleQueueRows = selection?.rows.filter(row => {
    const group = triageFor(row.work_item_id)?.group ?? "needs_review";
    return queueView === "all" ||
      (queueView === "prechecked" ? group === "prechecked" : group !== "prechecked");
  }) ?? [];
  const expandedRow = selection?.rows.find(row => row.work_item_id === candidateDetailId);
  const expandedEvidence = expandedRow && specEvidence?.rowId === expandedRow.work_item_id
    ? specEvidence.data : null;
  const expandedClarification = expandedRow
    ? autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.clarification
    : null;
  const expandedSelectedCode = expandedRow ? (candidates[expandedRow.work_item_id] ?? "").trim() : "";
  const expandedSavedCode = expandedRow ? savedCandidates[expandedRow.work_item_id] : undefined;
  const currentEvidenceMatch = Boolean(
    expandedEvidence?.status === "found_for_review" &&
    expandedEvidence?.candidate_link_status === "current" &&
    expandedEvidence?.candidate_consistency === "matches_examined_facts" &&
    expandedEvidence?.saved_candidate &&
    expandedEvidence.saved_candidate === expandedSavedCode &&
    expandedEvidence.saved_candidate === expandedSelectedCode
  );
  const expandedSuggestions = expandedRow
    ? [...suggestionsFor(expandedRow.work_item_id)].sort((a, b) =>
        Number(b.code === expandedSelectedCode) - Number(a.code === expandedSelectedCode))
    : [];
  const views: { key: View; title: string }[] = [{ key: "attention", title: "Farklar ve inceleme" }, { key: "all", title: "Tümü" }, ...["incompatible", "review_required", "out_of_scope", "checked_features_match"].map(key => ({ key: key as View, title: label(key) }))];
  const Container = projectScope ? "div" : "main";
  const Heading = projectScope ? "h2" : "h1";
  return <Container className={projectScope ? styles.page : `page ${styles.page}`}>
    {!projectScope && <><WorkflowNav active="technical" />
    <div className={styles.journey} aria-label="Proje çalışma adımları"><Link href="/#metraj">1. Metrajı hazırla</Link><strong aria-current="step">2. Pozları incele</strong><Link href="/#cost">3. Maliyet</Link></div>
    <Link href="/#technical">← Projedeki poz incelemesine dön</Link></>}
    {!projectScope && <div><span className={styles.eyebrow}>ARKEMX · TEKNİK İNCELEME</span><Heading>Pozları incele</Heading><p>Excel satırlarına uygun poz adaylarını bul; teknik farkları ve kaynak kanıtlarını incele.</p></div>}
    {!ready ? <p role="status">Oturum kontrol ediliyor…</p> : !authenticated ? <section className={styles.card}><h2>ARKEMX oturumu gerekli</h2><p>Tarayıcıdaki ana çalışma alanından giriş yapıp buraya dön. PowerShell oturumu tarayıcıya aktarılmaz.</p><Link href="/">Giriş ekranına git</Link></section> : <>
      <div className={styles.simpleSource}>
        <div className={styles.simpleSourceIdentity}>
          <strong>Excel kaynağı: {selection?.import_source.filename ?? imports.find(item => item.id === importId)?.filename ?? "Henüz seçilmedi"}</strong>
          <span>{selectedProject?.name ?? "Proje seçin"}{selection ? ` · ${selection.import_source.sheet_name}` : ""}</span>
        </div>
        <details className={styles.simpleSourceSettings}><summary>Kaynağı değiştir / geçmiş</summary>
          {!projectScope && <label>Proje
            <select value={projectId} onChange={e => chooseProject(e.target.value)}><option value="">Proje seç</option>
              {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select></label>}
          <label>Excel aktarımı
            <select value={importId} disabled={!projectId || Boolean(busy)} onChange={e => loadItems(e.target.value)}>
              <option value="">Excel seç</option>
              {imports.map(item => <option key={item.id} value={item.id}>{item.filename} · {item.row_count} satır</option>)}
            </select>
          </label>
          <button type="button" className="secondary" disabled={Boolean(busy) || !importId}
            onClick={() => loadItems(importId,offset)}>Excel kayıtlarını yenile</button>
          {selection && <details><summary>Excel kaynak kimliği</summary>
            <p>{selection.import_source.filename} · {selection.import_source.sheet_name}</p>
            <code>{selection.import_source.sha256}</code></details>}
          {importId && <section aria-label="Kayıtlı incelemeler">
            <h3>Kayıtlı incelemeler</h3>
            <button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => listSaved()}>
              Önceki kayıtları göster</button>
            {savedList && (savedList.records.length ? <ul className={styles.resultList}>
              {savedList.records.map(record => <li key={record.id}><strong>{record.title}</strong> · {record.row_count} satır
                <button type="button" className="secondary" disabled={Boolean(busy)}
                  onClick={() => { setArchive(null); void request<SavedReview>(
                    `/api/projects/${encodeURIComponent(projectId)}/a3/reviews/${encodeURIComponent(record.id)}`,
                    acceptArchive, "archive"); }}>Kaydı aç</button></li>)}
              </ul> : <p>Kayıtlı inceleme bulunamadı.</p>)}
            {savedList?.next_offset !== null && savedList?.next_offset !== undefined &&
              <button type="button" className="secondary" disabled={Boolean(busy)}
                onClick={() => listSaved(savedList.next_offset!)}>Daha fazla kayıt</button>}
          </section>}
        </details>
      </div>
      {busy && <p role="status">{busy === "auto" ? "Pozlar otomatik eşleştiriliyor…" :
        busy === "compare" ? "Teknik karşılaştırma hazırlanıyor…" : "Kayıtlar yükleniyor…"}</p>}
      {saveNotice && <p className="success" role="status">{saveNotice}</p>}
      {(!selection && projectId && !busy && imports.length === 0) &&
        <p>Bu projede kayıtlı Excel bulunmuyor. Önce Metraj sayfasından Excel yükle.</p>}
      <div className={styles.infoStrip} role="note">Eşleştirmeler katalogdan otomatik önerilir. Teknik onay veya maliyet hesabı yapılmaz; belirsiz satırlar kontrol için ayrılır.</div>
      {archive && <section className={styles.card} aria-labelledby="archive-heading"><div className={styles.toolbar}><h2 id="archive-heading">Kaydedildiği andaki inceleme · {archive.record.title}</h2><button type="button" className="secondary" onClick={() => setArchive(null)}>Kayıt görünümünü kapat</button></div>
        <p><strong>{archive.currentness.status === "unchanged" ? "Kaydedilen girdilerde değişiklik saptanmadı." : archive.currentness.status === "changed" ? "Kaynak veya kurallar değişmiş. Bu sonuç eski çalışmaya aittir." : "Kaydın güncelliği tamamen doğrulanamadı."}</strong></p>
        <p>Bu bölüm tarihî kaydı gösterir; güncel teknik sonuç veya mühendis onayı değildir.</p>
        {archive.currentness.flags.length > 0 && <ul>{archive.currentness.flags.map(flag => <li key={flag}>{freshnessLabels[flag] ?? flag}</li>)}</ul>}
        <p>Kayıt tarihi: {new Date(archive.record.created_at).toLocaleString("tr-TR")} · {archive.record.row_count} satır</p>
        <details><summary>Kayıt kimliği ve bütünlük kanıtı</summary><code>{archive.record.id}</code><br /><code>{archive.record.snapshot_sha256}</code></details>
        <button type="button" disabled={Boolean(busy) || !archive.resume_allowed} onClick={prepareResume}>Adayları güncel satırlarla yeniden incelemeye hazırla</button>
        <p className="hint">Mevcut kaydedilmemiş aday girişleri bu kayıttaki adaylarla değiştirilir. Sonuç yeniden hesaplanmadan güncel sayılmaz.</p>
        <label>Kaydedilmiş satır<select value={archiveRow ?? ""} onChange={e => setArchiveRow(e.target.value)}>{archive.report.rows.map(row => <option key={row.identity.work_item_id} value={row.identity.work_item_id}>Excel satırı {row.identity.source_row} · {row.candidate_code ?? "Aday yok"} · {label(row.technical_status)}</option>)}</select></label>
        {archivedDetail && <>
          <RowDetail key={`archive-${archive.record.id}-${archiveRow}`} row={archivedDetail} />
          <AssessmentPanel key={`assessment-${archive.record.id}-${archiveRow}`} api={API} projectId={projectId} recordId={archive.record.id}
            itemId={archivedDetail.identity.work_item_id} snapshot={archive.record.snapshot_sha256} candidate={archivedDetail.candidate_code}
            disabled={Boolean(busy)} onExpired={expireSavedSession} />
          <M4LinkPanel key={`m4-link-${archive.record.id}-${archiveRow}`} api={API} projectId={projectId} recordId={archive.record.id}
            itemId={archivedDetail.identity.work_item_id} snapshot={archive.record.snapshot_sha256} candidate={archivedDetail.candidate_code}
            disabled={Boolean(busy)} onExpired={expireSavedSession} />
        </>}
      </section>}
      {selection && <section className={`${styles.card} ${styles.simpleMatch}`} aria-labelledby="rows-heading">
        <div className={styles.simpleMatchHead}>
          <div><h2 id="rows-heading">Otomatik poz eşleştirme</h2>
            <p>Metraj satırları seçili kaynak kataloğuna göre kendiliğinden taranır.</p></div>
          <div className={styles.simpleMatchSummary} role="status">
            {busy === "auto" ? "Pozlar eşleştiriliyor…" :
              autoCandidates ? `${selection.rows.length} imalat tarandı · ${countSuggested} aday bulundu · ${countMissing} aday bulunamadı` :
              pdfSource?.present ? "PDF ile eşleştirme hazırlanıyor…" : "PDF kaynağı bekleniyor"}
          </div>
        </div>
        {pdfSource?.present ? <div className={styles.simpleCatalog}>
          <span>Kaynak: <strong>2026 İnşaat Birim Fiyat Analizleri · Cilt 1</strong>
            {" · "}{pdfSource.position_count} poz · {pdfSource.verified_price_count} fiyat kontrolü geçti
            {pdfSource.uncertain_price_count ? " · " + pdfSource.uncertain_price_count + " fiyat inceleme bekliyor" : ""}
          </span>
          <details><summary>PDF kaynağını güncelle</summary>
            <p>Yeni PDF bağlanırsa otomatik öneriler yeniden hesaplanır.</p>
            <input type="file" accept=".pdf,application/pdf" aria-label="2026 analiz PDF dosyası"
              onChange={event => setPdfFile(event.target.files?.[0] ?? null)} />
            <label className={styles.pdfRights}><input type="checkbox" checked={pdfRightsConfirmed}
              onChange={event => setPdfRightsConfirmed(event.target.checked)} />
              PDF dosyasını işlemek için gerekli hak ve izne sahibim.</label>
            <button type="button" disabled={Boolean(busy) || !pdfFile || !pdfRightsConfirmed} onClick={attachPdf}>PDF kaynağını güncelle</button>
          </details>
        </div> : <div className={styles.simpleMissingSource}>
          <strong>Gerçek pozlar doğrudan 2026 analiz PDF dosyasından okunacak.</strong>
          <p>PDF dosyasını bir kez bağla. Sonra Excel satırları bu belgeden otomatik eşleştirilir.</p>
          <label>2026 İnşaat Birim Fiyat Analizleri · Cilt 1 PDF
            <input type="file" accept=".pdf,application/pdf" aria-label="2026 analiz PDF dosyası"
              onChange={event => setPdfFile(event.target.files?.[0] ?? null)} />
          </label>
          <label className={styles.pdfRights}><input type="checkbox" checked={pdfRightsConfirmed}
            onChange={event => setPdfRightsConfirmed(event.target.checked)} />
            Bu PDF dosyasını işlemek için gerekli hak ve izne sahibim.</label>
          <button type="button" disabled={Boolean(busy) || !pdfFile || !pdfRightsConfirmed} onClick={attachPdf}>PDF dosyasını bağla</button>
          <p className={styles.legalNote}>Belgenin ikinci sayfası işleme ve çoğaltma için yazılı izin şartı içeriyor. Yetkin yoksa onaylama. Bu işlem yalnızca yerel kullanım içindir.</p>
        </div>}
        {autoCandidates && <div className={styles.simpleSourceCitation}>
          Kaynak PDF: {pdfSource?.sha256?.slice(0,12)}… · Teknik onay verilmedi
        </div>}
        {error && <div role="alert" className="error">{error}
          {pdfSource?.present && <button type="button" className="secondary" disabled={Boolean(busy)}
            onClick={() => { automaticRunKeyRef.current = ""; findAutomaticCandidates(); }}>Yeniden dene</button>}
        </div>}

        {autoCandidates && <section className={styles.reviewQueue} aria-label="Teknik kontrol özeti">
          <div className={styles.queueHeading}>
            <div><h3>Teknik kontrol listesi</h3>
              <p>Eksik bilgiler ve kontrol bekleyen işler bir arada. Ön kontrol, mühendis onayı değildir.</p></div>
            <small>Bu sayfada {selection.rows.length} imalat</small>
          </div>
          <div className={styles.queueFilters} role="group" aria-label="Satır durumunu filtrele">
            <button type="button" aria-pressed={queueView === "attention"}
              onClick={() => { setQueueView("attention"); setCandidateDetailId(null); }}>
              <strong>{queueCounts.needs_info + queueCounts.needs_review}</strong>
              <span>Kontrol bekleyen</span>
              <small>{queueCounts.needs_info} eksik bilgi · {queueCounts.needs_review} diğer kontrol</small>
            </button>
            <button type="button" aria-pressed={queueView === "prechecked"}
              onClick={() => { setQueueView("prechecked"); setCandidateDetailId(null); }}>
              <strong>{queueCounts.prechecked}</strong>
              <span>Ön kontrol tamam</span>
              <small>Henüz teknik onay değil</small>
            </button>
            <button type="button" aria-pressed={queueView === "all"}
              onClick={() => { setQueueView("all"); setCandidateDetailId(null); }}>
              <strong>{selection.rows.length}</strong>
              <span>Tüm imalatlar</span>
              <small>Kaynak Excel satırları</small>
            </button>
          </div>
        </section>}
        {autoCandidates && <details className={styles.projectEvidence}>
          <summary>A3.27 · Mühendis incelemesine hazırlık</summary>
          <p>Belgede kanıtı bulunan imalatları ve kontrolü eksik kalanları tek listede gör. Bu işlem teknik onay vermez veya maliyet oluşturmaz.</p>
          <button type="button" className="secondary" disabled={Boolean(busy)} onClick={loadEngineerHandoff}>
            {busy === "engineer-readiness" ? "Kontrol ediliyor…" : "Bu sayfadaki imalatları kontrol et"}
          </button>
          {engineerHandoff && <div className={styles.handoffSummary} role="status">
            <strong>Belge–poz ön karşılaştırması: {engineerHandoff.rows.filter(r => r.status === "documented_for_review").length} satırda kanıt uyumlu · {engineerHandoff.rows.filter(r => r.status !== "documented_for_review").length} satır kontrol bekliyor</strong>
            <div className={styles.handoffRows}>
              {engineerHandoff.rows.map(row => <div key={row.work_item_id} className={styles.handoffRow}>
                <div><strong>Satır {row.source_row} · {row.description}</strong>
                  <small>{row.status === "documented_for_review" ? "Kaynaklı ön kontrol uyumlu · Mühendis incelemesi bekliyor" :
                    row.status === "conflicting" ? "Çelişki var · İnceleme gerekli" :
                    row.status === "manual_review" ? "Belge–poz otomatik kontrolü henüz desteklenmiyor" :
                    row.status === "document_evidence_for_review" ? "Belgelenmiş kısmi teknik bilgi · Poz incelemesi gerekli" :
                    row.status === "needs_candidate" ? "Kaydedilmiş poz bekleniyor" :
                    row.status === "stale_candidate" ? "Poz veya PDF kaynağı güncellenmeli" :
                    row.status === "input_review" ? "Excel girdisi kontrol edilmeli" :
                    "Teknik belge kanıtı bekleniyor"}</small>
                </div>
                <p>{row.reason}</p>
                {row.evidence_facts && Object.keys(row.evidence_facts).length > 0 &&
                  <small>Belgede bulunanlar: {Object.entries(row.evidence_facts)
                    .map(([key, value]) => `${handoffFactLabels[key] ?? key}: ${String(value)}`).join(" · ")}</small>}
                {row.evidence_quote && <small>Kaynak ifadesi: {row.evidence_quote}</small>}
                <small>Kontrol listesi: {row.checks.join(" · ")}
                  {row.evidence_page ? ` · PDF sayfa ${row.evidence_page}` : ""}
                  {row.saved_candidate ? ` · Poz ${row.saved_candidate}` : ""}
                </small>
                <HandoffDecisionPanel projectId={projectId} importId={importId} rowId={row.work_item_id}/>
              </div>)}
            </div>
            <small>Tüm satırlar mühendis kararına tabidir. Eksik bilgiler tahmin edilmez; onay veya fiyat hesabı yapılmadı.</small>
          </div>}
        </details>}
        <div className={styles.tableScroll}><table className={styles.simpleMatchTable}>
          <caption className={styles.srOnly}>Metraj kalemlerine ait otomatik poz adayları ve teknik durumları</caption>
          <thead><tr>
            <th scope="col">İmalat</th><th scope="col">Bulunan poz</th><th scope="col">Durum</th><th scope="col">İşlem</th>
          </tr></thead>
          <tbody>{visibleQueueRows.map(row => {
            const proposed = suggestionsFor(row.work_item_id);
            const reviewRow = autoCandidates?.rows.find(item => item.work_item_id === row.work_item_id);
            const rowTriage = reviewRow?.triage;
            const paired = Boolean(reviewRow?.related_excel_rows?.length);
            const needsCeramicChoice = Boolean(reviewRow?.clarification && !savedCandidates[row.work_item_id]);
            const suitable = proposed.find(item => item.technical_status !== "blocked") ?? null;
            const top = suitable ?? proposed[0] ?? null;
            const selectedCode = candidates[row.work_item_id]?.trim() ?? "";
          const isSaved = Boolean(selectedCode && savedCandidates[row.work_item_id] === selectedCode);
          const hasStaleChoice = Boolean(reviewRow?.saved_selection?.stale);
            const selectedCandidate = proposed.find(item => item.code === selectedCode) ?? null;
            // Once the user selects a code, show that choice rather than the original
            // top lexical suggestion. A manually typed, unverified code stays unverified.
            const manuallyEntered = Boolean(selectedCode && !selectedCandidate);
            const visibleCandidate = selectedCode ? selectedCandidate : top;
            const shared = Boolean(visibleCandidate?.possible_shared_scope);
            const blocked = visibleCandidate?.technical_status === "blocked";
            const missing = Boolean(autoCandidates && !visibleCandidate && !manuallyEntered);
            const gasbetonDetailsMissing = Boolean(visibleCandidate?.review_flags.some(flag =>
              flag === "GAZBETON_STRENGTH_N_MM2_UNVERIFIED" ||
              flag === "GAZBETON_DENSITY_KG_M3_UNVERIFIED"));
            const ambiguous = !selectedCode && gasbetonDetailsMissing &&
              proposed.filter(item => item.technical_status !== "blocked").length > 1;
            const needsReview = manuallyEntered || Boolean(visibleCandidate &&
              (visibleCandidate.technical_status !== "compatible" ||
              shared || paired || visibleCandidate.similarity < 0.5 ||
              row.input_review_required || gasbetonDetailsMissing));
            return <tr key={row.work_item_id}>
              <td className={styles.simpleMatchDescription}>
                <strong>{row.effective_description}</strong>
                <small>Excel {row.source_row} · {row.quantity ?? "Miktar eksik"} {row.unit ?? ""}</small>
              </td>
              <td>
                {manuallyEntered ? <div className={styles.simpleMatchPosition}>
                  <strong>{selectedCode}</strong>
                  <small>Elle girilen poz · PDF adayları arasında doğrulanmadı</small>
                  <em role="status">{isSaved ? "İnceleme için kaydedildi · onaylanmadı" :
                    "Seçildi · henüz kaydedilmedi"}</em>
                </div> : visibleCandidate ? <div className={styles.simpleMatchPosition}>
                  {needsCeramicChoice && !selectedCode ? <>
                    <strong>{proposed.length} olası seramik pozu</strong>
                    <small>Seramik türü projeden doğrulanmalı.</small>
                  </> : ambiguous ? <>
                    <strong>{proposed.filter(item => item.technical_status !== "blocked").length} olası poz</strong>
                    <small>Dayanım ve yoğunluk belirtilmediği için doğru kod kesinleştirilemez.</small>
                  </> : <>
                    <strong>{visibleCandidate.code}</strong>
                    <small title={visibleCandidate.description}>{visibleCandidate.description}</small>
                  </>}
                  {isSaved ? <em role="status">İnceleme için kaydedildi · onaylanmadı</em> :
                    selectedCode ? <em>Seçildi · henüz kaydedilmedi</em> : null}
                  {hasStaleChoice && !isSaved && <em>Eski kayıt geçersiz · yeniden seç</em>}
                </div> :
                  <span className={styles.simpleNoCandidate}>{missing ? "Aday bulunamadı" : "PDF taraması bekleniyor"}</span>}
              </td>
              <td>
                <span className={`${styles.simpleStatus} ${
                  blocked ? styles.simpleStatusBlocked :
                  rowTriage?.group === "prechecked" ? styles.simpleStatusSuggested :
                  rowTriage ? styles.simpleStatusReview :
                  missing || needsReview ? styles.simpleStatusReview :
                  top ? styles.simpleStatusSuggested : styles.simpleStatusPending}`}>
                  {rowTriage?.group === "prechecked" ? "Ön kontrol tamam" :
                    rowTriage?.group === "needs_info" ? "Bilgi eksik" :
                    blocked ? "Teknik uyumsuzluk" :
                    manuallyEntered ? "Poz doğrulanmalı" :
                    paired ? "Birleşik iş kontrolü" :
                    shared ? "Çift fiyatlama riski" :
                    missing ? "İnceleme gerekli" :
                    gasbetonDetailsMissing ? "Teknik bilgi eksik" :
                    needsCeramicChoice ? "Seramik türü sorulmalı" :
                    needsReview || rowTriage?.group === "needs_review" ? "Kontrol gerekli" :
                    visibleCandidate ? "Aday bulundu · onay bekliyor" : "Taranıyor"}
                </span>
                {rowTriage && <small className={styles.queueReason}>{rowTriage.reason}</small>}
              </td>
              <td><button type="button" className={styles.showCandidates}
                aria-expanded={candidateDetailId === row.work_item_id}
                onClick={() => setCandidateDetailId(old => old === row.work_item_id ? null : row.work_item_id)}>
                {candidateDetailId === row.work_item_id ? "Kapat" : "Detay"}
              </button></td>
            </tr>;
          })}</tbody>
        </table></div>
        {autoCandidates && visibleQueueRows.length === 0 && <p className={styles.queueEmpty}>
          {queueView === "prechecked" ? "Henüz ön kontrolü tamamlanmış poz yok. Bu, teknik uygunluk onayı verilmediği anlamına gelmez; eksik bilgiler incelenmeli." :
            "Bu bölümde gösterilecek imalat yok."}
        </p>}
        {expandedRow && <div className={styles.simpleMatchDetail}>
          {autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.review_summary && (
            <div className={styles.reviewReason} role="note">
              {autoCandidates.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.review_summary}
              {Boolean(autoCandidates.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.related_excel_rows?.length) &&
                <small>İlgili Excel satırı: {autoCandidates.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.related_excel_rows?.join(", ")}. Aynı iş olduğu doğrulanmadan fiyatlar birleştirilmeyecek.</small>}
            </div>
          )}
          {triageFor(expandedRow.work_item_id)?.group === "needs_info" && (
            <div className={styles.missingFacts} role="note">
              <strong>Projeden doğrulanması gereken bilgiler</strong>
              <span>{triageFor(expandedRow.work_item_id)?.missing_fields.join(" · ")}</span>
              <small>Bu bilgiler metraj tarifinde yoksa mimari/teknik şartnameye bak. Poz seçmek eksik bilgiyi otomatik doğrulamaz.</small>
            </div>
          )}
          {triageFor(expandedRow.work_item_id)?.group === "needs_info" && (
            <details className={styles.projectEvidence}>
              <summary>Bilgiyi doğrula · Proje şartnamesi PDF</summary>
              <p>Projenin teknik şartnamesini yükle. ARKEMX ilgili ifadeyi sayfasıyla arar; bulması teknik onay değildir.</p>
              <div className={styles.projectEvidenceActions}>
                <label>Şartname PDF (en fazla 8 MB)
                  <input type="file" accept=".pdf,application/pdf"
                    disabled={Boolean(busy)} onChange={event => setSpecFile(event.target.files?.[0] ?? null)} />
                </label>
                <button type="button" disabled={Boolean(busy) || !specFile} onClick={uploadSpecification}>
                  Şartnameyi bağla
                </button>
                <button type="button" disabled={Boolean(busy)}
                  className="secondary" onClick={() => findSpecificationEvidence(expandedRow.work_item_id)}>
                  Belgede ara
                </button>
              </div>
              {projectSpec?.present && <small>Bağlı belge: {projectSpec.filename ?? "Proje şartnamesi PDF"} · Kaynak {projectSpec.sha256?.slice(0,12)}…</small>}
              {expandedEvidence && <div className={styles.projectEvidenceResult} role="status">
                <strong>{expandedEvidence.status === "no_document" ? "Önce proje şartnamesi yükle" :
                  expandedEvidence.status === "not_found" ? "Bilgi bulunamadı · Belge veya proje tarifi kontrol edilmeli" :
                  expandedEvidence.status === "unreadable_text" ? "Bu PDF taranmış olabilir · okunabilir metin bulunamadı" :
                  expandedEvidence.status === "conflicting" ? "Çelişkili teknik bilgiler bulundu" :
                  "Belgede ilgili bilgi bulundu · İnceleme bekliyor"}</strong>
                {(expandedEvidence.status === "found_for_review" || expandedEvidence.status === "conflicting") && (
                  <div className={styles.projectPositionComparison} role="note">
                    <strong>Belge–poz karşılaştırması{expandedEvidence.saved_candidate ? " · " + expandedEvidence.saved_candidate : ""}</strong>
                    {expandedEvidence.status === "conflicting" ? (
                      <p>Şartname içinde çelişkili bilgiler bulundu. Poz uyumu doğrulanamaz; mühendis incelemesi gerekli.</p>
                    ) : expandedEvidence.candidate_link_status !== "current" ? (
                      <p>{expandedEvidence.candidate_link_status === "source_or_revision_changed"
                        ? "Kayıtlı pozun PDF kaynağı veya metraj revizyonu değişmiş. Pozu yeniden incelemek gerekiyor."
                        : expandedEvidence.candidate_link_status === "analysis_pdf_missing"
                        ? "Poz analiz PDF kaynağı bulunamadı; belge ile kayıtlı poz karşılaştırılamıyor."
                        : expandedEvidence.candidate_link_status === "candidate_not_in_pdf"
                        ? "Kayıtlı poz güncel analiz PDF dosyasında bulunamadı."
                        : "Belgede bilgi bulundu fakat bu satıra bağlı güncel ve doğrulanabilir kayıtlı poz bulunamadı. Önce poz adayını kaydet."}</p>
                    ) : !expandedEvidence.saved_candidate ||
                      expandedEvidence.saved_candidate !== expandedSelectedCode ||
                      expandedEvidence.saved_candidate !== expandedSavedCode ? (
                      <p>Belgeyle karşılaştırılan kayıtlı poz, ekranda seçili pozla aynı değil. Kaydedilmiş pozu yenileyip tekrar “Belgede ara” işlemini çalıştır.</p>
                    ) : expandedEvidence.candidate_consistency === "conflicts" ? (
                      <p>Belge ve kayıtlı pozun açık teknik özellikleri uyuşmuyor. İnceleme gerekli.</p>
                    ) : currentEvidenceMatch ? (
                      <p>Kaydedilmiş poz ile teknik şartnamede karşılaştırılan zorunlu özellikler aynı. Excel tarifindeki eksik alanlar belgeyle desteklendi; teknik onay hâlâ bekliyor.</p>
                    ) : (
                      <p>Belgede ilgili bilgiler bulundu ancak pozla gereken tüm özellikler karşılaştırılamadı. Eksikler incelemede kalır.</p>
                    )}
                    <small>Bu karşılaştırma yalnızca kaynaklı ön kontroldür; mühendis onayı ve maliyet hesabı kapalıdır.</small>
                  </div>
                )}
                {expandedEvidence.evidence.map((record, index) => (
                  <div key={record.page + "-" + index} className={styles.projectEvidenceQuote}>
                    <strong>PDF sayfa {record.page}</strong>
                    <p>{record.quote}</p>
                    <small>{Object.entries(record.facts).filter(([,value]) => value !== null).map(([key,value]) =>
                      `${({
                        gazbeton_strength_n_mm2: "Dayanım",
                        gazbeton_density_kg_m3: "Yoğunluk",
                        glaze: "Seramik yüzeyi",
                        color: "Renk",
                        surface: "Bitiş",
                        rectified: "Kenar",
                      } as Record<string, string>)[key] ?? key}: ${value}`).join(" · ")}</small>
                  </div>
                ))}
                {Boolean(expandedEvidence.additional_evidence_count) &&
                  <small>Belgede {expandedEvidence.additional_evidence_count} ek ilgili ifade var; tüm belge incelenmeli.</small>}
                <small>Belgede bilgi bulmak, eksik şartnameyi tamamlamak veya mühendis onayı vermek anlamına gelmez.</small>
              </div>}
            </details>
          )}
          <div className={styles.suggestionTop}><div><h3>Satır {expandedRow.source_row} · Teknik inceleme</h3>
            <p>{expandedRow.effective_description}</p></div>
            <button type="button" className="secondary" onClick={() => setCandidateDetailId(null)}>Kapat</button></div>
          {expandedClarification && <section className={styles.simpleCeramicQuestion} aria-label="Seramik türü seçimi">
            <strong>{expandedClarification.prompt}</strong>
            <p>{expandedClarification.hint}</p>
            <div className={styles.simpleCeramicChoices}>
              {expandedClarification.options.map(option => <button type="button"
                key={option.code} disabled={Boolean(busy)}
                aria-pressed={savedCandidates[expandedRow.work_item_id] === option.code}
                onClick={() => saveCandidate(expandedRow.work_item_id, option.code)}>
                <span>{option.label}</span>
                <small>{option.code} · PDF sayfa {option.source_page ?? "—"}</small>
                {savedCandidates[expandedRow.work_item_id] === option.code && <em>İnceleme için kaydedildi</em>}
              </button>)}
            </div>
            <small>Projede özellik belirtilmemişse hiçbirini seçme. Poz kaydı teknik onay değildir.</small>
          </section>}
          {expandedSelectedCode && <div className={styles.chosenCandidateNotice} role="status">
            {savedCandidates[expandedRow.work_item_id] === expandedSelectedCode ? "İnceleme için kaydedildi" : "Henüz kaydedilmedi"}:
            <strong> {expandedSelectedCode}</strong> · Teknik onay verilmedi.
            {!expandedSuggestions.some(option => option.code === expandedSelectedCode) &&
              <small>Bu kod önerilen PDF adayları arasında bulunmuyor; ayrıca doğrulanmalı.</small>}
          </div>}
          {expandedSuggestions.length ? <>
            {expandedSuggestions.slice(0,1).map(option =>
              <div key={option.code} className={styles.simplePrimaryCandidate}>
                <div>
                  <strong>Olası poz: {option.code}</strong>
                  <p>{option.description}</p>
                  <span className={styles.simpleStatus + " " +
                    (option.technical_status === "blocked" ? styles.simpleStatusBlocked : styles.simpleStatusReview)}>
                    {option.technical_status === "blocked" ? "Teknik uyumsuzluk" :
                      currentEvidenceMatch && option.code === expandedEvidence?.saved_candidate
                        ? "Şartname–poz ön kontrolü uyumlu · Mühendis incelemesi" :
                      option.review_flags.some(flag => flag.startsWith("GAZBETON_")) ? "Dayanım / yoğunluk kontrolü gerekli" :
                      "Mühendis kontrolü gerekli"}
                  </span>
                  {[...option.blockers, ...option.review_flags].length > 0 && (
                    <p className={styles.issues}>
                      {currentEvidenceMatch && option.code === expandedEvidence?.saved_candidate &&
                        "Aşağıdaki uyarılar yalnızca özgün Excel tarifine göredir; teknik şartnameden bulunan özellikler yukarıda ayrı karşılaştırıldı. "}
                      {[...option.blockers, ...option.review_flags].map(value => label(value)).join(" · ")}
                    </p>
                  )}
                  <small>PDF sayfa {option.source_page ?? "—"} ·
                    {option.source_price_verified && option.source_price ?
                      " Kaynak fiyat " + option.source_price + " TL/" + option.unit : " Fiyat doğrulanmadı"}
                  </small>
                </div>
                <details>
                  <summary>PDF kanıtı ve analiz girdileri</summary>
                  {option.scope_excerpt && <p>{option.scope_excerpt}</p>}
                  {option.analysis_inputs && <ul>{option.analysis_inputs.map((input, i) =>
                    <li key={input.code + "-" + i}>{input.code} · {input.description}: {input.quantity} {input.unit} × {input.unit_price} TL = {input.amount} TL</li>)}</ul>}
                </details>
                <button type="button" disabled={Boolean(busy)}
                  onClick={() => saveCandidate(expandedRow.work_item_id, option.code)}>
                  {savedCandidates[expandedRow.work_item_id] === option.code ? "İnceleme için kaydedildi" : "Bu adayı kaydet"}
                </button>
              </div>)}
            {expandedSuggestions.length > 1 && <details className={styles.otherCandidates}>
              <summary>Diğer {expandedSuggestions.length - 1} adayı göster</summary>
              {expandedSuggestions.slice(1).map(option =>
                <div key={option.code} className={styles.otherCandidateRow}>
                  <div><strong>{option.code}</strong> · {option.description}
                    <small>{option.technical_status === "blocked" ? "Teknik uyumsuzluk" : "Teknik inceleme gerekli"} · PDF sayfa {option.source_page ?? "—"}</small>
                  </div>
                  <button type="button" className="secondary" disabled={Boolean(busy)}
                    onClick={() => saveCandidate(expandedRow.work_item_id, option.code)}>{savedCandidates[expandedRow.work_item_id] === option.code ? "Kaydedildi" : "Bu adayı kaydet"}</button>
                </div>)}
            </details>}
          </> : <p>Bu satır için uygun poz doğrulanamadı. Teknik tarif veya poz ayrıca incelenmeli.</p>}
          <details><summary>Manuel poz kodu gir (gerekirse)</summary>
            <label>Poz kodu<input maxLength={80} disabled={Boolean(busy)}
              value={candidates[expandedRow.work_item_id] ?? ""} placeholder="Poz kodu"
              onChange={e => candidate(expandedRow.work_item_id, e.target.value)} /></label>
            <button type="button" disabled={Boolean(busy) || !expandedSelectedCode ||
              savedCandidates[expandedRow.work_item_id] === expandedSelectedCode}
              onClick={() => saveCandidate(expandedRow.work_item_id, expandedSelectedCode)}>
              {savedCandidates[expandedRow.work_item_id] === expandedSelectedCode ? "Kaydedildi" : "Poz seçimini kaydet"}
            </button>
            <small>Yalnızca bağlı PDF'deki pozlar kaydedilir. Teknik onay değildir.</small>
          </details>
          <details><summary>İleri teknik inceleme</summary>
            <button type="button" disabled={Boolean(busy)} onClick={() => {
              setSelected([expandedRow.work_item_id]);
              setCandidateDetailId(null);
            }}>Satırı incelemeye hazırla</button>
          </details>
        </div>}
        {autoMessage && <p role="status" className={styles.simpleFootnote}>{autoMessage}</p>}
        <div className={styles.tableFooter}>
          <span>{selection.rows.length} satır · {Math.floor(offset / 20)+1}. sayfa</span>
          <div className={styles.pager}>
            <button type="button" className="secondary" disabled={Boolean(busy) || offset === 0}
              onClick={() => loadItems(importId, Math.max(0,offset-20))}>← Önceki</button>
            <button type="button" className="secondary" disabled={Boolean(busy) || selection.next_offset === null}
              onClick={() => loadItems(importId,selection.next_offset ?? 0)}>Sonraki →</button>
          </div>
        </div>
        <details className={styles.helpCard}>
          <summary>Teknik inceleme ve kanıtlar (isteğe bağlı)</summary>
          <p>Bu listede pozlar otomatik önerilir. Seçilen poz mühendis tarafından ayrıca doğrulanmadan maliyete aktarılmaz.</p>
          <p>Teknik inceleme mevcut pilotun desteklediği pozlarla sınırlıdır. Teknik kanıtlar desteklenmeyen pozlar için otomatik onay üretmez.</p>
          <button type="button" disabled={Boolean(busy) || !selection.rows.length}
            onClick={() => {
              setSelected(selection.rows.map(row => row.work_item_id));
            }}>Tüm satırları teknik incelemeye hazırla</button>
          <div className={styles.primaryAction}>
            <span>{selected.length} satır incelemeye hazır</span>
            <button type="button" disabled={Boolean(busy) || selected.length === 0}
              onClick={compare}>Teknik karşılaştırmayı aç →</button>
          </div>
        </details>
      </section>}
      {report && <div className={styles.workbench}><section className={styles.card} aria-labelledby="results-heading"><h2 id="results-heading">3. Güncel önizleme sonucu</h2><p>{report.row_count} seçili satır değerlendirildi. “Kontrol edilen özellikler eşleşti” tam teknik uygunluk veya onay anlamına gelmez.</p>
        <div className={styles.bulkPanel}><label>İnceleme adı<input maxLength={120} value={recordTitle} disabled={Boolean(busy)} onChange={e => setRecordTitle(e.target.value)} placeholder="Örn. Sıva katmanları ilk inceleme" /></label><button type="button" disabled={Boolean(busy) || recordTitle.trim().length < 3} onClick={() => void saveReview()}>İncelemeyi kaydet</button><p className="hint">Sunucu sonucu yeniden doğrular ve yeni, değiştirilemez bir kayıt oluşturur. Mühendis kararı veya maliyet taslağı oluşturmaz.</p></div>
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
        {detail ? <><div className={styles.nextAction}><strong>Excel satırı {detail.identity.source_row} · Sonraki işlem</strong><p>{detail.flags.includes("CANDIDATE_NOT_SELECTED") ? "Bu satır için aday poz kodu belirle ve yeniden incele." : detail.technical_status === "incompatible" ? "Uyuşmazlığı incele; tarifi veya aday pozu değiştirmek gerekiyorsa kaynak kaydı düzelt." : detail.technical_status === "out_of_scope" ? "Bu aday pilot kapsamının dışında. Bağımsız mühendis incelemesi gerekir." : detail.technical_status === "review_required" ? "Eksik veya belirsiz bilgileri aşağıdaki gerekçelerden kontrol et." : "Kontrol edilen özellikler eşleşti. Bu önizleme henüz mühendis kararına veya maliyet taslağına aktarılamaz."}</p><p className="hint">Sayfadan ayrılmadan önce “İncelemeyi kaydet” ile çalışmanı saklayabilirsin. Kaydedilen incelemede mühendis adayı bağlantısı ayrıca kontrol edilir; onay otomatik verilmez.</p></div><RowDetail key={detail.identity.work_item_id} row={detail} /></> : <div className={styles.card}><h2>Satırın kanıtları</h2><p>Soldaki listeden “Kanıtları aç” seç. Teknik farklar ve özgün ifadeler burada görünecek.</p></div>}
      </aside></div>}
    </>}
  </Container>;
}
