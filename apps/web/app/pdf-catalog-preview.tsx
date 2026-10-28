
"use client";

import { useEffect, useState } from "react";

type PdfRow = {
  code: string;
  description: string;
  unit: string;
  price: string;
  source_page: number;
  source_bbox: number[];
  source_sha256: string;
  validation_status: string;
};

type PdfPreview = {
  page: number;
  total: number;
  catalog_period: string;
  status: string;
  rows: PdfRow[];
};

const API =
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000";

export default function PdfCatalogPreview({
  token,
}: {
  token: string | null;
}) {
  const [data, setData] = useState<PdfPreview | null>(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadPreview() {
    if (!token) return;

    setLoading(true);
    setError("");
    setData(null);
    setSelected(null);

    try {
      const response = await fetch(
        `${API}/api/m6/pilot/preview`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
          cache: "no-store",
        }
      );

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : `HTTP ${response.status}`
        );
      }

      const result: PdfPreview = await response.json();

      if (!Array.isArray(result.rows)) {
        throw new Error("Geçersiz PDF önizleme yanıtı");
      }

      setData(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Bağlantı hatası"
      );
    } finally {
      setLoading(false);
    }
  }

  const filtered = data?.rows.filter((row) =>
    `${row.code} ${row.description}`
      .toLocaleLowerCase("tr-TR")
      .includes(search.toLocaleLowerCase("tr-TR"))
  ) ?? [];

  const active = data?.rows.find(
    (row) => row.code === selected
  );

  return (
    <section className="card stack" aria-label="M6 PDF katalog önizleme">
      <div className="flex between">
        <div>
          <h2>M6 · PDF Katalog Önizleme</h2>
          <p className="hint">
            ÇŞİDB 2026/01 · Yerel kaynak · Sayfa 8
          </p>
        </div>
        <span className="tag">Salt okunur</span>
      </div>

      <p className="notice">
        Bu bölüm yalnızca PDF kaynak kanıtlarını gösterir.
        Katalog kaydı, otomatik eşleştirme ve mühendis
        onayı oluşturmaz.
      </p>

      <button
        type="button"
        className="secondary"
        disabled={loading || !token}
        onClick={loadPreview}
      >
        {loading
          ? "PDF okunuyor..."
          : "Gerçek PDF pozlarını görüntüle"}
      </button>

      {error && <p role="alert" className="error">{error}</p>}

      {data && (
        <>
          <div className="workspace-kpis">
            <div className="kpi">
              <b>{data.total}</b>
              <span>Okunan poz</span>
            </div>
            <div className="kpi">
              <b>{data.rows.length}</b>
              <span>Kaynak kanıtı</span>
            </div>
            <div className="kpi">
              <b>{data.page}</b>
              <span>PDF sayfası</span>
            </div>
          </div>

          <label>
            Poz kodu veya açıklama ara
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Örn. 10.100.1001 veya taşçı"
            />
          </label>

          <p className="hint">
            {filtered.length} poz görüntüleniyor.
            Katalog dönemi: {data.catalog_period}
          </p>

          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Poz kodu</th>
                  <th>Açıklama</th>
                  <th>Birim</th>
                  <th>Fiyat (TL)</th>
                  <th>Kanıt</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr key={row.code}>
                    <td>{row.code}</td>
                    <td>{row.description}</td>
                    <td>{row.unit}</td>
                    <td>
                      {Number(row.price).toLocaleString("tr-TR", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setSelected(row.code)}
                      >
                        İncele
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {active && (
            <div className="stack">
              <h3>Kaynak Kanıtı — {active.code}</h3>

              <p><strong>Tanım:</strong> {active.description}</p>
              <p><strong>PDF sayfası:</strong> {active.source_page}</p>
              <p>
                <strong>Kaynak koordinatları:</strong>{" "}
                {active.source_bbox.map((n) => n.toFixed(2)).join(", ")}
              </p>
              <p>
                <strong>Durum:</strong>{" "}
                {active.validation_status === "needs_review"
                  ? "Mühendis incelemesi gerekli"
                  : active.validation_status}
              </p>
              <p className="hint" style={{ overflowWrap: "anywhere" }}>
                SHA-256: {active.source_sha256}
       
              <PdfEvidenceImage token={token} code={active.code} />       </p>

              <button
                type="button"
                className="secondary"
                onClick={() => setSelected(null)}
              >
                Kanıt ayrıntısını kapat
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}


function PdfEvidenceImage({
  token,
  code,
}: {
  token: string | null;
  code: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let objectUrl: string | null = null;

    setSrc(null);
    setLoading(true);
    setError("");

    async function loadImage() {
      if (!token) {
        setLoading(false);
        setError("Oturum gerekli");
        return;
      }

      try {
        const response = await fetch(
          `${API}/api/m6/pilot/evidence-image/${encodeURIComponent(code)}`,
          {
            headers: {
              Authorization: `Bearer ${token}`,
            },
            cache: "no-store",
            signal: controller.signal,
          }
        );

        if (!response.ok) {
          throw new Error(`PDF goruntusu alinamadi: HTTP ${response.status}`);
        }

        const blob = await response.blob();

        if (blob.type !== "image/png") {
          throw new Error("Beklenmeyen goruntu formati");
        }

        if (!active) return;

        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);

      } catch (err) {
        if (active && !controller.signal.aborted) {
          setError(
            err instanceof Error ? err.message : "Goruntu hatasi"
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadImage();

    return () => {
      active = false;
      controller.abort();

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [token, code]);

  return (
    <div className="stack">
      <h3>PDF Üzerinde Kaynak Kanıtı</h3>

      {loading && <p>Kaynak görüntüsü yükleniyor...</p>}

      {error && <p role="alert" className="error">{error}</p>}

      {src && (
        <img
          src={src}
          alt={`${code} pozunun işaretli PDF kaynak satırı`}
          style={{
            display: "block",
            width: "100%",
            height: "auto",
            border: "1px solid #dbe3ef",
            borderRadius: 8,
          }}
        />
      )}

      <p className="hint">
        Gerçek PDF'den üretilen salt okunur kaynak görüntüsü.
      </p>
    </div>
  );
}