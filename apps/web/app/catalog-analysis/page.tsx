
const stats = [
  { label: "PDF sayfası", value: "741" },
  { label: "Tespit edilen tablo", value: "706" },
  { label: "Tablosuz sayfa", value: "37" },
  { label: "Tarama hatası", value: "0" },
];

const tableTypes = [
  { label: "4 sütun", count: 533, color: "#2563eb" },
  { label: "5 sütun", count: 156, color: "#0d9488" },
  { label: "3 sütun", count: 11, color: "#8b5cf6" },
  { label: "8 sütun", count: 3, color: "#f59e0b" },
  { label: "2 sütun", count: 2, color: "#64748b" },
  { label: "6 sütun", count: 1, color: "#ef4444" },
];

const samples = [
  { page: 8, structure: "4 sütun", kind: "Rayiç adayı", codes: "46" },
  { page: 20, structure: "5 sütun", kind: "Rayiç adayı", codes: "23" },
  { page: 100, structure: "5 sütun", kind: "Rayiç adayı", codes: "16" },
  { page: 183, structure: "4 sütun", kind: "Rayiç adayı", codes: "30" },
  {
    page: 149,
    structure: "5 + 8 sütun",
    kind: "Çakışma incelemesi",
    codes: "37 + 9",
  },
  { page: 249, structure: "2 × 2 sütun", kind: "Teknik tablo", codes: "0" },
  { page: 483, structure: "6 sütun", kind: "Teknik tablo", codes: "0" },
  { page: 485, structure: "3 sütun", kind: "Teknik tablo", codes: "0" },
];

const panel = {
  background: "#ffffff",
  border: "1px solid #e2e8f0",
  borderRadius: 14,
  padding: 22,
  boxShadow: "0 2px 10px rgba(15,23,42,0.035)",
};

export default function CatalogAnalysisPage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#f5f7fb",
        color: "#1e293b",
        padding: "28px 18px 60px",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <a
          href="/"
          style={{
            color: "#2563eb",
            fontSize: 14,
            textDecoration: "none",
          }}
        >
          ← Çalışma alanına dön
        </a>

        <header style={{ margin: "25px 0" }}>
          <p
            style={{
              color: "#2563eb",
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: 1,
            }}
          >
            ARKEMX COST INTELLIGENCE · M6.0-C
          </p>

          <h1
            style={{
              fontSize: 30,
              margin: "10px 0",
              fontWeight: 750,
            }}
          >
            PDF Katalog Analizi
          </h1>

          <p style={{ color: "#64748b", fontSize: 14 }}>
            2026 rayiç kataloğunun tablo yapısı, poz adayları
            ve inceleme gerektiren kayıtları.
          </p>

          <p
            style={{
              display: "inline-block",
              marginTop: 12,
              background: "#eff6ff",
              color: "#1d4ed8",
              padding: "8px 12px",
              borderRadius: 8,
              fontSize: 12,
            }}
          >
            Salt okunur · Kaydedilmiş tarama sonuçları
          </p>
        </header>

        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 14,
            marginBottom: 22,
          }}
        >
          {stats.map((stat) => (
            <div key={stat.label} style={panel}>
              <div
                style={{
                  fontSize: 13,
                  color: "#64748b",
                  marginBottom: 10,
                }}
              >
                {stat.label}
              </div>
              <strong style={{ fontSize: 30 }}>
                {stat.value}
              </strong>
            </div>
          ))}
        </div>

        <section style={{ ...panel, marginBottom: 22 }}>
          <h2 style={{ fontSize: 19, margin: "0 0 6px" }}>
            Tablo yapılarının dağılımı
          </h2>

          <p
            style={{
              color: "#64748b",
              fontSize: 13,
              marginBottom: 24,
            }}
          >
            741 sayfanın tamamında tespit edilen 706 tablo.
          </p>

          {tableTypes.map((type) => (
            <div
              key={type.label}
              style={{ marginBottom: 20 }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 13,
                  marginBottom: 8,
                }}
              >
                <span>{type.label}</span>
                <strong>{type.count}</strong>
              </div>

              <div
                style={{
                  height: 10,
                  background: "#e8edf5",
                  borderRadius: 10,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${(type.count / 706) * 100}%`,
                    background: type.color,
                    borderRadius: 10,
                  }}
                />
              </div>
            </div>
          ))}

          <p style={{ fontSize: 13, color: "#475569" }}>
            4 ve 5 sütunlu tablolar toplamın yaklaşık
            <strong> %97,6</strong>'sını oluşturuyor.
            Bu oran doğrulanmış poz oranı değildir.
          </p>
        </section>

        <section style={{ ...panel, marginBottom: 22 }}>
          <h2 style={{ fontSize: 19, margin: "0 0 8px" }}>
            Tablo ailesi sınıflandırması
          </h2>

          <p style={{ fontSize: 13, color: "#64748b" }}>
            Sekiz örnek sayfa üzerinde doğrulanan on tablo.
          </p>

          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(170px, 1fr))",
              gap: 12,
              marginTop: 18,
            }}
          >
            {[
              {
                title: "Rayiç adayları",
                value: 5,
                color: "#0d9488",
              },
              {
                title: "Teknik / pozsuz",
                value: 4,
                color: "#64748b",
              },
              {
                title: "Karmaşık tablo",
                value: 1,
                color: "#d97706",
              },
            ].map((item) => (
              <div
                key={item.title}
                style={{
                  background: "#f8fafc",
                  padding: 18,
                  borderRadius: 10,
                }}
              >
                <strong
                  style={{
                    fontSize: 28,
                    color: item.color,
                  }}
                >
                  {item.value}
                </strong>

                <p style={{ fontSize: 13 }}>
                  {item.title}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section style={{ ...panel, marginBottom: 22 }}>
          <h2 style={{ fontSize: 19, margin: "0 0 18px" }}>
            İncelenen örnek sayfalar
          </h2>

          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 13,
                textAlign: "left",
              }}
            >
              <thead>
                <tr style={{ background: "#f1f5f9" }}>
                  {[
                    "PDF sayfası",
                    "Tablo yapısı",
                    "Sınıflandırma",
                    "Poz adayı",
                  ].map((heading) => (
                    <th
                      key={heading}
                      style={{ padding: 13 }}
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody>
                {samples.map((sample) => (
                  <tr
                    key={sample.page}
                    style={{
                      borderBottom:
                        "1px solid #e2e8f0",
                    }}
                  >
                    <td style={{ padding: 13 }}>
                      {sample.page}
                    </td>
                    <td style={{ padding: 13 }}>
                      {sample.structure}
                    </td>
                    <td style={{ padding: 13 }}>
                      {sample.kind}
                    </td>
                    <td style={{ padding: 13 }}>
                      {sample.codes}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section
          style={{
            ...panel,
            background: "#fffbeb",
            border: "1px solid #fde68a",
          }}
        >
          <h2
            style={{
              fontSize: 17,
              color: "#92400e",
              marginTop: 0,
            }}
          >
            ⚠ Mükerrer poz incelemesi
          </h2>

          <p
            style={{
              fontSize: 14,
              lineHeight: 1.7,
              color: "#78350f",
            }}
          >
            PDF'nin 149. sayfasındaki iki tabloda
            ortak olan 9 poz tespit edildi.
            Bunlar otomatik birleştirilmeyecek veya
            silinmeyecek. Kaynak koordinatları ve
            içerikleri ayrıca karşılaştırılacak.
          </p>
        </section>

        <footer
          style={{
            marginTop: 22,
            color: "#94a3b8",
            fontSize: 12,
          }}
        >
          ARKEMX · M6.0-C katalog kapsam analizi ·
          Gerçek tarama sonuçlarının statik görünümü
        </footer>
      </div>
    </main>
  );
}
