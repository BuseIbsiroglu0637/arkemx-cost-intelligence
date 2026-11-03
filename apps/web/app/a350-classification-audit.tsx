"use client";

import {useEffect, useRef, useState} from "react";
import styles from "./metraj-understanding-preview.module.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const EXPECTED = "a3501-work-object-v1";
const LABELS: Record<string, string> = {
  gazbeton_wall: "Gazbeton duvar", brick_wall: "Tuğla duvar",
  ceramic_surface: "Seramik / karo kaplama",
  pvc_floor: "PVC zemin kaplaması", pvc_profile: "PVC profil",
  pvc_pipework: "PVC boru/tesisat", pvc_joinery: "PVC doğrama",
  plaster_cement: "Çimento sıva", plaster_gypsum: "Alçı sıva",
  plaster_generic: "Sıva (bağlayıcı belirsiz)",
  cement_surface_coating: "Çimento esaslı yüzey kaplama",
  plumbing_tap: "Musluk / batarya", plumbing_fixture: "Sıhhi tesisat",
  waterproofing: "Su yalıtımı", thermal_insulation: "Isı yalıtımı",
  paint: "Boya", window_door: "Kapı / pencere",
  concrete_work: "Beton imalatı", steel_structure: "Çelik konstrüksiyon",
  electrical_work: "Elektrik tesisatı", hvac_work: "Havalandırma",
  demolition: "Söküm (nesne belirsiz)", unknown: "Belirlenemedi",
  multiple: "Birden fazla imalat",
};
type Summary = {
  classified_count: number;
  review_count: number;
  by_class: Record<string, number>;
  by_status: Record<string, number>;
  by_source_role: Record<string, number>;
};
type Audit = {
  version: string; read_only: true; approval_allowed: false;
  cost_allowed: false; matching_performed: false;
  summary: Summary;
};
type ExcelAudit = Audit & {
  total_rows: number;
  source: {project_id: string; import_id: string; excel_sha256: string};
  review_examples: {
    source_row: number; work_item_id: string; description: string;
    class_key: string; review_reasons: string[];
  }[];
};
type CatalogAudit = Audit & {
  total_records: number;
  source: {source_sha256: string; edition_date: string};
};

async function fetchAudit<T>(path: string, token: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(API + path, {
    headers: {Authorization: "Bearer " + token},
    cache: "no-store", signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as {detail?: string} | null;
    throw Error(error?.detail ?? "HTTP " + response.status);
  }
  return await response.json() as T;
}
const sortedClasses = (counts: Record<string, number>) =>
  Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);

export default function ClassificationAudit({
  token, project, importId,
}: {token: string; project: string; importId: string}) {
  const [excel, setExcel] = useState<ExcelAudit | null>(null);
  const [catalog, setCatalog] = useState<CatalogAudit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function inspect() {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setLoading(true);
    setError("");
    setExcel(null);
    setCatalog(null);
    try {
      const [x, c] = await Promise.all([
        fetchAudit<ExcelAudit>(
          "/api/projects/" + project + "/a350/imports/" + importId +
          "/classification?offset=0&limit=20", token, current.signal,
        ),
        fetchAudit<CatalogAudit>(
          "/api/a350/catalog/classification", token, current.signal,
        ),
      ]);
      if (current.signal.aborted) return;
      if (x.version !== EXPECTED || c.version !== EXPECTED) {
        throw Error("Güncel A3.50.1 API sürümü çalışmıyor. API'yi 8000 portunda yeniden başlat.");
      }
      if (x.read_only !== true || c.read_only !== true ||
          x.approval_allowed !== false || c.approval_allowed !== false ||
          x.cost_allowed !== false || c.cost_allowed !== false ||
          x.matching_performed !== false || c.matching_performed !== false ||
          x.source.import_id !== importId || x.source.project_id !== project) {
        throw Error("Sınıflandırma kaynakları ve güvenlik bilgileri doğrulanamadı.");
      }
      setExcel(x);
      setCatalog(c);
    } catch (e) {
      if (!current.signal.aborted) setError(e instanceof Error ? e.message : "Sınıflandırma raporu alınamadı.");
    } finally {
      if (!current.signal.aborted) setLoading(false);
    }
  }

  return <details className={styles.auditPanel}>
    <summary>İmalat sınıflandırma raporu <span>Yeni · A3.50.1</span></summary>
    <p className={styles.hint}>Excel metrajını ve 2026 resmî pozlarını aynı imalat sınıflarına ayırır.
      <strong> Bu, doğru poz bulma oranı değildir.</strong></p>
    <button type="button" disabled={loading} onClick={() => void inspect()}>
      {loading ? "408 satır ve katalog inceleniyor…" : "İmalatları sınıflandır"}
    </button>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {excel && catalog && <div className={styles.auditResults}>
      <div className={styles.auditSummary}>
        <section>
          <strong>Excel metrajı</strong>
          <div className={styles.auditBig}>{excel.total_rows.toLocaleString("tr-TR")} satır</div>
          <p>İmalatı tanınan: <b>{excel.summary.classified_count.toLocaleString("tr-TR")}</b></p>
          <p>Belirsiz / kontrol gerekli: <b>{excel.summary.review_count.toLocaleString("tr-TR")}</b></p>
        </section>
        <section>
          <strong>2026 poz kütüphanesi</strong>
          <div className={styles.auditBig}>{catalog.total_records.toLocaleString("tr-TR")} poz</div>
          <p>İmalatı tanınan: <b>{catalog.summary.classified_count.toLocaleString("tr-TR")}</b></p>
          <p>Belirsiz / kontrol gerekli: <b>{catalog.summary.review_count.toLocaleString("tr-TR")}</b></p>
        </section>
      </div>
      <div className={styles.auditClassGrid}>
        <div>
          <strong>Excel'deki en sık imalat grupları</strong>
          {sortedClasses(excel.summary.by_class).map(([classKey, count]) =>
            <p key={classKey}>{LABELS[classKey] ?? classKey} <b>{count}</b></p>)}
        </div>
        <div>
          <strong>Resmî PDF'deki en sık gruplar</strong>
          {sortedClasses(catalog.summary.by_class).map(([classKey, count]) =>
            <p key={classKey}>{LABELS[classKey] ?? classKey} <b>{count}</b></p>)}
        </div>
      </div>
      {excel.review_examples.length > 0 && <details className={styles.auditExamples}>
        <summary>Önce incelenmesi gereken Excel açıklamaları</summary>
        {excel.review_examples.map(item => <p key={item.work_item_id}>
          <b>Satır {item.source_row} · {LABELS[item.class_key] ?? item.class_key}:</b>
          {" "}{item.description}
        </p>)}
      </details>}
      <p className={styles.hint}>Kaynaklar: Excel SHA {excel.source.excel_sha256.slice(0, 12)}… ·
        PDF SHA {catalog.source.source_sha256.slice(0, 12)}… · {catalog.source.edition_date}.
        Veriler değiştirilmedi; mühendis onayı veya fiyat eşleştirmesi yapılmadı.</p>
    </div>}
  </details>;
}
