"use client";

/** Read-only quantity × manually entered price sandbox. No cost API writes. */
import { useEffect, useState } from "react";
import { readWorkspace } from "./workspace-context";
import styles from "./cost-scenario-preview.module.css";

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
type Imported = { id: string; filename: string; sheet: string };
type Item = {
  work_item_id: string; source_row: number; effective_description: string;
  quantity: string | null; unit: string | null; input_review_required: boolean;
};
type Selection = {read_only: true; approval_allowed: false; rows: Item[];
  next_offset: number | null; import_source: {import_id: string; project_id: string; filename: string}};
type Status = {work_item_id: string; status: string; engineering_approved: false; cost_allowed: false};
type Readiness = {read_only: true; approval_allowed: false; engineering_approved: false;
  cost_allowed: false; import_id: string; rows: Status[]};
async function get<T>(path: string, token: string): Promise<T> {
  const r = await fetch(API + path, {cache: "no-store", headers: {Authorization: "Bearer " + token}});
  if (!r.ok) throw Error("Veri okunamadı (HTTP " + r.status + ").");
  return r.json() as Promise<T>;
}
/** Money is exact integer kuruş. Quantities are read as fixed 4 decimal places. */
function fixed(value: string, precision: number): bigint | null {
  const raw = value.trim().replace(",", ".");
  if (!/^\d{1,9}(?:\.\d{1,4})?$/.test(raw)) return null;
  const parts = raw.split(".");
  if ((parts[1] ?? "").length > precision) return null;
  return BigInt(parts[0]) * BigInt(10 ** precision) +
    BigInt((parts[1] ?? "").padEnd(precision, "0") || "0");
}
function amountInKurus(item: Item, typed: string): bigint | null {
  if (item.input_review_required || !item.unit || !item.quantity || !typed.trim()) return null;
  const quantity = fixed(item.quantity, 4);
  const price = fixed(typed, 2);
  if (quantity === null || price === null || quantity <= BigInt(0) || price <= BigInt(0)) return null;
  const scale = BigInt(10000);
  return (quantity * price + scale / BigInt(2)) / scale;
}
function formatKurus(value: bigint): string {
  const whole = (value / BigInt(100)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return whole + "," + (value % BigInt(100)).toString().padStart(2, "0") + " ₺";
}
export default function CostScenarioPreview({token,project}:{token:string|null;project:string}) {
  const [imports,setImports] = useState<Imported[]>([]);
  const [importId,setImportId] = useState("");
  const [selection,setSelection] = useState<Selection|null>(null);
  const [statuses,setStatuses] = useState<Record<string,string>>({});
  const [prices,setPrices] = useState<Record<string,string>>({});
  const [priceSource,setPriceSource] = useState("");
  const [offset,setOffset] = useState(0);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");

  useEffect(()=>{
    setImports([]);setImportId("");setSelection(null);setPrices({});setStatuses({});
    if (!token || !project) return;
    let active = true; setBusy(true);setError("");
    void get<Imported[]>("/api/projects/" + encodeURIComponent(project) + "/imports",token)
      .then(data=>{
        if(!active)return;
        setImports(data);
        const saved=readWorkspace(token);
        setImportId(data.find(x=>x.id===(saved?.projectId===project?saved.importId:null))?.id ?? data[0]?.id ?? "");
      }).catch(e=>{if(active)setError(e instanceof Error?e.message:"Excel bulunamadı.");})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[token,project]);

  useEffect(()=>{
    setSelection(null);setStatuses({});
    if(!token||!project||!importId)return;
    let active=true;setBusy(true);setError("");
    const base="/api/projects/"+encodeURIComponent(project);
    void Promise.all([
      get<Selection>(base+"/a3/imports/"+encodeURIComponent(importId)+"/items?limit=20&offset="+offset,token),
      get<Readiness>(base+"/a327/imports/"+encodeURIComponent(importId)+"/readiness?limit=20&offset="+offset,token),
    ]).then(([items,review])=>{
      if(!active)return;
      if(items.read_only!==true||items.approval_allowed!==false||
         items.import_source.project_id!==project||items.import_source.import_id!==importId||
         review.read_only!==true||review.approval_allowed!==false||
         review.engineering_approved!==false||review.cost_allowed!==false||
         review.import_id!==importId||review.rows.length!==items.rows.length||
         review.rows.some((r,i)=>r.work_item_id!==items.rows[i].work_item_id||
           r.engineering_approved!==false||r.cost_allowed!==false)) {
        throw Error("Maliyet önizlemesi için kaynak güvenlik kontrolü başarısız.");
      }
      setSelection(items);setStatuses(Object.fromEntries(review.rows.map(r=>[r.work_item_id,r.status])));
    }).catch(e=>{if(active)setError(e instanceof Error?e.message:"Metraj yüklenemedi.");})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[token,project,importId,offset]);

  const lines = (selection?.rows??[]).map(item=>({
    ...item, price:prices[item.work_item_id]??"",
    amount:amountInKurus(item,prices[item.work_item_id]??""),
  }));
  const counted=lines.filter(x=>x.amount!==null);
  const subtotal=counted.reduce((sum,item)=>sum+(item.amount??BigInt(0)),BigInt(0));
  const malformed=lines.filter(x=>x.price.trim()&&x.amount===null);
  return <section className={styles.panel} aria-label="Onaysız ön maliyet senaryosu">
    <div className={styles.heading}>
      <div><span className={styles.kicker}>A3.28 · MALİYET ÖN HAZIRLIK</span>
        <h2>Ön maliyet senaryosu</h2>
        <p>Metrajdaki miktarlara kendi varsayımsal birim fiyatını girerek etkisini gör.</p>
      </div><span className={styles.tag}>Sadece deneme · Kaydedilmez</span>
    </div>
    <p className={styles.warning}>
      <strong>Onaysız deneme hesabı.</strong> Bu ekran resmî rayiç, kesin maliyet, teklif veya mühendis onayı üretmez.
      Kaba/ince sıvanın aynı kapsamı iki kez fiyatlandırma riski kontrol edilmedi. Sonuçları sözleşmede kullanma.
    </p>
    <div className={styles.source}>
      <label>Excel metrajı
        <select value={importId} onChange={e=>{setImportId(e.target.value);setOffset(0);setPrices({});}}>
          <option value="">Excel seç</option>
          {imports.map(i=><option key={i.id} value={i.id}>{i.filename} · {i.sheet}</option>)}
        </select>
      </label>
      <label>Birim fiyat dayanağı (senaryo notu)
        <input value={priceSource} maxLength={160} onChange={e=>setPriceSource(e.target.value)}
          placeholder="Örn. Tedarikçi teklifi, varsayımsal fiyat" />
      </label>
    </div>
    {busy&&<p role="status">Metraj bilgileri yükleniyor…</p>}
    {error&&<p role="alert" className={styles.error}>{error}</p>}
    {!busy && selection && <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>İmalat</th><th>Miktar</th><th>Deneme fiyatı (₺/birim)</th><th>Ön tutar</th></tr></thead>
        <tbody>{lines.map(row=><tr key={row.work_item_id}>
          <td><strong>#{row.source_row} · {row.effective_description}</strong><small>
            {statuses[row.work_item_id]==="documented_for_review"?
              "Poz ön kontrolü mevcut · Mühendis onayı yok":"Teknik inceleme bekliyor"}
          </small></td>
          <td>{row.quantity??"—"} {row.unit??""}</td>
          <td><input inputMode="decimal" aria-label={"Satır "+row.source_row+" deneme birim fiyatı"}
            placeholder="Örn. 1250,00" value={row.price} maxLength={15}
            onChange={e=>setPrices(v=>({...v,[row.work_item_id]:e.target.value}))}/></td>
          <td>{row.amount===null?"—":formatKurus(row.amount)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {malformed.length>0&&<p role="alert" className={styles.error}>
      {malformed.length} fiyat veya miktar hesaplanamadı. Pozitif değer gir; fiyat en fazla 2 ondalık basamak içermeli.
    </p>}
    {selection&&<div className={styles.total}>
      <div><small>Fiyat girilmiş {counted.length}/{selection.rows.length} satırın deneme toplamı (yalnızca bu sayfa)</small>
        <strong>{counted.length?formatKurus(subtotal):"—"}</strong>
        <small>{priceSource.trim().length<10?"Fiyat dayanağını en az 10 karakterle belirt; senaryonun kaynağı belirsiz.":"Dayanak: "+priceSource}</small>
      </div>
      <span>Gerçek maliyet toplamı değil</span>
    </div>}
    {selection&&<div className={styles.pager}>
      <button type="button" className="secondary" disabled={busy||offset===0}
        onClick={()=>setOffset(v=>Math.max(0,v-20))}>Önceki</button>
      <span>Sayfa {Math.floor(offset/20)+1}</span>
      <button type="button" className="secondary" disabled={busy||selection.next_offset===null}
        onClick={()=>setOffset(selection.next_offset??offset)}>Sonraki</button>
    </div>}
    <p className={styles.note}>
      Bu fiyatlar yalnızca tarayıcıda tutulur ve maliyet kayıtlarına eklenmez.
      Aşağıdaki resmî M5 maliyet taslağına yalnızca yetkili teknik onayı tamamlanmış pozlar alınabilir.
    </p>
  </section>;
}