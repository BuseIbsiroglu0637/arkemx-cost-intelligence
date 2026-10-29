"use client";

import { useEffect, useRef, useState } from "react";

type Action = "reject_candidate" | "request_information";
type Assessment = { id: string; record_id: string; work_item_id: string; action: Action; reason: string; created_by_id: string; created_at: string; candidate_code: string | null; revision_id: string | null; snapshot_sha256: string; approval_allowed: boolean; engineering_approval: boolean };
type History = { record_id: string; work_item_id: string; snapshot_sha256: string; approval_allowed: boolean; engineering_approval: boolean; assessment_allowed: boolean; latest_id: string | null; currentness: { status: string }; events: Assessment[]; next_offset: number | null };
type Props = { api: string; projectId: string; recordId: string; itemId: string; snapshot: string; candidate: string | null; disabled: boolean; onExpired: () => void };
const actionLabel = { reject_candidate: "Adayı reddet", request_information: "Ek bilgi iste" };

export default function AssessmentPanel({ api, projectId, recordId, itemId, snapshot, candidate, disabled, onExpired }: Props) {
  const [history, setHistory] = useState<History | null>(null);
  const [action, setAction] = useState<Action>(candidate ? "reject_candidate" : "request_information");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const controllerRef = useRef<AbortController | null>(null);
  const attempt = useRef<{ basis: string; key: string } | null>(null);
  const base = `${api}/api/projects/${encodeURIComponent(projectId)}/a3/reviews/${encodeURIComponent(recordId)}/assessments`;
  useEffect(() => () => { controllerRef.current?.abort(); }, []);

  async function send<T>(url: string, init: RequestInit = {}): Promise<T | null> {
    controllerRef.current?.abort();
    const controller = new AbortController(); controllerRef.current = controller;
    const token = sessionStorage.getItem("arkemx_dev_token");
    if (!token) { setHistory(null); onExpired(); return null; }
    try {
      const response = await fetch(url, { ...init, cache: "no-store", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, ...(init.body ? { "Content-Type": "application/json" } : {}) } });
      if (controller.signal.aborted || sessionStorage.getItem("arkemx_dev_token") !== token) return null;
      if (response.status === 401) { sessionStorage.removeItem("arkemx_dev_token"); setHistory(null); onExpired(); return null; }
      if (!response.ok) {
        if (response.status === 409) { setHistory(null); throw new Error("İnceleme veya değerlendirme geçmişi değişmiş olabilir. Geçmişi yenile; kaynak değiştiyse yeni karşılaştırma yapıp kaydet."); }
        throw new Error(response.status === 422 ? "İşlemi ve 10–1000 karakterlik gerekçeyi kontrol et." : `Değerlendirme işlemi tamamlanamadı (HTTP ${response.status}).`);
      }
      const data = await response.json() as T;
      if (controller.signal.aborted || sessionStorage.getItem("arkemx_dev_token") !== token) return null;
      return data;
    } catch (err) {
      if (!controller.signal.aborted) throw err;
      return null;
    }
  }
  function validEvent(event: Assessment) {
    return event.record_id === recordId && event.work_item_id === itemId && event.snapshot_sha256 === snapshot &&
      event.approval_allowed === false && event.engineering_approval === false && event.action in actionLabel;
  }
  async function fetchHistory(offset = 0) {
    const data = await send<History>(`${base}?work_item_id=${encodeURIComponent(itemId)}&offset=${offset}`);
    if (!data) return;
    if (data.record_id !== recordId || data.work_item_id !== itemId || data.snapshot_sha256 !== snapshot ||
        data.approval_allowed !== false || data.engineering_approval !== false || data.events.some(event => !validEvent(event))) {
      setHistory(null); throw new Error("Değerlendirme geçmişinin kaynak kimliği doğrulanamadı.");
    }
    setHistory(previous => offset && previous ? { ...data, events: [...previous.events, ...data.events] } : data);
  }
  async function loadHistory(offset = 0) {
    setBusy(true); setError("");
    try { await fetchHistory(offset); } catch (err) { setError(err instanceof Error ? err.message : "Geçmiş yüklenemedi."); }
    finally { setBusy(false); }
  }
  async function submit() {
    if (!history?.assessment_allowed || history.currentness.status !== "unchanged" || busy || disabled || reason.trim().length < 10) return;
    const basis = JSON.stringify({ action, reason: reason.trim(), latest: history.latest_id });
    if (attempt.current?.basis !== basis) attempt.current = { basis, key: crypto.randomUUID() };
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await send<Assessment>(base, { method: "POST", body: JSON.stringify({ work_item_id: itemId, action,
        reason: reason.trim(), expected_snapshot_sha256: snapshot, expected_previous_id: history.latest_id, request_key: attempt.current.key }) });
      if (!data) return;
      if (!validEvent(data)) { setHistory(null); throw new Error("Kaydedilen değerlendirmenin kanıt bağlantısı doğrulanamadı."); }
      setReason(""); attempt.current = null;
      setNotice("Değerlendirme kaydedildi. Teknik sonuç ve maliyet değiştirilmedi.");
      await fetchHistory();
    } catch (err) { setError(err instanceof Error ? err.message : "Değerlendirme kaydedilemedi."); }
    finally { setBusy(false); }
  }
  const allowed = history?.assessment_allowed && history.currentness.status === "unchanged";
  return <section aria-labelledby="assessment-heading">
    <h3 id="assessment-heading">Satır değerlendirmesi</h3>
    <p>Bu kayıt ve seçili satır için gerekçeli değerlendirme ekle. Mühendis onayı verilmez; M4 kararları ve maliyet taslakları değişmez.</p>
    <button type="button" className="secondary" disabled={busy || disabled} onClick={() => void loadHistory()}>Değerlendirme geçmişini getir / yenile</button>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {!history && <p>Değerlendirme eklemek için önce geçmişi yükle.</p>}
    {history && <>
      {!allowed && <p role="status">Güncellik doğrulanamadığı için yeni değerlendirme kapalı. Güncel satırlarla yeniden karşılaştırıp yeni inceleme kaydet.</p>}
      <form onSubmit={event => { event.preventDefault(); void submit(); }}>
        <fieldset disabled={busy || disabled || !allowed}>
          <legend>Yeni değerlendirme</legend>
          <label>İşlem<select value={action} onChange={event => setAction(event.target.value as Action)}>
            <option value="reject_candidate" disabled={!candidate}>Adayı reddet</option>
            <option value="request_information">Ek bilgi iste</option>
          </select></label>
          <label>Gerekçe<textarea value={reason} minLength={10} maxLength={1000} required rows={3} onChange={event => setReason(event.target.value)} placeholder="Hangi teknik fark veya eksik bilgi nedeniyle bu değerlendirmeyi yapıyorsun?" /></label>
          <p>Gerekçe 10–1000 karakter olmalı. Yeni değerlendirme geçmişe eklenir; önceki kayıt silinmez.</p>
          <button type="submit" disabled={reason.trim().length < 10 || reason.length > 1000}>Değerlendirmeyi kaydet</button>
        </fieldset>
      </form>
      <h4>Değerlendirme geçmişi · yalnızca bu kayıt ve satır</h4>
      {history.events.length ? <ol>{history.events.map(event => <li key={event.id}>
        <strong>{actionLabel[event.action]}</strong> · {new Date(event.created_at).toLocaleString("tr-TR")}
        <p>{event.reason}</p><small>Değerlendiren kullanıcı: {event.created_by_id} · Poz: {event.candidate_code ?? "Seçilmedi"}</small>
      </li>)}</ol> : <p>Bu satır için henüz değerlendirme yok.</p>}
      {history.next_offset !== null && <button type="button" className="secondary" disabled={busy || disabled} onClick={() => void loadHistory(history.next_offset!)}>Önceki değerlendirmeleri getir</button>}
    </>}
  </section>;
}
