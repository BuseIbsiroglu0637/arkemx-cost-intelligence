"use client";
import Link from "next/link";
import WorkflowNav from "../workflow-nav";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
type Evidence = {
  quote: string;
  start: number;
  end: number;
};
type Check = {
  layer?: number;
  field: string;
  status: string;
  code: string | null;
  metraj_value: unknown;
  catalog_value: unknown;
  metraj_evidence: Evidence | Evidence[] | null;
  catalog_evidence: Evidence | Evidence[] | null;
};
type Review = {
  schema: "arkemx.pdf_technical_review_preview.v1";
  read_only: boolean;
  approval_allowed: boolean;
  sources: {
    metraj: string;
    catalog: string;
  };
  comparison: {
    status: "blocked" | "review" | "layer_match";
    approval_allowed: boolean;
    blockers: string[];
    review_flags: string[];
    checks: Check[];
    technical_checks: Check[];
  };
  catalog_analysis: {
    position_code: string;
    unit: string;
    source: {
      filename: string;
      sha256: string;
      pdf_page: number;
      printed_page: number;
      price_date: string;
    };
    totals: {
      total: string;
      currency: string;
    };
    resources: {
      code: string;
      description: string;
      unit: string;
      quantity: string;
      unit_price: string;
      amount: string;
    }[];
  };
};

type ScenarioPreview = {
  schema: string;
  read_only: boolean;
  approval_allowed: boolean;
  scenario: {
    read_only: boolean;
    approval_allowed: boolean;
    technical_compatibility: string;
    alternative_price_verification: string;
    alternative_price_source: {
      position_code: string;
      description: string;
      unit: string;
      unit_price_tl: string;
      source: {
        filename: string;
        sha256: string;
        pdf_page: number;
        price_date: string;
      };
      evidence: {
        quote: string;
        pdf_page: number;
      };
    };
    source: {
      position_code: string;
      sha256: string;
      pdf_page: number;
      price_date: string;
    };
    original: {
      resource_code: string;
      total_tl: string;
    };
    replacement: {
      resource_code: string;
      quantity: string;
      unit_price_tl: string;
      line_amount_tl: string;
    };
    scenario: {
      subtotal_tl: string;
      overhead_tl: string;
      total_tl: string;
      difference_tl: string;
      unit: string;
    };
  };
};
const API = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");
const FIELD_LABELS: Record<string, string> = {
  work_type: "İmalat türü",
  thickness_mm: "Kalınlık (mm)",
  materials: "Malzeme",
  cement_dosage_kg: "Çimento miktarı (kg; tarifteki kum dayanağıyla)",
  environment: "Uygulama yeri",
  work_scope_ince_siva: "İnce sıva kapsamı",
  work_scope_kaba_siva: "Kaba sıva kapsamı",
  work_scope_siva: "Sıva kapsamı",
  work_scope_gazbeton_duvar: "Gazbeton duvar kapsamı",
};
const VALUE_LABELS: Record<string, string> = {
  included: "Kapsamda",
  excluded: "Kapsam dışı",
  kaba_siva: "Kaba sıva",
  ince_siva: "İnce sıva",
  siva: "Sıva",
  gazbeton_duvar: "Gazbeton duvar",
  cimento: "Çimento",
  alci: "Alçı",
  gazbeton: "Gazbeton",
};
const STATUS_LABELS: Record<string, string> = {
  match: "Eşleşiyor",
  block: "Uyuşmazlık",
  review: "İnceleme gerekli",
  not_specified: "Belirtilmemiş",
};
function display(value: unknown): string {
  if (value === null || value === undefined) return "Belirtilmemiş";
  if (Array.isArray(value)) {
    return value.length ? value.map(display).join(", ") : "Belirtilmemiş";
  }
  if (typeof value === "string") return VALUE_LABELS[value] ?? value;
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
function EvidenceView({
  title,
  evidence,
}: {
  title: string;
  evidence: Pick<Evidence, "quote"> | Pick<Evidence, "quote">[] | null;
}) {
  const items = evidence
    ? Array.isArray(evidence) ? evidence : [evidence]
    : [];
  return (
    <div>
      <strong>{title}</strong>
      {items.length ? items.map((item, index) => (
        <blockquote
          key={index}
          style={{
            margin: "8px 0",
            padding: "10px",
            borderLeft: "3px solid #9fb6e9",
            whiteSpace: "pre-wrap",
            overflowWrap: "anywhere",
          }}
        >
          {item.quote}
        </blockquote>
      )) : <p>Kaynak ifadesi bulunamadı.</p>}
    </div>
  );
}
export default function TechnicalReviewPage() {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [description, setDescription] = useState("");
  const [result, setResult] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<"attention" | "all">("attention");
  const requestRef = useRef<AbortController | null>(null);
  const scenarioRequestRef = useRef<AbortController | null>(null);
  const [scenarioResult, setScenarioResult] = useState<ScenarioPreview | null>(null);
  const [scenarioBusy, setScenarioBusy] = useState(false);
  const [scenarioError, setScenarioError] = useState("");

  function clearScenario() {
    scenarioRequestRef.current?.abort();
    scenarioRequestRef.current = null;
    setScenarioResult(null);
    setScenarioError("");
    setScenarioBusy(false);
  }

  useEffect(() => {
    setAuthenticated(Boolean(sessionStorage.getItem("arkemx_dev_token")));
    setReady(true);
    return () => {
      requestRef.current?.abort();
      scenarioRequestRef.current?.abort();
    };
  }, []);
  function changeDescription(value: string) {
    requestRef.current?.abort();
    requestRef.current = null;
    setDescription(value);
    setResult(null);
    clearScenario();
    setError("");
    setBusy(false);
  }
  async function compare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) {
      setAuthenticated(false);
      setResult(null);
      clearScenario();
      return;
    }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setError("");
    setResult(null);
    clearScenario();
    try {
      const response = await fetch(`${API}/api/a3/compare-pdf`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ metraj_description: description }),
        cache: "no-store",
        signal: controller.signal,
      });
      if (response.status === 401) {
        if (requestRef.current === controller) {
          setAuthenticated(false);
          setResult(null);
          clearScenario();
        }
        return;
      }
      if (!response.ok) {
        throw new Error(
          response.status === 503
            ? "PDF kaynağı hazır değil veya doğrulanamadı. API sunucusunun PDF ayarını kontrol edin."
            : response.status === 422
              ? "Tarif doğrulanamadı. Metni ve uzunluğunu kontrol edin."
              : `Karşılaştırma tamamlanamadı (HTTP ${response.status}).`
        );
      }
      const data = await response.json() as Review;
      if (
        data.schema !== "arkemx.pdf_technical_review_preview.v1" ||
        data.read_only !== true ||
        data.approval_allowed !== false ||
        data.comparison?.approval_allowed !== false ||
        !["blocked", "review", "layer_match"].includes(
          data.comparison?.status
        )
      ) {
        throw new Error("Beklenen teknik önizleme yanıtı alınamadı.");
      }
      if (requestRef.current === controller) {
        setView("attention");
        setResult(data);
      }
    } catch (exception) {
      if (controller.signal.aborted) return;
      if (requestRef.current === controller) {
        setError(
          exception instanceof Error
            ? exception.message
            : "API bağlantısı kurulamadı."
        );
      }
    } finally {
      if (requestRef.current === controller) {
        setBusy(false);
        requestRef.current = null;
      }
    }
  }
  // This is a constrained cost illustration, not an engineering approval.
  const scenarioEligible = Boolean(
    result?.catalog_analysis.position_code === "15.275.1111" &&
    result?.comparison.status === "blocked" &&
    result?.comparison.approval_allowed === false &&
    result?.comparison.blockers.length === 1 &&
    result?.comparison.blockers[0] === "LAYER_2_CEMENT_DOSAGE_KG_MISMATCH" &&
    result?.comparison.review_flags.length === 0 &&
    result?.comparison.technical_checks.some(
      (check) =>
        check.layer === 2 &&
        check.field === "cement_dosage_kg" &&
        check.status === "block" &&
        String(check.metraj_value) === "300" &&
        String(check.catalog_value) === "350"
    )
  );

  async function calculateScenario() {
    const current = result;
    if (!current || !scenarioEligible) return;

    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) {
      setAuthenticated(false);
      setScenarioError("Oturum bulunamadı. Yeniden giriş yapın.");
      return;
    }

    scenarioRequestRef.current?.abort();
    const controller = new AbortController();
    scenarioRequestRef.current = controller;
    setScenarioBusy(true);
    setScenarioError("");
    setScenarioResult(null);

    try {
      const response = await fetch(`${API}/api/a3/cost-scenario`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          alternative_resource_code: "19.100.2506",
        }),
        signal: controller.signal,
        cache: "no-store",
      });

      if (!response.ok) {
        throw new Error(
          response.status === 401
            ? "Oturum süresi doldu. Yeniden giriş yapın."
            : response.status === 503
              ? "PDF veya senaryo kaynağı doğrulanamadı."
              : `Senaryo hesaplanamadı (HTTP ${response.status}).`
        );
      }

      const data = (await response.json()) as ScenarioPreview;
      const scenario = data.scenario;
      const original = current.catalog_analysis;

      if (
        data.schema !== "arkemx.cost_scenario_preview.v1" ||
        data.read_only !== true ||
        data.approval_allowed !== false ||
        scenario?.read_only !== true ||
        scenario?.approval_allowed !== false ||
        scenario.technical_compatibility !== "not_evaluated" ||
        scenario.alternative_price_verification !== "verified_source_document" ||
        scenario.alternative_price_source?.position_code !== "19.100.2506" ||
        scenario.alternative_price_source?.unit !== "m³" ||
        scenario.alternative_price_source?.unit_price_tl !== scenario.replacement.unit_price_tl ||
        scenario.alternative_price_source?.source?.pdf_page !== 697 ||
        scenario.alternative_price_source?.source?.sha256 !== "ca7453f9e8d583e28bb16130b19487edc8308831017d8d7e4daa0367c8038431" ||
        scenario.alternative_price_source?.evidence?.quote?.includes("1.926,15") !== true ||
        scenario.source.sha256 !== original.source.sha256 ||
        scenario.source.position_code !== original.position_code ||
        scenario.source.pdf_page !== original.source.pdf_page ||
        scenario.source.price_date !== original.source.price_date ||
        scenario.original.resource_code !== "19.100.2508" ||
        scenario.original.total_tl !== original.totals.total ||
        scenario.replacement.resource_code !== "19.100.2506" ||
        scenario.replacement.quantity !== "0.010" ||
        scenario.scenario.unit !== original.unit
      ) {
        throw new Error("Senaryo sonucu kaynak PDF ile eşleşmiyor.");
      }

      // A stale response cannot overwrite a new description or comparison.
      if (scenarioRequestRef.current === controller) {
        setScenarioResult(data);
      }
    } catch (exception) {
      if (controller.signal.aborted) return;
      if (scenarioRequestRef.current === controller) {
        setScenarioError(
          exception instanceof Error
            ? exception.message
            : "Senaryo bağlantısı sırasında hata oluştu."
        );
      }
    } finally {
      if (scenarioRequestRef.current === controller) {
        setScenarioBusy(false);
        scenarioRequestRef.current = null;
      }
    }
  }

  const comparison = result?.comparison;
  const analysis = result?.catalog_analysis;
  const checks = comparison
    ? [...comparison.checks, ...comparison.technical_checks]
    : [];
  const indexedChecks = checks.map((check, index) => ({ check, index }));
  const attentionChecks = indexedChecks.filter(({ check }) => check.status !== "match");
  const visibleChecks = view === "all" ? indexedChecks : attentionChecks;
  const blockedCount = checks.filter((check) => check.status === "block").length;
  const reviewCount = checks.filter((check) => check.status === "review").length;
  const matchCount = checks.filter((check) => check.status === "match").length;
  const otherCount = attentionChecks.length - blockedCount - reviewCount;
  const title = comparison?.status === "blocked"
    ? "Teknik uyuşmazlık bulundu"
    : comparison?.status === "review"
      ? "Eksik veya belirsiz bilgi var"
      : "Kontrol edilen özellikler eşleşiyor";
  const priceApplicability = comparison?.status === "blocked"
    ? "Bu fiyat girilen tarife uygulanamaz."
    : comparison?.status === "review"
      ? "Bu fiyatın girilen tarife uygulanabilirliği henüz doğrulanmadı."
      : "Kontrol edilen özellikler eşleşiyor; fiyatın projede kullanımı için kapsam ve mühendis incelemesi gereklidir.";
  return (
    <>
      <header>
        <div>
          <div className="brand">ARKEMX</div>
          <div className="subbrand">COST INTELLIGENCE</div>
        </div>
        <Link href="/" style={{ color: "white" }}>
          Çalışma alanına dön
        </Link>
      </header>
      <main className="page stack">
        <WorkflowNav active="technical" />
        <Link href="/#technical">← Teknik inceleme seçenekleri</Link>
        <section className="card stack">
          <h1>Tek tarif denemesi</h1>
          <p>Gelişmiş araç · Excel satırlarını incelemek için <Link href="/batch-technical-review">Excel teknik incelemesine geç</Link>.</p>
          <p>
            Metraj tarifini 15.275.1111 pozunun doğrulanmış PDF
            tarifiyle karşılaştırın.
          </p>
          <p className="notice">
            Tek poz pilotu · Sonuçlar mühendis onayı değildir.
            Bu ekran proje kaydı veya maliyet taslağı oluşturmaz.
          </p>
          {!ready ? <p>Oturum kontrol ediliyor…</p> : !authenticated ? (
            <p role="status">
              Devam etmek için <Link href="/">giriş yapın</Link>,
              ardından bu sayfaya dönün.
            </p>
          ) : (
            <form className="stack" onSubmit={compare}>
              <label htmlFor="metraj-description">Metraj tarifi</label>
              <textarea
                id="metraj-description"
                rows={7}
                required
                minLength={3}
                maxLength={5000}
                value={description}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => changeDescription(event.target.value)}
                placeholder="Metraj cetvelindeki imalat tarifini yapıştırın."
                style={{
                  width: "100%",
                  font: "inherit",
                  padding: 12,
                  border: "1px solid #cbd5e1",
                  borderRadius: 9,
                }}
              />
              <span className="hint">{description.length} / 5000 karakter</span>
              <button disabled={busy || description.trim().length < 3}>
                {busy ? "Karşılaştırılıyor…" : "PDF pozuyla karşılaştır"}
              </button>
            </form>
          )}
          {busy && <p role="status">PDF ve teknik özellikler inceleniyor…</p>}
          {error && <div className="error" role="alert">{error}</div>}
        </section>
        {result && comparison && analysis && (
          <>
            <section className="card stack">
              <h2>{title}</h2>
              <p className="notice">
                Değerlendirme yalnızca motorun kontrol ettiği özellikleri
                kapsar. Nihai teknik uygunluk mühendis incelemesi gerektirir.
              </p>
              {comparison.blockers.length > 0 && (
                <div>
                  <strong>Engelleyen bulgular</strong>
                  <ul>{comparison.blockers.map((code) => (
                    <li key={code}>{code}</li>
                  ))}</ul>
                </div>
              )}
              {comparison.review_flags.length > 0 && (
                <div>
                  <strong>İncelenmesi gereken bulgular</strong>
                  <ul>{comparison.review_flags.map((code) => (
                    <li key={code}>{code}</li>
                  ))}</ul>
                </div>
              )}
              <div className="flex" aria-label="Teknik kontrol özeti">
                <span className="tag">{blockedCount} uyuşmazlık</span>
                <span className="tag">{reviewCount} inceleme gerekli</span>
                <span className="tag">{matchCount} eşleşen özellik</span>
                {otherCount > 0 && (
                  <span className="tag">{otherCount} diğer / belirtilmemiş kontrol</span>
                )}
              </div>
              <div className="flex" role="group" aria-label="Karşılaştırma görünümü">
                <button
                  type="button"
                  className={view === "attention" ? "" : "secondary"}
                  aria-pressed={view === "attention"}
                  aria-controls="technical-check-table"
                  onClick={() => setView("attention")}
                >
                  Farklar ve eksikler ({attentionChecks.length})
                </button>
                <button
                  type="button"
                  className={view === "all" ? "" : "secondary"}
                  aria-pressed={view === "all"}
                  aria-controls="technical-check-table"
                  onClick={() => setView("all")}
                >
                  Tüm özellikler ({checks.length})
                </button>
              </div>
              <p className="hint" role="status">
                {visibleChecks.length} / {checks.length} kontrol gösteriliyor.
                Sayılar tablodaki özellik kontrollerine aittir; genel bulgular yukarıda ayrıca listelenir.
              </p>
              {view === "attention" && attentionChecks.length === 0 && (
                <p className="notice" role="status">
                  Gösterilecek fark veya eksik özellik satırı yok.
                  Tüm özellikleri açabilirsiniz. Bu görünüm mühendis onayı değildir;
                  varsa yukarıdaki genel inceleme bulguları geçerlidir.
                </p>
              )}
              <div className="table-scroll" id="technical-check-table">
                <table>
                  <caption>Katman ve teknik özellik karşılaştırması</caption>
                  <thead>
                    <tr>
                      <th>Katman / özellik</th>
                      <th>Metraj</th>
                      <th>PDF poz tarifi</th>
                      <th>Sonuç ve kanıt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleChecks.map(({ check, index }) => (
                      <tr key={index}>
                        <td>
                          {check.layer ? `Katman ${check.layer} · ` : ""}
                          {FIELD_LABELS[check.field] ?? check.field}
                        </td>
                        <td>{display(check.metraj_value)}</td>
                        <td>{display(check.catalog_value)}</td>
                        <td>
                          <strong>
                            {STATUS_LABELS[check.status] ?? check.status}
                          </strong>
                          <details name="technical-check-evidence">
                            <summary>Kaynak ifadelerini göster</summary>
                            <EvidenceView
                              title="Metraj"
                              evidence={check.metraj_evidence}
                            />
                            <EvidenceView
                              title="PDF poz tarifi"
                              evidence={check.catalog_evidence}
                            />
                            {check.code && <p className="hint">{check.code}</p>}
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="card stack">
              <h2>PDF kaynak bilgisi · {analysis.position_code}</h2>
              <p>
                Kaynak fiyat tarihi: {analysis.source.price_date}
                {" · "}PDF sayfası: {analysis.source.pdf_page}
                {" · "}Basılı sayfa: {analysis.source.printed_page}
              </p>
              <div className="stack" aria-label="PDF'de yayımlanan fiyat">
                <strong>
                  PDF’de yayımlanan poz fiyatı: {analysis.totals.total}
                  {" "}{analysis.totals.currency}/{analysis.unit}
                </strong>
                <p className="hint">
                  Bu tutar kaynak PDF’deki pozun tarifine aittir.
                  Metraj metnini değiştirmeniz belgedeki fiyatı değiştirmez.
                </p>
              </div>
              <p
                role="status"
                className={comparison.status === "blocked" ? "error" : "notice"}
              >
                {priceApplicability}
              </p>
              <div
                className="stack"
                aria-label="Alternatif maliyet senaryosu"
                style={{ borderTop: "1px solid var(--border)", paddingTop: 16 }}
              >
                <h3>Alternatif maliyet senaryosu</h3>
                <p className="hint">
                  Kaynak PDF fiyatı değiştirilmez. Bu pilot yalnızca ikinci
                  katmandaki 350 kg ince harç yerine 300 kg alternatifini,
                  0,010 m³ miktarı sabit tutarak hesaplar. Diğer analiz girdileri
                  değişmez.
                </p>
                {scenarioEligible ? (
                  <>
                    <button
                      type="button"
                      disabled={scenarioBusy}
                      onClick={calculateScenario}
                    >
                      {scenarioBusy
                        ? "Senaryo hesaplanıyor…"
                        : "300 kg alternatifinin maliyetini hesapla"}
                    </button>
                    {scenarioError && (
                      <div className="error" role="alert">{scenarioError}</div>
                    )}
                    {scenarioResult && (
                      <>
                        <div className="workspace-kpis" aria-label="Senaryo tutarları">
                          <div className="kpi">
                            <b>{scenarioResult.scenario.original.total_tl} TL</b>
                            <span>Kaynak PDF fiyatı / m²</span>
                          </div>
                          <div className="kpi">
                            <b>{scenarioResult.scenario.scenario.total_tl} TL</b>
                            <span>Alternatif senaryo / m²</span>
                          </div>
                          <div className="kpi">
                            <b>{scenarioResult.scenario.scenario.difference_tl} TL</b>
                            <span>Fark / m² (senaryo − PDF)</span>
                          </div>
                        </div>
                        <details>
                          <summary>Senaryo varsayımları ve hesaplama ayrıntıları</summary>
                          <p>
                            Harç poz değişimi: {scenarioResult.scenario.original.resource_code}
                            {" → "}{scenarioResult.scenario.replacement.resource_code}
                          </p>
                          <p>
                            Sabit miktar: {scenarioResult.scenario.replacement.quantity} m³
                            {" · "}Alternatif birim fiyatı: {scenarioResult.scenario.replacement.unit_price_tl} TL/m³
                          </p>
                          <p>
                            Alternatif satır tutarı: {scenarioResult.scenario.replacement.line_amount_tl} TL
                          </p>
                          <p>
                            Yeni ara toplam: {scenarioResult.scenario.scenario.subtotal_tl} TL
                            {" · "}Genel gider ve kâr: {scenarioResult.scenario.scenario.overhead_tl} TL
                          </p>
                          <p className="hint">
                            Kaynak analiz: {scenarioResult.scenario.source.position_code}
                            {" · "}PDF sayfası {scenarioResult.scenario.source.pdf_page}
                            {" · "}Kaynak SHA-256: {scenarioResult.scenario.source.sha256}
                          </p>
                        </details>
                        <details>
                          <summary>İki PDF kaynağı ve fiyat kanıtı</summary>
                          <p>
                            Ana poz: {analysis.position_code}
                            {" · "}PDF sayfası {analysis.source.pdf_page}
                            {" · "}{analysis.totals.total} TL/{analysis.unit}
                          </p>
                          <p style={{ overflowWrap: "anywhere" }}>
                            Ana kaynak SHA-256: {analysis.source.sha256}
                          </p>
                          <p>
                            Alternatif poz: {scenarioResult.scenario.alternative_price_source.position_code}
                            {" · "}PDF sayfası {scenarioResult.scenario.alternative_price_source.source.pdf_page}
                            {" · "}{scenarioResult.scenario.alternative_price_source.unit_price_tl}
                            {" TL/"}{scenarioResult.scenario.alternative_price_source.unit}
                          </p>
                          <p style={{ overflowWrap: "anywhere" }}>
                            Alternatif kaynak SHA-256: {scenarioResult.scenario.alternative_price_source.source.sha256}
                          </p>
                          <blockquote style={{ whiteSpace: "pre-wrap" }}>
                            {scenarioResult.scenario.alternative_price_source.evidence.quote}
                          </blockquote>
                        </details>
                        <p className="warning" role="status">
                          Alternatif harcın PDF birim fiyatı doğrulandı.
                          Ancak 300 kg ve 350 kg dozajları farklıdır.
                          Fiyat doğrulaması teknik uygunluk veya mühendis onayı değildir.
                        </p>
                      </>
                    )}
                  </>
                ) : (
                  <p className="notice">
                    Bu tarif için desteklenen bir alternatif senaryo bulunmuyor.
                    İlk pilot yalnızca ikinci katmandaki 300 kg / 350 kg dozaj
                    farkı için geçerlidir; fiyat değişimi kendiliğinden teknik onay sağlamaz.
                  </p>
                )}
              </div>
              <details>
                <summary>Analiz girdileri ve belge kimliği</summary>
                <p style={{ overflowWrap: "anywhere" }}>
                  {analysis.source.filename}<br />
                  SHA-256: {analysis.source.sha256}
                </p>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Kod / girdi</th>
                        <th>Birim</th>
                        <th>Miktar</th>
                        <th>Birim fiyat (TL)</th>
                        <th>Tutar (TL)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.resources.map((resource, index) => (
                        <tr key={index}>
                          <td>{resource.code}<br />{resource.description}</td>
                          <td>{resource.unit}</td>
                          <td>{resource.quantity}</td>
                          <td>{resource.unit_price}</td>
                          <td>{resource.amount}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <details>
                <summary>Karşılaştırılan kaynak metinleri</summary>
                <EvidenceView
                  title="Metraj tarifi"
                  evidence={{
                    quote: result.sources.metraj,
                  }}
                />
                <EvidenceView
                  title="PDF teknik tarifi"
                  evidence={{
                    quote: result.sources.catalog,
                  }}
                />
              </details>
            </section>
          </>
        )}
      </main>
    </>
  );
}
