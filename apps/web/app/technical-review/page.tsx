"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

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
  schema: string;
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

  useEffect(() => {
    setAuthenticated(Boolean(sessionStorage.getItem("arkemx_dev_token")));
    setReady(true);
    return () => requestRef.current?.abort();
  }, []);

  function changeDescription(value: string) {
    requestRef.current?.abort();
    requestRef.current = null;
    setDescription(value);
    setResult(null);
    setError("");
    setBusy(false);
  }

  async function compare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) {
      setAuthenticated(false);
      setResult(null);
      return;
    }

    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setError("");
    setResult(null);

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
        <section className="card stack">
          <h1>Kanıtlı teknik karşılaştırma</h1>
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
                onChange={(event) => changeDescription(event.target.value)}
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
                aria-label="Girilen tarife göre maliyet"
                style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}
              >
                <strong>Girilen tarife göre maliyet: Henüz hesaplanmadı</strong>
                <p className="hint">
                  Uyarlanmış maliyet için değişen imalatın malzeme miktarları,
                  yardımcı analizleri ve işçilik girdileri ayrıca değerlendirilmelidir.
                  Yukarıdaki kaynak fiyatı, bu tarifin hesaplanmış maliyeti değildir.
                </p>
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
