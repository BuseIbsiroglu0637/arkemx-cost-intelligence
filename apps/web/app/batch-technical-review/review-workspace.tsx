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
import EditableEngineeringReview from "./editable-engineering-review";
import PlasterEvidenceComparison from "./plaster-evidence-comparison";

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
type CandidateChoice = { code: string; description: string; unit: string; similarity: number; technical_status: "compatible" | "review" | "blocked"; blockers: string[]; review_flags: string[]; source_version_id: string; possible_shared_scope: boolean; source_page?: number; source_price?: string | null; source_price_verified?: boolean; analysis_inputs?: {code:string;description:string;unit:string;quantity:string;unit_price:string;amount:string}[]; scope_excerpt?: string; pdf_edition_date?: string; price_audit?: {
  inputs_total: string; reconciliation_addition_percent: number; reconciliation_addition: string;
  calculated_price: string; pdf_price: string; difference: string; status: string;
} | null };
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
type SpecCompletion = {
  schema:"arkemx.a347.spec_completion.v1";read_only:true;approval_allowed:false;
  engineering_approved:false;cost_allowed:false;
  work_item_id:string;source_row:number;revision_id:string|null;
  document_sha256:string|null;document_status:string;
  selected_position_code:string|null;position_status:string;technical_flags:string[];
  facts:{key:string;label:string;value:string|number|null;excel_value:string|number|null;position_value?:string|number|null;
    state:"found_for_review"|"missing"|"conflict";evidence:{page:number;quote:string;value:string|number}[];additional_evidence_count:number}[];
  missing:string[];conflicts:string[];status:string;note:string;
};
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
    pilot_confirmed: boolean;
    pilot_status: "none" | "confirmed" | "reopened" | "stale";
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
type ManualPosition = { position_code: string; current: boolean; pdf_found: boolean; can_select: boolean; technical_status: string | null; pdf_match: CandidateChoice | null; cost_allowed: false; engineering_approved: false };
type CandidateResponse = { read_only: boolean; approval_allowed: boolean; cost_allowed: boolean; import_source: Source; catalog: { version_id: string; synthetic: boolean }; rows: { work_item_id: string; source_row: number; revision_id: string | null; suggestions: CandidateChoice[]; excluded_positions?: ExcludedPosition[]; manual_position?: ManualPosition | null; saved_selection?: SavedCandidate | null; clarification?: CeramicClarification | null; triage?: ReviewTriage; related_excel_rows?: number[]; review_summary?: string | null }[] };
type ManualPositionResponse = { saved: true; manual_position: ManualPosition; engineering_approved: false; cost_allowed: false };
type ReviewCoverage = {
  schema: "arkemx.a344.review_coverage.v1";
  read_only: true; approval_allowed: false; cost_allowed: false;
  source_sha256: string; import_id: string; import_sha256: string;
  total_rows: number; scanned_rows: number; complete: boolean;
  counts: {no_match: number; needs_info: number; needs_review: number; rule_prechecked: number; manual_codes: number; rows_with_exclusions: number};
  top_reasons: {reason: string; count: number}[];
  rows: {work_item_id: string; source_row: number; description: string; quantity: string|null; unit: string|null; state: "no_match"|"needs_info"|"needs_review"|"rule_prechecked"; reason: string; suggested_code: string|null; candidate_count: number; manual_code: string|null; cost_allowed: false; engineering_approved: false}[];
  cost_note: string;
};
type AuditRowRef = {work_item_id:string;source_row:number;row_index:number;description:string;cost_allowed:false;engineer_approved:false};
type AuditReason = "metraj_input_gap"|"technical_conflict"|"manual_code_in_pdf_not_parsed"|"manual_code_outside_loaded_pdf"|"possible_retrieval_gap"|"source_scope_or_description_unknown";
type MatchingAudit = {
  schema:"arkemx.a346.matching_audit.v1";read_only:true;approval_allowed:false;cost_allowed:false;
  source_pdf_sha256:string;import_id:string;import_sha256:string;total_rows:number;
  missing_count:number;candidate_count:number;
  missing_reason_counts:Record<AuditReason,number>;
  candidate_risk_counts:Record<string,number>;
  source_pdf:{volume:number;year:number;parsed_position_count:number;verified_price_count:number;
    raw_code_scan_available:boolean;raw_text_position_codes:number|null;
    codes_in_text_not_extracted_count:number|null;codes_in_text_not_extracted_sample:string[];note:string};
  missing_rows:(AuditRowRef&{reason_code:AuditReason;reason:string;manual_code:string|null;
    diagnostic_leads:{code:string;description:string;pdf_page:number;lexical_similarity:number;selectable:false;cost_allowed:false}[];
    excluded_examples:ExcludedPosition[];technical_exclusions:number})[];
  candidate_rows:(AuditRowRef&{risk:string;reason:string;excluded_count:number;
    source_options:{code:string;description:string;pdf_page:number;technical_status:string;
      source_price_verified:boolean;review_flags:string[];selectable_for_review:true;cost_allowed:false}[]})[];
  note:string;
};
const auditReasonLabels:Record<AuditReason,string>={
  metraj_input_gap:"Metraj bilgisi eksik",
  technical_conflict:"Teknik nedenle elendi",
  manual_code_in_pdf_not_parsed:"PDF metninde var, analiz çıkarılamadı",
  manual_code_outside_loaded_pdf:"Manuel numara bu PDF'de yok",
  possible_retrieval_gap:"Arama kaçırmış olabilir",
  source_scope_or_description_unknown:"Katalog kapsamı veya tarif belirsiz",
};
type ExcludedPosition = {code: string; description: string; source_page: number; reason: string; cost_allowed: false; selectable: false};
type PartialCostPreview = {
  schema: "arkemx.a345.partial_cost_preview.v1"; read_only: true; creates_estimate: false;
  source_pdf_sha256: string; import_id: string; import_sha256: string; total_rows: number;
  included_count: number; pending_count: number; partial_total: string; currency: "TRY";
  is_partial: boolean; included: {work_item_id: string;source_row:number;description:string;position_code:string;quantity:string;unit:string;unit_price:string;amount:string;source_pdf_page:number}[];
  pending: {work_item_id:string;source_row:number;description:string;reason:string;amount:null}[];
};
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
  WORK_SCOPE_DEMOLITION_MISMATCH: "Metraj söküm işi tarif etmiyor; bu poz söküm işine ait.",
  WORK_SCOPE_MATERIAL_ONLY_MISMATCH: "Metraj yalnızca malzemeyi tarif ediyor; bu poz uygulama/imalat işini de içeriyor.",
  WORK_SCOPE_LABOR_ONLY_MISMATCH: "Metraj yalnızca işçilik için; bu pozun kapsamına malzeme de dahil.",
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
  const reasons = [...row.flags, ...(row.comparison?.blockers ?? []), ...(row.comparison?.review_flags ?? [])]
    .filter(reason => reason !== "MATERIAL_UNVERIFIED");
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
  const [specCompletion, setSpecCompletion] = useState<SpecCompletion|null>(null);
  const [completionLoading, setCompletionLoading] = useState(false);
  const [completionError, setCompletionError] = useState("");
  const [specEvidence, setSpecEvidence] = useState<{ rowId: string; data: DocumentEvidence } | null>(null);
  const [engineerHandoff, setEngineerHandoff] = useState<EngineerHandoff | null>(null);
  const [pilotRefreshTick, setPilotRefreshTick] = useState(0);
  const [pdfRightsConfirmed, setPdfRightsConfirmed] = useState(false);
  const [catalogs, setCatalogs] = useState<CandidateCatalog[]>([]);
  const [catalogVersion, setCatalogVersion] = useState("");
  const [autoCandidates, setAutoCandidates] = useState<CandidateResponse | null>(null);
  const [coverage, setCoverage] = useState<ReviewCoverage | null>(null);
  const [audit, setAudit] = useState<MatchingAudit|null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
  const [auditReasonFilter, setAuditReasonFilter] = useState<AuditReason|"all">("all");
  const auditAbortRef=useRef<AbortController|null>(null);
  const [listSearch, setListSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all"|"approved"|"no_match"|"needs_info"|"needs_review"|"rule_prechecked">("all");
  const [costPreview, setCostPreview] = useState<PartialCostPreview|null>(null);
  const [costLoading, setCostLoading] = useState(false);
  const [costError, setCostError] = useState("");
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [coverageError, setCoverageError] = useState("");
  const coverageAbortRef = useRef<AbortController | null>(null);
  const jumpToRowRef = useRef<string | null>(null);
  const [manualCodes, setManualCodes] = useState<Record<string, string>>({});
  const [queueView, setQueueView] = useState<QueueView>("all");
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
    setCatalogs([]); setCatalogVersion(""); setPdfSource(null); setPdfFile(null); setPdfRightsConfirmed(false); setSpecFile(null); setProjectSpec(null); setSpecEvidence(null); setSpecCompletion(null); setEngineerHandoff(null); setAutoCandidates(null); setAutoMessage(""); automaticRunKeyRef.current = "";
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
    if (id !== importId || sourceProject !== projectId) {
      coverageAbortRef.current?.abort(); auditAbortRef.current?.abort();
      setCoverage(null); setCoverageLoading(false); setCoverageError("");
      setAudit(null); setAuditLoading(false); setAuditError("");
      setCostPreview(null); setCostLoading(false); setCostError("");
    }
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
      setCoverage(old => old && data.sha256 === old.source_sha256 ? old : null);
      setAudit(old => old && data.sha256 === old.source_pdf_sha256 ? old : null);
      setCostPreview(old => old && data.sha256 === old.source_pdf_sha256 ? old : null);
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
        setSpecEvidence(null); setSpecCompletion(null);
        setEngineerHandoff(null);
        setSaveNotice("Şartname bağlandı. Teknik bilgiler seçili satır için otomatik incelenecek.");
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
      coverageAbortRef.current?.abort(); auditAbortRef.current?.abort();
      setCoverage(null); setCoverageLoading(false); setCoverageError("");
      setAudit(null); setAuditLoading(false); setAuditError("");
      setCostPreview(null); setCostLoading(false); setCostError("");
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
  async function runMatchingAudit() {
    if (!selection || !projectId || !importId || !pdfSource?.sha256 || auditLoading || busy) return;
    auditAbortRef.current?.abort();
    const controller=new AbortController();
    auditAbortRef.current=controller;
    const token=sessionStorage.getItem("arkemx_dev_token");
    if(!token){setAuditError("Oturum gerekli.");return;}
    const source=selection.import_source;
    const sha=pdfSource.sha256;
    setAuditLoading(true);setAuditError("");setAudit(null);
    try{
      const res=await fetch(
        `${API}/api/projects/${encodeURIComponent(projectId)}/a346/imports/${encodeURIComponent(importId)}/audit`,
        {cache:"no-store",signal:controller.signal,headers:{Authorization:"Bearer "+token}}
      );
      if(!res.ok)throw Error("Eşleştirme denetimi başarısız (HTTP "+res.status+").");
      const data=await res.json() as MatchingAudit;
      if(controller.signal.aborted)return;
      if(data.schema!=="arkemx.a346.matching_audit.v1" ||
        data.read_only!==true || data.approval_allowed!==false || data.cost_allowed!==false ||
        data.source_pdf_sha256!==sha || data.import_id!==importId ||
        data.import_sha256!==source.sha256 || data.total_rows!==source.row_count ||
        data.missing_count+data.candidate_count!==data.total_rows ||
        data.missing_rows.length!==data.missing_count ||
        data.candidate_rows.length!==data.candidate_count ||
        Object.values(data.missing_reason_counts).reduce((a,b)=>a+b,0)!==data.missing_count ||
        Object.values(data.candidate_risk_counts).reduce((a,b)=>a+b,0)!==data.candidate_count ||
        [...data.missing_rows,...data.candidate_rows].some(row=>
          row.cost_allowed!==false||row.engineer_approved!==false||
          row.row_index<0||row.row_index>=data.total_rows)) {
        throw Error("Denetim kaynak bilgisi veya satır toplamı doğrulanamadı.");
      }
      setAudit(data);
    }catch(e){
      if(!controller.signal.aborted)setAuditError(e instanceof Error?e.message:"Denetim başarısız.");
    }finally{
      if(auditAbortRef.current===controller){
        auditAbortRef.current=null;setAuditLoading(false);
      }
    }
  }

  function openAuditedRow(row:AuditRowRef) {
    if(!selection)return;
    jumpToRowRef.current=row.work_item_id;
    if(selection.rows.some(x=>x.work_item_id===row.work_item_id)){
      setCandidateDetailId(row.work_item_id);
      jumpToRowRef.current=null;
    }else{
      loadItems(importId,Math.floor(row.row_index/20)*20);
    }
  }

    async function scanFullImport() {
    if (!selection || !projectId || !importId || !pdfSource?.sha256 || coverageLoading) return;
    coverageAbortRef.current?.abort();
    const controller = new AbortController();
    coverageAbortRef.current = controller;
    const source = selection.import_source;
    const sourceSha = pdfSource.sha256;
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) { setCoverageError("Oturum gerekli."); return; }
    setCoverageLoading(true); setCoverageError("");
    try {
      const response = await fetch(
        `${API}/api/projects/${encodeURIComponent(projectId)}/a318/imports/${encodeURIComponent(importId)}/review-coverage`,
        {cache: "no-store", signal: controller.signal, headers: {Authorization: "Bearer " + token}},
      );
      if (!response.ok) throw new Error(
        response.status === 422 ? "Proje, toplu tarama sınırını aşıyor; sayfa bazında incele." :
        "Toplu tarama tamamlanamadı (HTTP " + response.status + ")."
      );
      const result = await response.json() as ReviewCoverage;
      if (controller.signal.aborted) return;
      if (result.schema !== "arkemx.a344.review_coverage.v1" ||
          result.read_only !== true || result.approval_allowed !== false ||
          result.cost_allowed !== false || !result.complete ||
          result.import_id !== importId || result.import_sha256 !== source.sha256 ||
          result.source_sha256 !== sourceSha || result.total_rows !== source.row_count ||
          result.scanned_rows !== result.total_rows || result.rows.length !== result.total_rows ||
          result.rows.some(row => row.cost_allowed !== false || row.engineering_approved !== false)) {
        throw new Error("Tam proje incelemesi kaynak kimliğiyle uyuşmuyor.");
      }
      setCoverage(result);
    } catch (error) {
      if (!controller.signal.aborted)
        setCoverageError(error instanceof Error ? error.message : "Toplu tarama başarısız.");
    } finally {
      if (coverageAbortRef.current === controller) {
        coverageAbortRef.current = null;
        setCoverageLoading(false);
      }
    }
  }

    async function calculateSignedPartialCost() {
    if (!selection || !projectId || !importId || !pdfSource?.sha256 || costLoading) return;
    const token=sessionStorage.getItem("arkemx_dev_token");
    if (!token) {setCostError("Oturum bulunamadı.");return;}
    setCostLoading(true);setCostError("");setCostPreview(null);
    const source=selection.import_source;
    const expectedPdf=pdfSource.sha256;
    try {
      const response=await fetch(
        `${API}/api/projects/${encodeURIComponent(projectId)}/a345/imports/${encodeURIComponent(importId)}/cost-preview`,
        {cache:"no-store",headers:{Authorization:"Bearer "+token}}
      );
      if(!response.ok)throw Error("Kısmi maliyet önizlemesi hesaplanamadı (HTTP "+response.status+").");
      const data=await response.json() as PartialCostPreview;
      if(data.schema!=="arkemx.a345.partial_cost_preview.v1" ||
        data.read_only!==true || data.creates_estimate!==false ||
        data.source_pdf_sha256!==expectedPdf || data.import_id!==importId ||
        data.import_sha256!==source.sha256 || data.total_rows!==source.row_count ||
        data.included_count+data.pending_count!==data.total_rows ||
        data.included.length!==data.included_count ||
        data.pending.length!==data.pending_count ||
        data.pending.some(x=>x.amount!==null))throw Error("Maliyet önizlemesinin kaynak veya tutarlılık kontrolü başarısız.");
      setCostPreview(data);
    }catch(e){
      setCostError(e instanceof Error?e.message:"Maliyet önizlemesi alınamadı.");
    }finally{setCostLoading(false);}
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
        setManualCodes(old => Object.fromEntries(data.rows.map(row => [
          row.work_item_id, row.manual_position?.position_code ?? old[row.work_item_id] ?? "",
        ])));
        setCandidateDetailId(prev => {
          const jump = jumpToRowRef.current;
          if (jump && data.rows.some(row => row.work_item_id === jump)) {
            jumpToRowRef.current = null;
            return jump;
          }
          return prev && data.rows.some(row => row.work_item_id === prev) ?
            prev : data.rows[0]?.work_item_id ?? null;
        });
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

  // Restore project specification on reload; fail closed if inaccessible.
  useEffect(() => {
    const token=sessionStorage.getItem("arkemx_dev_token");
    if(!projectId||!authenticated||!token)return;
    const controller=new AbortController();
    void fetch(`${API}/api/projects/${encodeURIComponent(projectId)}/a326/source`,
      {cache:"no-store",signal:controller.signal,headers:{Authorization:"Bearer "+token}})
      .then(async res=>{if(!res.ok)throw Error("spec unavailable");return await res.json() as ProjectSpec;})
      .then(data=>{if(!controller.signal.aborted)setProjectSpec(data.present&&data.read_only===true&&data.sha256?data:null);})
      .catch(()=>{if(!controller.signal.aborted)setProjectSpec(null);});
    return ()=>controller.abort();
  },[projectId,authenticated]);

  // Automatic evidence lookup for selected metraj; no silent approval.
  useEffect(()=>{
    setSpecCompletion(null);setCompletionError("");setCompletionLoading(false);
    const row=selection?.rows.find(item=>item.work_item_id===candidateDetailId);
    const token=sessionStorage.getItem("arkemx_dev_token");
    if(!row||!token||!projectId||!importId||!projectSpec?.sha256)return;
    const controller=new AbortController();
    setCompletionLoading(true);
    void fetch(`${API}/api/projects/${encodeURIComponent(projectId)}/a347/imports/${encodeURIComponent(importId)}/items/${encodeURIComponent(row.work_item_id)}/completion`,
      {cache:"no-store",signal:controller.signal,headers:{Authorization:"Bearer "+token}})
      .then(async res=>{if(!res.ok)throw Error("Şartname incelemesi başarısız (HTTP "+res.status+").");return await res.json() as SpecCompletion;})
      .then(data=>{
        if(controller.signal.aborted)return;
        if(data.schema!=="arkemx.a347.spec_completion.v1"||
          data.read_only!==true||data.approval_allowed!==false||
          data.engineering_approved!==false||data.cost_allowed!==false||
          data.work_item_id!==row.work_item_id||data.source_row!==row.source_row||
          data.revision_id!==row.revision_id||data.document_sha256!==projectSpec.sha256)
          throw Error("Kanıtın kaynak veya metraj kimliği doğrulanamadı.");
        setSpecCompletion(data);
      }).catch(error=>{if(!controller.signal.aborted)setCompletionError(error instanceof Error?error.message:"Kanıt incelenemedi.");})
      .finally(()=>{if(!controller.signal.aborted)setCompletionLoading(false);});
    return ()=>controller.abort();
  },[selection,candidateDetailId,projectId,importId,projectSpec?.sha256,pilotRefreshTick]);

  // Reconcile Excel-only flags with the current saved candidate and the
  // matching technical specification. Read-only; no engineering approval.
  useEffect(() => {
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!selection || !autoCandidates || !pdfSource?.sha256 || !projectId || !importId || !token) {
      setEngineerHandoff(null);
      return;
    }
    const controller = new AbortController();
    const expected = selection.rows;
    setEngineerHandoff(null);
    void fetch(
      `${API}/api/projects/${encodeURIComponent(projectId)}/a327/imports/${encodeURIComponent(importId)}/readiness?offset=${offset}&limit=20`,
      {cache: "no-store", signal: controller.signal,
       headers: {Authorization: `Bearer ${token}`}},
    ).then(async response => {
      if (!response.ok) throw Error("Evidence readiness unavailable");
      return await response.json() as EngineerHandoff;
    }).then(data => {
      if (controller.signal.aborted || sessionStorage.getItem("arkemx_dev_token") !== token) return;
      if (data.schema !== "arkemx.a327.readiness.v1" ||
          data.read_only !== true || data.approval_allowed !== false ||
          data.engineering_approved !== false || data.cost_allowed !== false ||
          data.import_id !== importId ||
          (projectSpec?.sha256 && data.source_sha256 !== projectSpec.sha256) ||
          data.rows.length !== expected.length ||
          data.rows.some((row, i) => row.work_item_id !== expected[i].work_item_id ||
            row.engineering_approved !== false || row.cost_allowed !== false ||
            typeof row.pilot_confirmed !== "boolean" ||
            !["none","confirmed","reopened","stale"].includes(row.pilot_status) ||
            (row.pilot_confirmed !== (row.pilot_status === "confirmed")))) {
        return;
      }
      setEngineerHandoff(data);
    }).catch(() => {
      // Failure means unknown, never silently verified.
      if (!controller.signal.aborted) setEngineerHandoff(null);
    });
    return () => controller.abort();
  }, [selection, autoCandidates, projectId, importId, offset, pdfSource?.sha256, projectSpec?.sha256, pilotRefreshTick]);

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
  function saveManualPosition(id: string) {
    if (!selection || !projectId || !importId || busy) return;
    const item = selection.rows.find(row => row.work_item_id === id);
    const code = (manualCodes[id] ?? "").trim().toUpperCase();
    if (!item) return;
    if (!/^[A-Z0-9][A-Z0-9./_-]{3,79}$/.test(code)) {
      setError("Poz numarasını kontrol et (örnek: 15.123.4567).");
      return;
    }
    void request<ManualPositionResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/a318/imports/${encodeURIComponent(importId)}/items/${encodeURIComponent(id)}/manual-position`,
      data => {
        if (!data.saved || data.cost_allowed !== false || data.engineering_approved !== false ||
            data.manual_position.position_code !== code || !data.manual_position.current ||
            data.manual_position.cost_allowed !== false) {
          throw Error("Manuel poz kaydı doğrulanamadı.");
        }
        setAutoCandidates(old => old ? {
          ...old, rows: old.rows.map(row => row.work_item_id === id ?
            {...row, manual_position: data.manual_position} : row),
        } : old);
        setManualCodes(old => ({...old, [id]: code}));
        auditAbortRef.current?.abort();
        setCoverage(null); setAudit(null); setCostPreview(null);
        setSaveNotice(data.manual_position.can_select ?
          "Poz numarası PDF'de bulundu. Teknik özellikleri kontrol edip 'Pozu kaydet' ile bağlayabilirsin." :
          "Manuel poz numarası inceleme için kaydedildi. PDF'de doğrulanana kadar maliyet hesabına alınmayacak.");
      }, "manual-position", {
        method: "POST", body: JSON.stringify({
          position_code: code, expected_revision_id: item.revision_id,
        }),
      }
    );
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
        auditAbortRef.current?.abort();
        setCoverage(null); setAudit(null); setCostPreview(null);
        setSpecEvidence(null); // Old evidence comparison was for the previous chosen code.
        setEngineerHandoff(null);
        setSelected(prev => [...new Set([...prev, id])]);
        setSaveNotice(`${targetCode} poz seçimi kaydedildi. Teknik kontrol ve mühendis onayı bekliyor.`);
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
  const evidenceProofFor = (id: string, code: string) => {
    const candidate = autoCandidates?.rows.find(row => row.work_item_id === id);
    const original = selection?.rows.find(row => row.work_item_id === id);
    const linked = engineerHandoff?.rows.find(row => row.work_item_id === id);
    if (!code || !candidate || !original || !linked ||
        savedCandidates[id] !== code ||
        candidate.saved_selection?.current !== true ||
        candidate.saved_selection.code !== code ||
        candidate.saved_selection.pdf_sha256 !== pdfSource?.sha256 ||
        candidate.saved_selection.revision_id !== original.revision_id ||
        linked.saved_candidate !== code ||
        linked.status !== "documented_for_review") return null;
    return linked;
  };
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
  const expandedIsPlaster = Boolean(expandedRow && /s[ıi]va/i.test(expandedRow.effective_description) &&
    /\b(kaba|ince)\b/i.test(expandedRow.effective_description));
  const expandedSavedCode = expandedRow ? savedCandidates[expandedRow.work_item_id] : undefined;
  const expandedProof = expandedRow && expandedSelectedCode ?
    evidenceProofFor(expandedRow.work_item_id, expandedSelectedCode) : null;
  const currentEvidenceMatch = Boolean(expandedProof || (
    expandedEvidence?.status === "found_for_review" &&
    expandedEvidence?.candidate_link_status === "current" &&
    expandedEvidence?.candidate_consistency === "matches_examined_facts" &&
    expandedEvidence?.saved_candidate &&
    expandedEvidence.saved_candidate === expandedSavedCode &&
    expandedEvidence.saved_candidate === expandedSelectedCode
  ));
  const remainingCandidateFlags = (option: CandidateChoice): string[] => {
    const flags = [...option.blockers, ...option.review_flags];
    const matching = currentEvidenceMatch &&
      option.code === (expandedProof?.saved_candidate ?? expandedEvidence?.saved_candidate);
    if (!matching) return flags.filter(flag => flag !== "MATERIAL_UNVERIFIED");
    // These two flags come solely from missing attributes in the original Excel,
    // not from any source/poz contradiction. A3.27 separately verifies both.
    return flags.filter(flag => ![
      "MATERIAL_UNVERIFIED",
      "GAZBETON_STRENGTH_N_MM2_UNVERIFIED",
      "GAZBETON_DENSITY_KG_M3_UNVERIFIED",
    ].includes(flag));
  };
  const expandedManual = expandedRow
    ? autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.manual_position
    : null;
  const expandedSuggestions = expandedRow ? (() => {
    const suggestions = suggestionsFor(expandedRow.work_item_id);
    const extra = expandedManual?.pdf_match && !suggestions.some(p => p.code === expandedManual.pdf_match?.code)
      ? [expandedManual.pdf_match] : [];
    return [...extra, ...suggestions].sort((a, b) =>
      Number(b.code === expandedSelectedCode) - Number(a.code === expandedSelectedCode));
  })() : [];
  const views: { key: View; title: string }[] = [{ key: "attention", title: "Farklar ve inceleme" }, { key: "all", title: "Tümü" }, ...["incompatible", "review_required", "out_of_scope", "checked_features_match"].map(key => ({ key: key as View, title: label(key) }))];
  type ListedRow = {work_item_id:string; source_row:number; description:string; quantity:string|null; unit:string|null;
    state:"no_match"|"needs_info"|"needs_review"|"rule_prechecked"; reason:string;
    suggested_code:string|null; manual_code:string|null; pageIndex:number;};
  const listRows:ListedRow[] = coverage
    ? coverage.rows.map((row,index)=>({...row,pageIndex:index}))
    : visibleQueueRows.map((row,index)=>{
      const item=autoCandidates?.rows.find(x=>x.work_item_id===row.work_item_id);
      const options=item?.suggestions??[];
      const state:ListedRow["state"]=!options.length?"no_match":
        item?.triage?.group==="needs_info"?"needs_info":
        item?.triage?.group==="prechecked"?"rule_prechecked":"needs_review";
      return {
        work_item_id:row.work_item_id,source_row:row.source_row,
        description:row.effective_description,quantity:row.quantity,unit:row.unit,
        state, reason:item?.triage?.reason??(options.length?"Teknik inceleme bekliyor":"Uygun poz bulunamadı"),
        suggested_code:options[0]?.code??null,
        manual_code:item?.manual_position?.position_code??null,
        pageIndex:offset+index,
      };
    });
  const filterText=listSearch.trim().toLocaleLowerCase("tr-TR");
  const approvedPreviewIds=new Set(costPreview?.included.map(item=>item.work_item_id)??[]);
  const filteredListRows=listRows.filter(row=>
    (statusFilter==="all"||
     (statusFilter==="approved"?approvedPreviewIds.has(row.work_item_id):row.state===statusFilter))&&
    (!filterText||[String(row.source_row),row.description,row.reason,row.suggested_code,row.manual_code]
      .filter(Boolean).join(" ").toLocaleLowerCase("tr-TR").includes(filterText))
  );
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
        <label>Excel aktarımı
          <select value={importId} disabled={!projectId || Boolean(busy)}
            onChange={e => loadItems(e.target.value)}>
            <option value="">Excel seç</option>
            {imports.map(item => <option key={item.id} value={item.id}>
              {item.filename} · {item.row_count} satır
            </option>)}
          </select>
        </label>
        {!projectScope && <label>Proje
          <select value={projectId} onChange={e => chooseProject(e.target.value)}>
            <option value="">Proje seç</option>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>}
      </div>
      {busy && <p role="status">{busy === "auto" ? "Pozlar otomatik eşleştiriliyor…" :
        busy === "compare" ? "Teknik karşılaştırma hazırlanıyor…" : "Kayıtlar yükleniyor…"}</p>}
      {saveNotice && <p className="success" role="status">{saveNotice}</p>}
      {(!selection && projectId && !busy && imports.length === 0) &&
        <p>Bu projede kayıtlı Excel bulunmuyor. Önce Metraj sayfasından Excel yükle.</p>}
      {selection && <section className={`${styles.card} ${styles.simpleMatch}`} aria-label="Poz inceleme çalışma listesi">
        <header className={styles.a343Overview}>
          <div>
            <h2>Poz eşleştirme</h2>
            <p>Metrajı doğrula, PDF analizini düzenle; onaylıları hesapla, eksikleri beklet.</p>
          </div>
          <Link href="/#cost" className={styles.a343CostLink}>Maliyet çalışma alanı →</Link>
        </header>
        <div className={styles.a343Summary} aria-label="Proje kontrol ve maliyet özeti">
          <div><small>Toplam metraj</small><strong>{selection.import_source.row_count}</strong></div>
          <div><small>{coverage?"PDF'de poz seçenekli":"Bu sayfada poz seçenekli"}</small>
            <strong>{coverage?coverage.total_rows-coverage.counts.no_match:autoCandidates?countSuggested:"—"}</strong></div>
          <div><small>Onaylı ve hesaplanabilir</small><strong>{costPreview?costPreview.included_count:"—"}</strong></div>
          <div className={styles.a343Source}><small>Kısmi maliyet</small>
            <strong>{costPreview&&costPreview.included_count?
              Number(costPreview.partial_total).toLocaleString("tr-TR",{minimumFractionDigits:2,maximumFractionDigits:2})+" TL":"—"}</strong></div>
        </div>
        <p className={styles.a343SummaryNote}>
          {coverage?`Kaynak PDF ile ${coverage.total_rows} satır incelendi.`:
          `Henüz tüm metraj taranmadı; yalnızca bu sayfadaki ${selection.rows.length} satır gösteriliyor.`}
          {" "}Kaynak: {pdfSource?.present?"2026 analiz PDF":"PDF bekleniyor"}.
          Poz seçeneği veya kural ön kontrolü mühendis onayı değildir.
        </p>
        {pdfSource?.present && <div className={styles.a345Toolbar}>
          <div><strong>Proje kontrolü</strong><small>Eksikler diğer kalemlerin hesabını durdurmaz.</small></div>
          <div className={styles.a345Actions}>
            <button type="button" disabled={coverageLoading||Boolean(busy)} onClick={()=>void scanFullImport()}>
              {coverageLoading?"Pozlar taranıyor…":coverage?"Taramayı yenile":"Tüm metrajı tara"}
            </button>
            <button type="button" className="secondary"
              disabled={auditLoading||Boolean(busy)} onClick={()=>void runMatchingAudit()}>
              {auditLoading?"Kaynak ve eşleştirme denetleniyor…":audit?"Denetimi yenile":"Eşleştirmeyi denetle"}
            </button>
            <button type="button" className="secondary" disabled={costLoading||Boolean(busy)}
              onClick={()=>void calculateSignedPartialCost()}>
              {costLoading?"Hesaplanıyor…":"Onaylı maliyeti hesapla"}
            </button>
          </div>
        </div>}
        {costError && <p role="alert" className={styles.a330Warning}>{costError}</p>}
        {costPreview && <details className={styles.a345CostDetail}>
          <summary>Kısmi maliyet: {costPreview.included_count} onaylı, {costPreview.pending_count} bekleyen
            {costPreview.included_count>0?" · "+Number(costPreview.partial_total).toLocaleString("tr-TR",{minimumFractionDigits:2,maximumFractionDigits:2})+" TL":""}
          </summary>
          <p>Bu yalnızca geçerli mühendis imzalı, kaynaklı proje analizlerinin önizlemesidir; M5 teklifi değildir.
            Bekleyen kalemler sıfır fiyatlı kabul edilmez.</p>
          {costPreview.included_count>0 && <div className={styles.a345CostLines}>
            {costPreview.included.map(line=><div key={line.work_item_id}>
              <strong>Excel {line.source_row} · {line.position_code}</strong>
              <span>{line.quantity} {line.unit} × {line.unit_price} TL = <b>{line.amount} TL</b></span>
              <small>PDF sayfa {line.source_pdf_page} · Onaylı proje analizi</small>
            </div>)}
          </div>}
          {costPreview.pending_count>0 && <p>{costPreview.pending_count} kalem onay, kaynak veya analiz doğrulaması bekliyor.</p>}
        </details>}
        {auditError && <p role="alert" className={styles.a330Warning}>{auditError}</p>}
        {audit && <section className={styles.a346Audit} aria-label="Kaynak ve eşleştirme doğruluk denetimi">
          <div className={styles.a346Header}>
            <div>
              <h3>Kaynak ve eşleştirme denetimi</h3>
              <p>Bu PDF'de {audit.total_rows} satır incelendi:
                {" "}<strong>{audit.missing_count} eşleşmeyen</strong>,
                {" "}<strong>{audit.candidate_count} poz seçenekli.</strong>
              </p>
            </div>
            <span>Salt okunur · Maliyet dışı</span>
          </div>
          <div className={styles.a346AuditSource}>
            <strong>PDF ayrıştırma kontrolü</strong>
            <span>{audit.source_pdf.year} / Cilt {audit.source_pdf.volume} ·
              {" "}{audit.source_pdf.parsed_position_count} poz ayrıştırıldı ·
              {" "}{audit.source_pdf.verified_price_count} analiz fiyatı doğrulandı</span>
            <small>{audit.source_pdf.raw_code_scan_available?
              `Ham PDF metnindeki 15.x numaralarının ${audit.source_pdf.codes_in_text_not_extracted_count} tanesi ayrıştırılmış poz listesinde yok. Bunların hepsi poz başlığı olmayabilir.`:
              "PDF ham metin taraması yapılamadı; ayrıştırıcının kaçırdığı numaralar belirlenemedi."}
              {" "}Diğer ciltler veya branş katalogları bu denetime dahil değil.</small>
          </div>
          <div className={styles.a346ReasonGrid}>
            {(Object.keys(auditReasonLabels) as AuditReason[]).map(key=>
              <button key={key} type="button"
                aria-pressed={auditReasonFilter===key}
                className={styles.a346Reason}
                onClick={()=>setAuditReasonFilter(old=>old===key?"all":key)}>
                <strong>{audit.missing_reason_counts[key]}</strong>
                <span>{auditReasonLabels[key]}</span>
              </button>)}
          </div>
          <details className={styles.a346Rows}>
            <summary>Eşleşmeyenleri nedenleriyle incele ({auditReasonFilter==="all"?
              audit.missing_count:audit.missing_reason_counts[auditReasonFilter]})</summary>
            <div className={styles.a346Filter}>
              <label>Gösterilen grup
                <select value={auditReasonFilter}
                  onChange={e=>setAuditReasonFilter(e.target.value as AuditReason|"all")}>
                  <option value="all">Tüm eşleşmeyenler</option>
                  {(Object.keys(auditReasonLabels) as AuditReason[]).map(key=>
                    <option value={key} key={key}>{auditReasonLabels[key]}</option>)}
                </select>
              </label>
            </div>
            <div className={styles.a346RowList}>
              {audit.missing_rows.filter(row=>
                auditReasonFilter==="all"||row.reason_code===auditReasonFilter
              ).map(row=><button type="button" key={row.work_item_id}
                onClick={()=>openAuditedRow(row)}>
                <span>Excel {row.source_row} · {auditReasonLabels[row.reason_code]}</span>
                <strong>{row.description}</strong>
                <small>{row.reason}
                  {row.diagnostic_leads.length>0?
                    ` · PDF'de kontrol edilebilecek numaralar: ${row.diagnostic_leads.map(x=>x.code+" (s."+x.pdf_page+")").join(", ")}`:""}
                </small>
              </button>)}
            </div>
          </details>
          <details className={styles.a346Rows}>
            <summary>Poz seçeneklerinin teknik ve fiyat riskleri ({audit.candidate_count})</summary>
            <p className={styles.a346Help}>Poz seçeneği olması uygunluk veya mühendis onayı anlamına gelmez. Aşağıdaki PDF seçeneklerini tek tek kontrol et.</p>
            <div className={styles.a346RowList}>
              {audit.candidate_rows.map(row=><button type="button" key={row.work_item_id}
                onClick={()=>openAuditedRow(row)}>
                <span>Excel {row.source_row} · {row.source_options[0]?.code??"Poz"}</span>
                <strong>{row.description}</strong>
                <small>{row.reason}
                  {row.source_options[0]?
                    ` · PDF s. ${row.source_options[0].pdf_page} · ${row.source_options[0].source_price_verified?"Analiz fiyatı doğrulandı":"Analiz fiyatı belirsiz"}`:""}
                </small>
              </button>)}
            </div>
          </details>
          <p className={styles.a346Help}>
            Denetim yalnızca yüklenen Cilt 1 kaynağına dayanır. Benzerlik önerileri maliyete alınmaz;
            kesin uygunluk, PDF kanıtı ve mühendis incelemesi gerekir.
          </p>
        </section>}
                {coverageError && <p role="alert" className={styles.a330Warning}>{coverageError}</p>}
        {coverage && <div className={styles.a344Coverage} aria-label="Tüm metraj inceleme özeti">
          <div className={styles.a344CoverageCounts}>
            <div><small>PDF'de poz bulunamadı</small><strong>{coverage.counts.no_match}</strong></div>
            <div><small>Teknik bilgi eksik</small><strong>{coverage.counts.needs_info}</strong></div>
            <div><small>İnceleme bekleyen</small><strong>{coverage.counts.needs_review}</strong></div>
            <div><small>Kural ön kontrolü</small><strong>{coverage.counts.rule_prechecked}</strong></div>
          </div>
          <p>Bu dört durumun toplamı {coverage.total_rows} metraj kalemidir.
            <strong> Maliyete aktarım ayrı bir onay ve fiyatlandırma aşamasıdır.</strong>
            Hiçbir bekleyen kalem 0 TL kabul edilmez.</p>
          <details className={styles.a344AllResults}>
            <summary>Tüm {coverage.total_rows} satırın durumu ve bekleme nedenleri</summary>
            <div className={styles.a344AllScroll}>
              {coverage.rows.map((row, index) =>
                <button key={row.work_item_id} type="button"
                  onClick={() => {
                    jumpToRowRef.current = row.work_item_id;
                    loadItems(importId, Math.floor(index / 20) * 20);
                  }}>
                  <span>Excel {row.source_row}</span>
                  <strong>{row.state === "no_match" ? "Poz yok" :
                    row.state === "needs_info" ? "Bilgi eksik" :
                    row.state === "rule_prechecked" ? "Ön kontrol" : "İnceleme"}</strong>
                  <span>{row.reason}</span>
                  <span>{row.suggested_code ?? row.manual_code ?? "—"}</span>
                </button>)}
            </div>
          </details>
        </div>}
        {!pdfSource?.present && <div className={styles.simpleMissingSource}>
          <strong>Önce poz analiz PDF kaynağını bağla</strong>
          <p>Gerçek poz adayları yalnızca yüklenen belge üzerinden aranır.</p>
          <input type="file" accept=".pdf,application/pdf" aria-label="2026 analiz PDF dosyası"
            onChange={event => setPdfFile(event.target.files?.[0] ?? null)} />
          <label className={styles.pdfRights}><input type="checkbox" checked={pdfRightsConfirmed}
            onChange={event => setPdfRightsConfirmed(event.target.checked)} />
            PDF dosyasını işlemek için gerekli hak ve izne sahibim.</label>
          <button type="button" disabled={Boolean(busy) || !pdfFile || !pdfRightsConfirmed}
            onClick={attachPdf}>PDF dosyasını bağla</button>
          <p className={styles.legalNote}>Belgenin kullanım ve çoğaltma izinlerini kontrol et. Yetkin yoksa onaylama.</p>
        </div>}
        {error && <div role="alert" className="error">{error}
          {pdfSource?.present && <button type="button" className="secondary"
            disabled={Boolean(busy)} onClick={() => {
              automaticRunKeyRef.current = ""; findAutomaticCandidates();
            }}>Tekrar dene</button>}
        </div>}
        <div className={styles.a344Workspace}>
          <section className={styles.a344List} aria-label="Metraj listesi">
            <div className={styles.a344ListHeading}>
              <strong>Metraj kalemleri</strong>
              <small>{coverage?`Tüm projeden ${filteredListRows.length} / ${coverage.total_rows} satır`:
                "İlk 20 satır görüntüleniyor. Tümünde aramak için önce tarama yap."}</small>
            </div>
            <div className={styles.a345Filters}>
              <input type="search" aria-label="Metraj veya poz ara" placeholder="İmalat, satır veya poz ara…"
                value={listSearch} onChange={e=>setListSearch(e.target.value)}/>
              <select aria-label="Poz durum filtresi" value={statusFilter}
                onChange={e=>setStatusFilter(e.target.value as typeof statusFilter)}>
                <option value="all">Tüm durumlar</option>
                <option value="approved">Onaylı ve hesaplanan</option>
                <option value="no_match">Poz bulunamadı</option>
                <option value="needs_info">Teknik bilgi eksik</option>
                <option value="needs_review">İnceleme bekliyor</option>
                <option value="rule_prechecked">Kural ön kontrolü</option>
              </select>
            </div>
            <div className={styles.a344ListItems}>
              {filteredListRows.map(row=><button type="button" key={row.work_item_id}
                aria-pressed={candidateDetailId===row.work_item_id}
                className={styles.a344ListRow}
                onClick={()=>{
                  if(selection?.rows.some(item=>item.work_item_id===row.work_item_id)){
                    setCandidateDetailId(row.work_item_id);
                  }else{
                    jumpToRowRef.current=row.work_item_id;
                    loadItems(importId,Math.floor(row.pageIndex/20)*20);
                  }
                }}>
                <span className={styles.a344ListRowTop}>
                  <span>Excel {row.source_row}</span>
                  <em>{approvedPreviewIds.has(row.work_item_id)?"Hesaplandı":
                    row.state==="no_match"?"Poz bulunamadı":
                    row.state==="needs_info"?"Bilgi eksik":
                    row.state==="rule_prechecked"?"Ön kontrol":"İnceleme"}</em>
                </span>
                <strong>{row.description}</strong>
                <small>{row.quantity??"Miktar eksik"} {row.unit??""} ·
                  {" "}{row.suggested_code?`Poz: ${row.suggested_code}`:
                    row.manual_code?`Manuel poz: ${row.manual_code}`:"Poz bekliyor"}</small>
              </button>)}
              {!filteredListRows.length&&<p className={styles.a345EmptyList}>
                Bu arama ve filtre için eşleşen metraj bulunamadı.
              </p>}
            </div>
            <div className={styles.tableFooter}>
          <span>{selection.rows.length} satır · {Math.floor(offset / 20)+1}. sayfa</span>
          <div className={styles.pager}>
            <button type="button" className="secondary" disabled={Boolean(busy) || offset === 0}
              onClick={() => loadItems(importId, Math.max(0,offset-20))}>← Önceki</button>
            <button type="button" className="secondary" disabled={Boolean(busy) || selection.next_offset === null}
              onClick={() => loadItems(importId,selection.next_offset ?? 0)}>Sonraki →</button>
          </div>
        </div>
          </section>
          <section className={styles.a344Review} aria-label="Seçilen metraj teknik inceleme">
            {expandedRow && <div className={styles.simpleMatchDetail}>
          <div className={styles.a343DetailHeading}>
            <div><h3>Satır {expandedRow.source_row} · Teknik inceleme</h3>
              <p>{expandedRow.effective_description}</p>
              <small>Excel miktarı: {expandedRow.quantity ?? "Belirtilmemiş"} {expandedRow.unit ?? ""}</small>
            </div>
            <span className={styles.a343Pending}>{expandedProof ? "Teknik kanıt incelendi" : "İnceleme bekliyor"}</span>
          </div>
          <div className={styles.a343Decision} role="status">
            <div className={styles.a343DecisionHead}>
              <strong>{expandedSuggestions.length ? "Poz seçeneği bulundu · teknik kontrol gerekli" : "Uygun poz doğrulanamadı"}</strong>
              <span>Hesap dışında · Sonra incelenebilir</span>
            </div>
            <p>{expandedSuggestions.length ?
              (triageFor(expandedRow.work_item_id)?.reason ?? "Pozun imalat kapsamı ile Excel tarifi karşılaştırılmalı.") :
              (autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.excluded_positions?.length
                ? "Bulunan bazı pozların iş kapsamı metrajla uyuşmadı. Uygun poz için manuel numara girebilirsin."
                : "Kaynak PDF'de doğrulanabilir uygun poz bulunamadı. Manuel numara girip yeniden arayabilirsin.")}</p>
            {Boolean(autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.related_excel_rows?.length) &&
              <small>İlişkili Excel satırları: {autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.related_excel_rows?.join(", ")}. Aynı iş doğrulanmadan tutarlar birleştirilmez.</small>}
            <small>Bu satır beklerken diğer onaylı metrajların maliyet hesabı devam edebilir.</small>
          </div>
          {projectSpec?.sha256 && <section className={styles.a347Facts} aria-label="Şartname teknik bilgileri">
            <div className={styles.a347FactsHeading}><strong>Şartnamede bulunan bilgiler</strong><small>Otomatik inceleme · PDF kanıtı</small></div>
            {completionLoading&&<p>Şartname inceleniyor…</p>}
            {completionError&&<p role="alert">{completionError}</p>}
            {specCompletion?.work_item_id===expandedRow.work_item_id&&<>
              {specCompletion.conflicts.length>0&&<p className={styles.a347Conflict}>Çelişki: {specCompletion.conflicts.join(" · ")}</p>}
              {specCompletion.facts.length>0?<div className={styles.a347FactList}>
                {specCompletion.facts.map(fact=><div key={fact.key}>
                  <span>{fact.label}</span>
                  <strong>{fact.state==="conflict"?"Çelişki":fact.state==="missing"?"Bulunamadı":String(fact.value)}</strong>
                  {fact.evidence[0]&&<small>PDF sayfa {fact.evidence[0].page} · {fact.state==="conflict"?"Uyuşmazlık var":"Kanıt bulundu"}</small>}
                </div>)}
              </div>:<p>Bu imalat için ayıklanabilen teknik özellik bulunamadı.</p>}
              {specCompletion.missing.length>0&&<p className={styles.a347Missing}>Eksik: {specCompletion.missing.join(" · ")}</p>}
              <details><summary>Belgedeki ifadeleri göster</summary>
                {specCompletion.facts.flatMap(fact=>fact.evidence.map((ev,i)=>
                  <p key={fact.key+"-"+i}>PDF s. {ev.page}: {ev.quote}</p>))}
              </details>
              <small>Bulunan kanıt teknik onay, poz seçimi veya maliyet yetkisi değildir.</small>
            </>}
          </section>}
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
                {savedCandidates[expandedRow.work_item_id] === option.code && <em>Seçili poz</em>}
              </button>)}
            </div>
            <small>Projede özellik belirtilmemişse hiçbirini seçme. Poz kaydı teknik onay değildir.</small>
          </section>}
          {expandedSuggestions.length ? <>
            {expandedSuggestions.slice(0,1).map(option =>
              <div key={option.code} className={styles.simplePrimaryCandidate}>
                <div>
                  <strong>İncelenen poz · {option.code}</strong>
                  <p>{option.description}</p>
                  <span className={styles.simpleStatus + " " +
                    (option.technical_status === "blocked" ? styles.simpleStatusBlocked : styles.simpleStatusReview)}>
                    {option.technical_status === "blocked" ? "Teknik uyumsuzluk" :
                      currentEvidenceMatch && option.code === (expandedProof?.saved_candidate ?? expandedEvidence?.saved_candidate)
                        ? "Şartname uyumlu" :
                      option.review_flags.some(flag => flag.startsWith("GAZBETON_")) ? "Dayanım / yoğunluk kontrolü gerekli" :
                      "Belge kontrolü gerekli"}
                  </span>
                  {!expandedIsPlaster && remainingCandidateFlags(option).length > 0 && (
                    <p className={styles.issues}>
                      {remainingCandidateFlags(option).map(value => label(value)).join(" · ")}
                    </p>
                  )}
                  <small>PDF sayfa {option.source_page ?? "—"} ·
                    {option.source_price_verified && option.source_price ?
                      " Kaynak fiyat " + option.source_price + " TL/" + option.unit : " Fiyat doğrulanmadı"}
                    {option.pdf_edition_date ? ` · PDF belge tarihi ${option.pdf_edition_date}` : ""}
                    {""}
                  </small>
                </div>
                {expandedIsPlaster && pdfSource?.sha256 && <PlasterEvidenceComparison
                  projectId={projectId} importId={importId} rowId={expandedRow.work_item_id}
                  candidateCode={option.code} pdfSha={pdfSource.sha256}
                  revisionId={expandedRow.revision_id} specSha={projectSpec?.sha256??null} />}
                {savedCandidates[expandedRow.work_item_id] === option.code ?
                  <EditableEngineeringReview key={[expandedRow.work_item_id, option.code, expandedRow.revision_id ?? "", pdfSource?.sha256 ?? "", projectSpec?.sha256 ?? ""].join(":")}
                    projectId={projectId} importId={importId}
                    rowId={expandedRow.work_item_id} position={option}
                    onPilotChanged={() => {setPilotRefreshTick(old => old + 1);setCostPreview(null);}} /> :
                  <details>
                    <summary>PDF kanıtı ve analiz girdileri</summary>
                    <p>Analiz tablosunu düzenleyebilmek için önce bu pozu kaynak PDF'ye bağlı şekilde kaydet. Bu işlem maliyet onayı değildir.</p>
                    {option.scope_excerpt && <p>{option.scope_excerpt}</p>}
                    {option.analysis_inputs && <ul>{option.analysis_inputs.map((input, k) =>
                      <li key={input.code + "-" + k}>{input.code} · {input.description}: {input.quantity} {input.unit} × {input.unit_price} TL = {input.amount} TL</li>)}</ul>}
                  </details>}
                {savedCandidates[expandedRow.work_item_id] !== option.code &&
                  <button type="button" disabled={Boolean(busy)}
                    onClick={() => saveCandidate(expandedRow.work_item_id, option.code)}>
                    Pozu seç ve analizi aç
                  </button>}
              </div>)}
            {expandedSuggestions.length > 1 && <details className={styles.otherCandidates}>
              <summary>Diğer poz seçenekleri ({expandedSuggestions.length - 1})</summary>
              {expandedSuggestions.slice(1).map(option =>
                <div key={option.code} className={styles.otherCandidateRow}>
                  <div><strong>{option.code}</strong> · {option.description}
                    <small>{option.technical_status === "blocked" ? "Teknik uyumsuzluk" : "Teknik inceleme gerekli"} · PDF sayfa {option.source_page ?? "—"}</small>
                  </div>
                  {savedCandidates[expandedRow.work_item_id] === option.code ?
                    <span className={styles.selectedCandidateLabel}>Seçili poz</span> :
                    <button type="button" className="secondary" disabled={Boolean(busy)}
                      onClick={() => saveCandidate(expandedRow.work_item_id, option.code)}>Bu pozu seç</button>}
                </div>)}
            </details>}
          </> : <p className={styles.a343Empty}>Kaynak PDF'de doğrulanmış uygun poz bulunamadı. Manuel numara girerek daha sonra yeniden eşleştirebilirsin.</p>}
          {Boolean(autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.excluded_positions?.length) &&
            <details className={styles.otherCandidates}>
              <summary>Teknik olarak elenen pozlar (bilgi amaçlı)</summary>
              <p className={styles.a343SummaryNote}>İmalat kapsamına uymayan pozlar seçilemez ve maliyete aktarılmaz.</p>
              {autoCandidates?.rows.find(item => item.work_item_id === expandedRow.work_item_id)?.excluded_positions?.map(option =>
                <div key={option.code} className={styles.otherCandidateRow}>
                  <div><strong>{option.code}</strong> · {option.description}
                    <small>{label(option.reason)} · PDF sayfa {option.source_page}</small>
                  </div>
                  <span className={styles.a343Rejected}>Uyumsuz</span>
                </div>)}
            </details>}
          <div className={styles.a343Manual} aria-label="Manuel poz numarası">
            <strong>Manuel poz numarası · PDF ile yeniden eşleştir</strong>
            <p>Numara kaydedilir ve PDF'de tekrar aranır. Bulunamazsa bekleyenlerde kalır; diğer kalemlerin hesabını engellemez.</p>
            <div className={styles.projectEvidenceActions}>
              <label>Poz numarası
                <input type="text" maxLength={80} disabled={Boolean(busy)}
                  placeholder="Ör. 15.123.4567"
                  value={manualCodes[expandedRow.work_item_id] ?? ""}
                  onChange={event => setManualCodes(old => ({
                    ...old, [expandedRow.work_item_id]: event.target.value,
                  }))}/>
              </label>
              <button type="button" disabled={Boolean(busy) || !(manualCodes[expandedRow.work_item_id] ?? "").trim()}
                onClick={() => saveManualPosition(expandedRow.work_item_id)}>Numarayı kaydet ve PDF'de ara</button>
            </div>
            {expandedManual && <div role="status" className={styles.a330Note}>
              <strong>{expandedManual.position_code}</strong> ·
              {!expandedManual.current ? "Metraj değişti; yeniden kaydet" :
                !expandedManual.pdf_found ? " PDF'de bulunamadı, bekleyen poz" :
                !expandedManual.can_select ? " PDF'de bulundu ancak teknik olarak uyumsuz" :
                " PDF'de bulundu; eşleştirme incelemesi yapılabilir"}
              {expandedManual.current && expandedManual.can_select && expandedManual.pdf_match &&
                savedCandidates[expandedRow.work_item_id] !== expandedManual.position_code && (
                  <button type="button" className="secondary" disabled={Boolean(busy)}
                    onClick={() => saveCandidate(expandedRow.work_item_id, expandedManual.position_code)}>
                    PDF'deki pozu kaydet
                  </button>
                )}
            </div>}
          </div>
          <div className={styles.a343Advanced}>
          {(
            <details className={styles.projectEvidence}>
              <summary>Teknik belge / şartname kanıtları (isteğe bağlı)</summary>
              <p>Belgeyi bir kez bağla; yalnız gerektiğinde ilgili satırın kanıtlarını incele.</p>
              <div className={styles.projectEvidenceActions}>
                <label>Şartname PDF (en fazla 8 MB)
                  <input type="file" accept=".pdf,application/pdf"
                    disabled={Boolean(busy)} onChange={event => setSpecFile(event.target.files?.[0] ?? null)} />
                </label>
                <button type="button" disabled={Boolean(busy) || !specFile} onClick={uploadSpecification}>
                  Şartnameyi bağla
                </button>
                {!expandedIsPlaster && <button type="button" disabled={Boolean(busy)}
                  className="secondary" onClick={() => findSpecificationEvidence(expandedRow.work_item_id)}>
                  Belgede ara
                </button>}
              </div>
              {projectSpec?.present && <small>Bağlı belge: {projectSpec.filename ?? "Proje şartnamesi PDF"} · Kaynak {projectSpec.sha256?.slice(0,12)}…</small>}
              {expandedIsPlaster && <small>Sıva için PDF bilgileri aşağıdaki “Kaynaklı teknik bilgiler” tablosunda otomatik karşılaştırılır.</small>}
              {!expandedIsPlaster && expandedEvidence && <div className={styles.projectEvidenceResult} role="status">
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
                      <p>Kaydedilmiş poz ile teknik şartnamede karşılaştırılan zorunlu özellikler aynı. Excel tarifindeki eksik alanlar belgeyle desteklendi; mühendis kararını aşağıdaki bölümden kontrol et.</p>
                    ) : (
                      <p>Belgede ilgili bilgiler bulundu ancak pozla gereken tüm özellikler karşılaştırılamadı. Eksikler incelemede kalır.</p>
                    )}
                    <small>Bu karşılaştırma tek başına mühendis onayı veya maliyet yetkisi vermez.</small>
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

          </div>
        </div>}

            {!expandedRow && <div className={styles.a344Placeholder}>
              <strong>İncelemek istediğin metraj satırını seç.</strong>
              <p>PDF poz seçenekleri, eksik teknik bilgiler, analiz girdileri ve manuel numara burada açılacak.</p>
            </div>}
          </section>
        </div>
      </section>}
    </>}
  </Container>;
}
