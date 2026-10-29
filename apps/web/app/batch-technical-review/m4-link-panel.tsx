"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

type Candidate = { run_id: string; candidate_id: string; position_id: string; code: string; catalog_version_id: string; catalog_year: number; catalog_period: string; catalog_institution: string; evidence_sha256: string | null; evidence_status: string | null; existing_gate_can_approve: boolean; latest_decision: string | null; latest_assessment: string | null };
type Result = { schema: string; read_only: boolean; approval_allowed: boolean; engineering_approval: boolean; record_id: string; work_item_id: string; snapshot_sha256: string; candidate_code: string | null; link_status: string; ready_for_m4_review: boolean; flags: string[]; checks: { code: string; status: string }[]; m4_candidate: Candidate | null };
type Props = { api: string; projectId: string; recordId: string; itemId: string; snapshot: string; candidate: string | null; disabled: boolean; onExpired: () => void };
const checks: Record<string, string> = {
  A3_REVIEW_CURRENT: "Kayıtlı A3 incelemesi güncel olmalı.", A3_FEATURES_MATCH: "A3'te kontrol edilen özellikler eşleşmeli.",
  A3_PRICE_SOURCE_VERIFIED: "A3 fiyat kaynağı doğrulanmış olmalı.", CANDIDATE_SELECTED: "İncelenecek poz adayı seçilmiş olmalı.",
  M4_RUN_FOUND: "Bu proje için M4.1 veya M4.3 kanıtlı eşleştirme çalışması bulunmalı.", M4_IMPORT_MATCH: "M4 çalışması aynı Excel aktarımına ait olmalı.",
  M4_CATALOG_RIGHTS_ACTIVE: "Kataloğun kullanım izni geçerli olmalı.", M4_IMPORT_CURRENT: "M4 çalışması güncel ve incelemeye açık aktarımı kullanmalı.",
  M4_CANDIDATE_UNIQUE: "Güncel M4 çalışmasında aynı satır ve poz kodu için tek bir aday bulunmalı.", M4_POSITION_VERSION_MATCH: "Poz doğru katalog sürümüne bağlı olmalı.",
  M4_REVISION_MATCH: "M4 satırının revizyonu ve açıklaması A3 kaydıyla aynı olmalı.", M4_EVIDENCE_REFERENCES_MATCH: "M4 kanıtı aynı Excel, satır, revizyon ve katalog kimliklerini göstermeli.",
  M4_EVIDENCE_TEXT_MATCH: "M4 kanıtındaki metin kimlikleri güncel metinlerle eşleşmeli.", PDF_SOURCE_REVALIDATED: "Kaynak PDF yeniden doğrulanabilmeli.",
  CATALOG_PDF_TEXT_MATCH: "Katalogdaki tam teknik tarif PDF tarifiyle birebir eşleşmeli; kısa başlık yeterli değildir.", CATALOG_PDF_UNIT_MATCH: "Katalog ve PDF birimi eşleşmeli.",
  CATALOG_PDF_YEAR_MATCH: "Katalog yılı PDF fiyat yılıyla eşleşmeli.", M4_EVIDENCE_CURRENT: "M4 kanıtı güncel olmalı.",
  M4_EXISTING_GATES_PASS: "Mevcut M4 güvenlik kontrolleri sağlanmalı. A3 eşleşmesi bu kontrolleri kaldırmaz.", M4_CANDIDATE_UNDECIDED: "Önceden karar verilen adayın değişikliği ayrı karar incelemesi gerektirir.",
  A3_ASSESSMENT_REQUIRES_REVIEW: "Bu kayıttaki ret veya ek bilgi değerlendirmesi ayrıca incelenmeli.",
};
export default function M4LinkPanel({ api, projectId, recordId, itemId, snapshot, candidate, disabled, onExpired }: Props) {
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function inspect() {
    controller.current?.abort(); const active = new AbortController(); controller.current = active;
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) { setResult(null); onExpired(); return; }
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch(`${api}/api/projects/${encodeURIComponent(projectId)}/a3/reviews/${encodeURIComponent(recordId)}/m4-link?work_item_id=${encodeURIComponent(itemId)}`, {
        cache: "no-store", signal: active.signal, headers: { Authorization: `Bearer ${token}` },
      });
      if (active.signal.aborted || sessionStorage.getItem("arkemx_dev_token") !== token) return;
      if (response.status === 401) { sessionStorage.removeItem("arkemx_dev_token"); onExpired(); return; }
      if (!response.ok) throw new Error(response.status === 409 ? "İnceleme veya M4 kanıt bütünlüğü doğrulanamadı. Kaynakları yeniden incele." : `M4 bağlantısı kontrol edilemedi (HTTP ${response.status}).`);
      const data = await response.json() as Result;
      if (active.signal.aborted || sessionStorage.getItem("arkemx_dev_token") !== token) return;
      if (data.schema !== "arkemx.a3_m4_link.v1" || data.read_only !== true || data.approval_allowed !== false || data.engineering_approval !== false ||
          data.record_id !== recordId || data.work_item_id !== itemId || data.snapshot_sha256 !== snapshot || data.candidate_code !== candidate ||
          (data.m4_candidate && data.m4_candidate.code !== candidate)) throw new Error("Bağlantı yanıtının kaynak kimliği doğrulanamadı.");
      setResult(data);
    } catch (err) { if (!active.signal.aborted) setError(err instanceof Error ? err.message : "M4 bağlantısı kontrol edilemedi."); }
    finally { if (!active.signal.aborted) setBusy(false); }
  }
  return <section aria-labelledby="m4-link-heading">
    <h3 id="m4-link-heading">Mühendis kararına geçiş · aday kimliği</h3>
    <p>A3 incelemesini mevcut M4 eşleştirme adayıyla karşılaştır. Bu kontrol aday oluşturmaz, onay vermez ve maliyeti değiştirmez.</p>
    <button type="button" className="secondary" disabled={busy || disabled} onClick={() => void inspect()}>{busy ? "Bağlantı kontrol ediliyor…" : "M4 aday bağlantısını kontrol et"}</button>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <>
      <p role="status"><strong>{result.link_status === "linked" ? "Aynı satır, poz ve teknik tarif bağlantısı doğrulandı." : "A3 kaydı ile M4 adayı arasındaki bağlantı henüz doğrulanamadı."}</strong></p>
      <p>{result.ready_for_m4_review ? "Kontrol anında incelemeye geçiş koşulları sağlandı. Karar sırasında tekrar doğrulanması gerekir." : "Mühendis kararına geçiş için aşağıdaki eksikler giderilmeli."}</p>
      {result.flags.length > 0 && <ul>{result.flags.map(flag => <li key={flag}>{checks[flag] ?? flag}</li>)}</ul>}
      {result.flags.includes("M4_RUN_FOUND") && <p>Önce katalog adayları bölümünde bu proje için kanıtlı eşleştirme çalışması oluşturulmalı. Bu düğme çalışmayı otomatik başlatmaz.</p>}
      {result.m4_candidate && <details><summary>Bağlanan aday ve kanıt kimlikleri</summary>
        <p>Poz: {result.m4_candidate.code} · Katalog: {result.m4_candidate.catalog_institution} · {result.m4_candidate.catalog_year} / {result.m4_candidate.catalog_period}</p>
        <p>Çalışma: <code>{result.m4_candidate.run_id}</code></p><p>Aday: <code>{result.m4_candidate.candidate_id}</code></p>
        <p>Katalog sürümü: <code>{result.m4_candidate.catalog_version_id}</code></p><p>Kanıt: <code>{result.m4_candidate.evidence_sha256 ?? "Bulunamadı"}</code></p>
        <p>M4 kanıt durumu: {result.m4_candidate.evidence_status ?? "Eksik"}</p>
      </details>}
      <details><summary>Yapılan bağlantı kontrolleri</summary><ul>{result.checks.map(check => <li key={check.code}>{check.status === "match" ? "✓ Sağlandı: " : "İnceleme gerekli: "}{checks[check.code] ?? check.code}</li>)}</ul></details>
      <p>Bu sonuç yalnızca kontrol anını gösterir. M4 kararları bu sürümde A3 kaydına bağlanarak kaydedilmez.</p>
      <Link href="/#technical">Katalog adayları ve mühendis karar seçeneklerine git →</Link>
    </>}
  </section>;
}
