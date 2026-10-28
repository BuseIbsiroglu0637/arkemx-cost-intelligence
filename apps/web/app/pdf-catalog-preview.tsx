
"use client";

import { useEffect, useState } from "react";

type Category = "labor" | "material";

type PdfRow = {
  code: string;
  description: string;
  unit: string;
  price: string;
  source_page: number;
  source_bbox: number[];
  source_sha256: string;
  validation_status: string;
  category: Category;
  purchase_place?: string | null;
};

type ApiRow = Omit<PdfRow, "category"> & {
  category?: string;
};

type ApiPreview = {
  page: number;
  total: number;
  catalog_period: string;
  status: string;
  rows: ApiRow[];
};

type CombinedPreview = {
  rows: PdfRow[];
  laborCount: number;
  materialCount: number;
  catalogPeriod: string;
};

const API = (
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

async function fetchPreview(
  path: string,
  token: string
): Promise<ApiPreview> {
  const response = await fetch(`${API}${path}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));

    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `HTTP ${response.status}`
    );
  }

  const result: ApiPreview = await response.json();

  if (
    result.status !== "read_only" ||
    !Array.isArray(result.rows) ||
    result.total !== result.rows.length
  ) {
    throw new Error("Gecersiz PDF katalog yaniti");
  }

  return result;
}

export default function PdfCatalogPreview({
  token,
}: {
  token: string | null;
}) {
  const [data, setData] = useState<CombinedPreview | null>(null);
  const [category, setCategory] = useState<"all" | Category>(
    "all"
  );
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(
    null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadPreview() {
    if (!token || loading) return;

    setLoading(true);
    setError("");
    setData(null);
    setSelected(null);

    try {
      const [labor, material] = await Promise.all([
        fetchPreview("/api/m6/pilot/preview", token),
        fetchPreview("/api/m6/pilot/material/preview", token),
      ]);

      if (
        labor.rows.length !== 46 ||
        material.rows.length !== 16 ||
        labor.page !== 8 ||
        material.page !== 100 ||
        labor.catalog_period !== material.catalog_period
      ) {
        throw new Error(
          "Kaynak katalog kapsam kontrolu basarisiz"
        );
      }

      const rows: PdfRow[] = [
        ...labor.rows.map((row) => ({
          ...row,
          category: "labor" as const,
          purchase_place: null,
        })),
        ...material.rows.map((row) => ({
          ...row,
          category: "material" as const,
        })),
      ];

      const codes = new Set(rows.map((row) => row.code));

      if (codes.size !== 62) {
        throw new Error(
          "Tekrarlanan veya eksik poz kimligi"
        );
      }

      setData({
        rows,
        laborCount: labor.rows.length,
        materialCount: material.rows.length,
        catalogPeriod: labor.catalog_period,
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "PDF kataloglari yuklenemedi"
      );
    } finally {
      setLoading(false);
    }
  }

  const filtered = data?.rows.filter((row) => {
    const categoryMatches =
      category === "all" || row.category === category;

    const content = [
      row.code,
      row.description,
      row.unit,
      row.purchase_place ?? "",
    ]
      .join(" ")
      .toLocaleLowerCase("tr-TR");

    return (
      categoryMatches &&
      content.includes(search.toLocaleLowerCase("tr-TR"))
    );
  }) ?? [];

  const active = data?.rows.find(
    (row) => row.code === selected
  );

  return (
    <section
      className="card stack"
      aria-label="M6 PDF katalog onizleme"
    >
      <div className="flex between">
        <div>
          <h2>M6 · Birleşik PDF Katalog Önizleme</h2>
          <p className="hint">
            ÇŞİDB 2026/01 · Gerçek PDF · İşçilik ve malzeme
          </p>
        </div>
        <span className="tag">Salt okunur</span>
      </div>

      <p className="notice">
        PDF kaynak kanıtları yalnızca inceleme amaçlıdır.
        Katalog kaydı, otomatik eşleştirme veya mühendis
        onayı oluşturulmaz.
      </p>

      <button
        type="button"
        className="secondary"
        disabled={!token || loading}
        onClick={loadPreview}
      >
        {loading
          ? "Kaynaklar doğrulanıyor..."
          : "Gerçek PDF kataloglarını görüntüle"}
      </button>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {data && (
        <>
          <div className="workspace-kpis">
            <div className="kpi">
              <b>{data.rows.length}</b>
              <span>Toplam poz</span>
            </div>

            <div className="kpi">
              <b>{data.laborCount}</b>
              <span>İşçilik</span>
            </div>

            <div className="kpi">
              <b>{data.materialCount}</b>
              <span>Malzeme</span>
            </div>
          </div>

          <div className="fields">
            <label>
              Poz türü
              <select
                value={category}
                onChange={(event) => {
                  setCategory(
                    event.target.value as "all" | Category
                  );
                  setSelected(null);
                }}
              >
                <option value="all">Tümü · 62 poz</option>
                <option value="labor">
                  İşçilik · 46 poz
                </option>
                <option value="material">
                  Malzeme · 16 poz
                </option>
              </select>
            </label>

            <label>
              Poz kodu veya açıklama ara
              <input
                type="search"
                value={search}
                onChange={(event) =>
                  setSearch(event.target.value)
                }
                placeholder="Örn. 10.310.1301 veya EPS"
              />
            </label>
          </div>

          <p className="hint">
            {filtered.length} poz görüntüleniyor.
            Katalog dönemi: {data.catalogPeriod}
          </p>

          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Poz türü</th>
                  <th>Poz kodu</th>
                  <th>Açıklama</th>
                  <th>Birim</th>
                  <th>Satın alma yeri</th>
                  <th>Fiyat (TL)</th>
                  <th>Sayfa</th>
                  <th>Kanıt</th>
                </tr>
              </thead>

              <tbody>
                {filtered.map((row) => (
                  <tr key={row.code}>
                    <td>
                      {row.category === "labor"
                        ? "İşçilik"
                        : "Malzeme"}
                    </td>

                    <td>{row.code}</td>
                    <td>{row.description}</td>
                    <td>{row.unit}</td>
                    <td>{row.purchase_place ?? "—"}</td>

                    <td>
                      {Number(row.price).toLocaleString(
                        "tr-TR",
                        {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        }
                      )}
                    </td>

                    <td>{row.source_page}</td>

                    <td>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() =>
                          setSelected(row.code)
                        }
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

              <p>
                <strong>Tür:</strong>{" "}
                {active.category === "labor"
                  ? "İşçilik"
                  : "Malzeme"}
              </p>

              <p>
                <strong>Tanım:</strong>{" "}
                {active.description}
              </p>

              <p>
                <strong>PDF sayfası:</strong>{" "}
                {active.source_page}
              </p>

              {active.purchase_place && (
                <p>
                  <strong>Satın alma yeri:</strong>{" "}
                  {active.purchase_place}
                </p>
              )}

              <p>
                <strong>Kaynak koordinatları:</strong>{" "}
                {active.source_bbox
                  .map((n) => n.toFixed(2))
                  .join(", ")}
              </p>

              <p>
                <strong>Durum:</strong>{" "}
                {active.validation_status === "needs_review"
                  ? "Mühendis incelemesi gerekli"
                  : active.validation_status}
              </p>

              <p
                className="hint"
                style={{ overflowWrap: "anywhere" }}
              >
                SHA-256: {active.source_sha256}
              </p>

              <PdfEvidenceImage
                key={`${active.category}:${active.code}`}
                token={token}
                code={active.code}
                category={active.category}
              />

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
  category,
}: {
  token: string | null;
  code: string;
  category: Category;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    let active = true;

    setSrc(null);
    setLoading(true);
    setError("");

    if (!token) {
      setLoading(false);
      setError("Oturum gerekli");
      return () => controller.abort();
    }

    async function loadImage() {
      try {
        const endpoint =
          category === "material"
            ? "/api/m6/pilot/material/evidence-image/"
            : "/api/m6/pilot/evidence-image/";

        const response = await fetch(
          `${API}${endpoint}${encodeURIComponent(code)}`,
          {
            headers: {
              Authorization: `Bearer ${token}`,
            },
            cache: "no-store",
            signal: controller.signal,
          }
        );

        if (!response.ok) {
          const body = await response
            .json()
            .catch(() => ({}));

          throw new Error(
            typeof body.detail === "string"
              ? body.detail
              : `HTTP ${response.status}`
          );
        }

        const blob = await response.blob();

        if (blob.type !== "image/png") {
          throw new Error(
            "Beklenmeyen kaynak goruntu formati"
          );
        }

        if (!active) return;

        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      } catch (err) {
        if (active && !controller.signal.aborted) {
          setError(
            err instanceof Error
              ? err.message
              : "Kaynak goruntusu alinamadi"
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
  }, [token, code, category]);

  return (
    <div className="stack">
      <h3>PDF Üzerinde Kaynak Kanıtı</h3>

      {loading && (
        <p role="status">
          Kaynak görüntüsü hazırlanıyor...
        </p>
      )}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {src && (
        <img
          src={src}
          alt={`${code} pozunun PDF kaynak satırı`}
          style={{
            display: "block",
            maxWidth: "100%",
            height: "auto",
            border: "1px solid #dbe3ef",
            borderRadius: 8,
          }}
        />
      )}

      <p className="hint">
        Gerçek PDF'den oluşturulan salt okunur görüntü.
        Kaynak dosya değiştirilmez.
      </p>
    </div>
  );
}
