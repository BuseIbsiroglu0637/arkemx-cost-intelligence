
"use client";

import { useEffect, useState, type CSSProperties } from "react";

type Summary = {
  scanned_pages: number;
  tables_total: number;
  pages_without_tables: number;
  scan_error_pages: number;
  tables_by_columns: Record<string, number>;
  tables_by_family: Record<string, number>;
  candidate_code_occurrences: number;
  unique_candidate_codes: number;
  repeated_candidate_codes: number;
  repeated_code_examples: Record<string, number>;
  pages_with_table_overlaps: number;
  overlapping_table_pairs: number;
};

type CatalogReport = {
  status: "complete";
  schema_version: string;
  source: {
    filename: string;
    sha256: string;
    page_count: number;
  };
  summary: Summary;
};

const API = (
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

const panel: CSSProperties = {
  padding: 22,
  borderRadius: 14,
  background: "#ffffff",
  border: "1px solid #e2e8f0",
};


const familyLabels: Record<string, string> = {
  RAYIC_3_SUTUN_ADAYI: "3 sütunlu rayiç adayı",
  RAYIC_4_SUTUN_ADAYI: "4 sütunlu rayiç adayı",
  RAYIC_5_SUTUN_ADAYI: "5 sütunlu rayiç adayı",
  MONTAJ_4_SUTUN_ADAYI: "Montaj fiyat tablosu adayı",
  BELIRSIZ_INCELE: "Belirsiz / inceleme gerekli",
  KARMASIK_POZ_TABLOSU_INCELE: "Karmaşık poz tablosu",
  TEKNIK_VEYA_POZSUZ_TABLO: "Teknik / pozsuz tablo",
};

const colors = [
  "#2563eb",
  "#0d9488",
  "#8b5cf6",
  "#d97706",
  "#64748b",
  "#dc2626",
];

function format(value: number) {
  return value.toLocaleString("tr-TR");
}

export default function CatalogAnalysisPage() {
  const [report, setReport] = useState<CatalogReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    const token = sessionStorage.getItem("arkemx_dev_token");

    if (!token) {
      setReport(null);
      setError(
        "Oturum bulunamadı. ARKEMX çalışma alanında giriş yapın."
      );
      setLoading(false);
      return;
    }

    async function loadReport() {
      setLoading(true);
      setError("");

      try {
        const response = await fetch(
          `${API}/api/m6/pilot/catalog-analysis`,
          {
            method: "GET",
            headers: {
              Authorization: `Bearer ${token}`,
            },
            cache: "no-store",
            signal: controller.signal,
          }
        );

        if (!response.ok) {
          const body = await response.json().catch(() => ({}));

          const message =
            typeof body.detail === "string"
              ? body.detail
              : `API hatası: HTTP ${response.status}`;

          throw new Error(message);
        }

        const data: CatalogReport = await response.json();

        if (
          data.status !== "complete" ||
          !data.summary ||
          !data.source ||
          !Number.isInteger(data.summary.scanned_pages) ||
          !Number.isInteger(data.summary.tables_total) ||
          !data.summary.tables_by_columns ||
          !data.summary.tables_by_family ||
          data.source.page_count !== data.summary.scanned_pages
        ) {
          throw new Error("Geçersiz katalog raporu");
        }

        if (active) setReport(data);
      } catch (err) {
        if (active && !controller.signal.aborted) {
          setReport(null);
          setError(
            err instanceof Error
              ? err.message
              : "Katalog raporu yüklenemedi"
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadReport();

    return () => {
      active = false;
      controller.abort();
    };
  }, [refresh]);

  const summary = report?.summary;

  const stats = summary
    ? [
        ["PDF sayfası", summary.scanned_pages],
        ["Tespit edilen tablo", summary.tables_total],
        ["Benzersiz poz adayı", summary.unique_candidate_codes],
        ["Tarama hatası", summary.scan_error_pages],
      ] as const
    : [];

  const columns = summary
    ? Object.entries(summary.tables_by_columns).sort(
        (a, b) => Number(a[0]) - Number(b[0])
      )
    : [];

  const maxCount = Math.max(
    1,
    ...columns.map(([, count]) => count)
  );

  const repeated = summary
    ? Object.entries(summary.repeated_code_examples)
    : [];

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#f5f7fb",
        padding: "28px 18px 60px",
        fontFamily: "Arial, sans-serif",
        color: "#1e293b",
      }}
    >
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <a
          href="/"
          style={{ color: "#2563eb", textDecoration: "none" }}
        >
          ← Çalışma alanına dön
        </a>

        <header style={{ margin: "24px 0" }}>
          <p style={{ color: "#2563eb", fontSize: 12 }}>
            ARKEMX COST INTELLIGENCE · M6.0-C.6
          </p>

          <h1 style={{ fontSize: 28 }}>
            PDF Katalog Analizi
          </h1>

          <p style={{ color: "#64748b" }}>
            Gerçek PDF analiz raporuna bağlı, salt okunur panel.
          </p>

        <button
            type="button"
            disabled={loading}
            onClick={() => setRefresh((value) => value + 1)}
            style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                minWidth: 145,
                minHeight: 40,
                padding: "10px 16px",
                backgroundColor: "#ffffff",
                color: "#142b50",
                fontSize: 14,
                fontWeight: 700,
                lineHeight: "20px",
                opacity: 1,
                border: "1px solid #cbd5e1",
                borderRadius: 8,
                cursor: loading ? "wait" : "pointer",
            }}
        >
            <span style={{ color: "#142b50", fontSize: 14 }}>
                {loading ? "Yükleniyor..." : "Raporu yenile"}
            </span>
        </button>

        </header>

        {loading && (
          <div style={panel} role="status">
            Katalog analiz raporu okunuyor...
          </div>
        )}

        {error && (
          <div
            style={{
              ...panel,
              borderColor: "#fca5a5",
              color: "#991b1b",
              marginBottom: 20,
            }}
            role="alert"
          >
            {error}
            <p>
              API bağlantısını, pilot ayarlarını ve oturumu
              kontrol edin.
            </p>
          </div>
        )}

        {report && summary && (
          <>
            <div
              style={{
                ...panel,
                marginBottom: 18,
                background: "#eff6ff",
              }}
            >
              <strong>Canlı API raporu yüklendi</strong>
              <p style={{ fontSize: 13 }}>
                Kaynak: {report.source.filename}
              </p>
              <p
                style={{
                  fontSize: 12,
                  overflowWrap: "anywhere",
                }}
              >
                SHA-256: {report.source.sha256}
              </p>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(180px, 1fr))",
                gap: 14,
                marginBottom: 20,
              }}
            >
              {stats.map(([label, value]) => (
                <div key={label} style={panel}>
                  <p style={{ fontSize: 13, color: "#64748b" }}>
                    {label}
                  </p>
                  <strong style={{ fontSize: 29 }}>
                    {format(value)}
                  </strong>
                </div>
              ))}
            </div>

            <section style={{ ...panel, marginBottom: 20 }}>
              <h2>Tablo yapılarının dağılımı</h2>

              {columns.map(([column, count], index) => (
                <div key={column} style={{ marginBottom: 18 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 13,
                      marginBottom: 8,
                    }}
                  >
                    <span>{column} sütun</span>
                    <strong>{format(count)}</strong>
                  </div>

                  <div
                    style={{
                      height: 10,
                      background: "#e2e8f0",
                      borderRadius: 8,
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        width: `${(count / maxCount) * 100}%`,
                        background: colors[index % colors.length],
                      }}
                    />
                  </div>
                </div>
              ))}
            </section>

            <section style={{ ...panel, marginBottom: 20 }}>
              <h2>Tablo aileleri</h2>

              <div style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 14,
                  }}
                >
                  <thead>
                    <tr>
                      <th style={{ padding: 12, textAlign: "left" }}>
                        Sınıflandırma
                      </th>
                      <th style={{ padding: 12, textAlign: "right" }}>
                        Tablo sayısı
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {Object.entries(summary.tables_by_family).map(
                      ([family, count]) => (
                        <tr
                          key={family}
                          style={{
                            borderTop: "1px solid #e2e8f0",
                          }}
                        >
                          <td style={{ padding: 12 }}>
                            {familyLabels[family] ?? family}
                          </td>
                          <td
                            style={{
                              padding: 12,
                              textAlign: "right",
                              fontWeight: 700,
                            }}
                          >
                            {format(count)}
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section style={{ ...panel, marginBottom: 20 }}>
              <h2>Poz kimliği kontrolü</h2>

              <p>
                Poz kodu görülme sayısı:{" "}
                <strong>
                  {format(summary.candidate_code_occurrences)}
                </strong>
              </p>
              <p>
                Benzersiz poz kodu adayı:{" "}
                <strong>
                  {format(summary.unique_candidate_codes)}
                </strong>
              </p>
              <p>
                Tekrarlanan kod:{" "}
                <strong>
                  {format(summary.repeated_candidate_codes)}
                </strong>
              </p>
              <p>
                Ortak poz içeren sayfa:{" "}
                <strong>
                  {format(summary.pages_with_table_overlaps)}
                </strong>
              </p>
            </section>

            {repeated.length > 0 && (
              <section
                style={{
                  ...panel,
                  background: "#fffbeb",
                  borderColor: "#fde68a",
                }}
              >
                <h2 style={{ color: "#92400e" }}>
                  ⚠ Mükerrer poz incelemesi
                </h2>

                <p>
                  Aşağıdaki poz kodları birden fazla tabloda
                  veya satırda görülmüş. Otomatik birleştirme
                  yapılmaz.
                </p>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fit, minmax(150px, 1fr))",
                    gap: 10,
                  }}
                >
                  {repeated.map(([code, count]) => (
                    <div
                      key={code}
                      style={{
                        background: "#ffffff",
                        padding: 12,
                        borderRadius: 8,
                        fontSize: 13,
                      }}
                    >
                      <strong>{code}</strong>
                      <div>{count} kez görüldü</div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <footer
              style={{
                marginTop: 22,
                fontSize: 12,
                color: "#1e293b",
                fontWeight: 600,
              }}
            >
              20.315 benzeri kod sayıları poz adayıdır;
              mühendis tarafından onaylanmış fiyat kaydı
              değildir. Bu ekran veritabanına yazmaz.
            </footer>
          </>
        )}
      </div>
    </main>
  );
}
