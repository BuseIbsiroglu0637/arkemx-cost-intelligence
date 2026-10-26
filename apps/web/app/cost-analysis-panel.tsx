"use client";
import {useEffect,useState} from "react";

type History = {id:string;title:string;total:string;currency:string;created_at:string};
type ComparisonRow = {work_item_id:string;source_row:number;description:string;status:string;
 matching_basis:string;baseline_work_item_id:string|null;target_work_item_id:string|null;
 baseline_position:string|null;target_position:string|null;baseline_quantity:string|null;
 target_quantity:string|null;baseline_unit_price:string|null;target_unit_price:string|null;
 baseline_amount:string;target_amount:string;difference:string;
 baseline_price_source:string|null;target_price_source:string|null;
 price_effect:string;quantity_effect:string;rounding_adjustment:string;
 unattributed_effect:string};
type Comparison = {status:string;baseline_total:string;target_total:string;difference:string;
 breakdown:{price_effect:string;quantity_effect:string;rounding_adjustment:string;unattributed_effect:string};
 counts:Record<string,number>;verified_cross_import_pairs:number;ambiguous_identity_groups:number;
 total_rows:number;page:number;page_size:number;rows:ComparisonRow[]};
type SnapshotLine = {candidate_id:string;source_row:number;position_code:string;description:string;
 quantity:string;unit_price:string;unit:string};
type Snapshot = {id:string;title:string;total:string;lines:SnapshotLine[]};
type SimLine = {source_row:number;position_code:string;difference:string;quantity_effect:string;
 price_effect:string;rounding_adjustment:string;baseline_amount:string;scenario_amount:string};
type Simulation = {status:string;persisted:boolean;baseline_total:string;
 simulated_total:string;difference:string;rows:SimLine[]};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";
const linkLabels:Record<string,string>={
 verified_cross_import:"Doğrulanmış revizyon bağlantısı",
 original_work_item:"Aynı kayıt",
 unmatched_requires_review:"Belirsiz — inceleme gerekli",
 unmatched:"Bağlantı bulunamadı"
};
const labels:Record<string,string>={
 unchanged:"Değişmedi",price_only:"Fiyat değişti",quantity_only:"Miktar değişti",
 quantity_and_price:"Fiyat + miktar",scope_changed:"Poz / kapsam değişti",
 source_changed:"Fiyat kaynağı değişti",added:"Eklendi",removed:"Çıkarıldı"
};
function errorText(e:unknown){return e instanceof Error?e.message:String(e);}
async function call<T>(path:string,token:string,body?:unknown):Promise<T>{
 const r=await fetch(BASE+path,{method:body?"POST":"GET",cache:"no-store",
 headers:{Authorization:"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},
 body:body?JSON.stringify(body):undefined});
 if(!r.ok){const error=await r.json().catch(()=>({detail:"HTTP "+r.status}));
  throw new Error(typeof error.detail==="string"?error.detail:"HTTP "+r.status);}
 return r.json() as Promise<T>;
}
const money=(n:string)=>new Intl.NumberFormat("tr-TR",{minimumFractionDigits:2,maximumFractionDigits:2})
 .format(Number(n))+" TL";
const diff=(n:string)=>(Number(n)>0?"+":"")+money(n);

export default function CostAnalysisPanel({token,project,history}:{
 token:string|null;project:string;history:History[]
}){
 const [baseline,setBaseline]=useState("");
 const [target,setTarget]=useState("");
 const [page,setPage]=useState(1);
 const [compare,setCompare]=useState<Comparison|null>(null);
 const [scenarioId,setScenarioId]=useState("");
 const [snapshot,setSnapshot]=useState<Snapshot|null>(null);
 const [candidateId,setCandidateId]=useState("");
 const [quantity,setQuantity]=useState("");
 const [unitPrice,setUnitPrice]=useState("");
 const [simulation,setSimulation]=useState<Simulation|null>(null);
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 useEffect(()=>{
  setBaseline(v=>history.some(d=>d.id===v)?v:(history[history.length-1]?.id??""));
  setTarget(v=>history.some(d=>d.id===v)?v:(history[0]?.id??""));
  setScenarioId(v=>history.some(d=>d.id===v)?v:(history[history.length-1]?.id??""));
 },[history]);
 useEffect(()=>{setCompare(null);setSnapshot(null);setSimulation(null);setError("");},[project]);
 useEffect(()=>{
  if(!token||!project||!scenarioId){setSnapshot(null);return;}
  let active=true;setSnapshot(null);setSimulation(null);
  call<Snapshot>("/api/projects/"+project+"/m5/estimates/"+scenarioId,token)
   .then(data=>{
    if(!active)return;
    setSnapshot(data);
    const first=data.lines[0];
    setCandidateId(first?.candidate_id??"");
    setQuantity(first?.quantity??"");
    setUnitPrice(first?.unit_price??"");
   }).catch(e=>{if(active){setError(errorText(e));setSnapshot(null);}});
  return()=>{active=false;};
 },[token,project,scenarioId]);
 async function fetchComparison(p:number){
  if(!token||!baseline||!target||baseline===target)return;
  setBusy(true);setError("");
  try{
   const qs=new URLSearchParams({baseline_id:baseline,target_id:target,
    page:String(p),page_size:"20"});
   setCompare(await call<Comparison>("/api/projects/"+project+"/m51/compare?"+qs,token));
   setPage(p);
  }catch(e){setCompare(null);setError(errorText(e));}
  finally{setBusy(false);}
 }
 async function simulate(){
  if(!token||!snapshot||!candidateId)return;
  setBusy(true);setError("");
  try{
   const data=await call<Simulation>("/api/projects/"+project+"/m51/simulate",token,{
    estimate_id:snapshot.id,changes:[{
     candidate_id:candidateId,quantity:quantity.trim(),unit_price:unitPrice.trim()
    }]
   });
   setSimulation(data);
  }catch(e){setSimulation(null);setError(errorText(e));}
  finally{setBusy(false);}
 }
 function selectCandidate(id:string){
  const row=snapshot?.lines.find(item=>item.candidate_id===id);
  setCandidateId(id);setQuantity(row?.quantity??"");setUnitPrice(row?.unit_price??"");
  setSimulation(null);
 }
 const validPrice=/^[0-9]{1,9}(\.[0-9]{1,4})?$/;
 const canSimulate=Boolean(!busy&&snapshot&&candidateId&&validPrice.test(quantity)
   &&validPrice.test(unitPrice)&&Number(quantity)>0&&Number(unitPrice)>0);
 return <details className="card m51-card">
  <summary>M5.1 · Akıllı maliyet karşılaştırması ve revizyon simülasyonu</summary>
  <div className="m51-body">
   <p className="m51-note">Yalnızca kayıtlı, bütünlüğü doğrulanmış sentetik M5 taslakları kullanılır.
     Karşılaştırma ve simülasyon eski metrajı, mühendis kararını veya maliyet taslaklarını değiştirmez.
     Bu bir nihai teklif veya gerçek fiyat değerlendirmesi değildir.</p>
   {error&&<p role="alert" className="error">{error}</p>}
   <div className="stack">
    <h3 className="m51-subtitle">İki kayıtlı taslağı karşılaştır</h3>
    <div className="m51-fields">
     <label>Önceki taslak
      <select value={baseline} onChange={e=>{setBaseline(e.target.value);setCompare(null);setPage(1);}}>
       <option value="">Taslak seçin</option>
       {history.map(h=><option key={h.id} value={h.id}>
        {h.title} · {new Date(h.created_at).toLocaleString("tr-TR")}
       </option>)}
      </select>
     </label>
     <label>Yeni taslak
      <select value={target} onChange={e=>{setTarget(e.target.value);setCompare(null);setPage(1);}}>
       <option value="">Taslak seçin</option>
       {history.map(h=><option key={h.id} value={h.id}>
        {h.title} · {new Date(h.created_at).toLocaleString("tr-TR")}
       </option>)}
      </select>
     </label>
    </div>
    <div className="flex between"><span className="hint">
     {history.length<2?"Karşılaştırma için en az iki taslak gerekir.":"Miktar, fiyat ve toplam tutar farkları ayrı hesaplanır."}
    </span>
    <button type="button" disabled={!token||busy||!baseline||!target||baseline===target}
     onClick={()=>fetchComparison(1)}>{busy?"Hesaplanıyor...":"Taslakları karşılaştır"}</button></div>
    {compare&&<div className="stack">
     <div className="m51-summary">
      <div className="m51-stat"><small>Önceki toplam</small><strong>{money(compare.baseline_total)}</strong></div>
      <div className="m51-stat"><small>Yeni toplam</small><strong>{money(compare.target_total)}</strong></div>
      <div className="m51-stat"><small>Toplam fark</small><strong>{diff(compare.difference)}</strong></div>
     </div>
     <div className="m51-summary">
      <div className="m51-stat"><small>Miktar etkisi</small><strong>{diff(compare.breakdown.quantity_effect)}</strong></div>
      <div className="m51-stat"><small>Fiyat etkisi</small><strong>{diff(compare.breakdown.price_effect)}</strong></div>
      <div className="m51-stat"><small>Eklenen / çıkarılan / kapsam</small><strong>{diff(compare.breakdown.unattributed_effect)}</strong></div>
     </div>
     <p className="hint" role="status">
       Revizyonlar arası doğrulanmış poz ilişkisi: <strong>{compare.verified_cross_import_pairs}</strong>.
       {compare.ambiguous_identity_groups>0&&<>
        {" "}Belirsiz kimlik grubu: <strong>{compare.ambiguous_identity_groups}</strong>.
        Bu kalemlerde otomatik miktar/fiyat ayrıştırması yapılmadı; uzman incelemesi gerekir.
       </>}
     </p>
     <p className="hint">Yuvarlama düzeltmesi: {money(compare.breakdown.rounding_adjustment)}.
      Miktar etkisi eski fiyatla, fiyat etkisi yeni miktarla hesaplanır.</p>
     <div className="table-scroll"><table className="m51-table">
      <thead><tr><th>Satır</th><th>İmalat / Poz</th><th>Durum ve ilişki</th><th>Önceki</th><th>Yeni</th><th>Fark</th></tr></thead>
      <tbody>{compare.rows.map(row=><tr key={row.work_item_id}>
       <td>{row.source_row}</td>
       <td><strong>{row.description}</strong><div className="hint">
        {row.baseline_position??"—"} → {row.target_position??"—"}</div></td>
       <td>{labels[row.status]??row.status}
        <div className="hint">{linkLabels[row.matching_basis]??row.matching_basis}</div></td>
       <td>{money(row.baseline_amount)}<div className="hint">
        {row.baseline_quantity??"—"} × {row.baseline_unit_price??"—"}</div>
        <div className="hint">{row.baseline_price_source??""}</div></td>
       <td>{money(row.target_amount)}<div className="hint">
        {row.target_quantity??"—"} × {row.target_unit_price??"—"}</div>
        <div className="hint">{row.target_price_source??""}</div></td>
       <td><strong>{diff(row.difference)}</strong></td>
      </tr>)}</tbody></table></div>
     {compare.total_rows>20&&<div className="flex between">
      <button type="button" className="secondary" disabled={busy||page<=1}
       onClick={()=>fetchComparison(page-1)}>Önceki</button>
      <span className="hint">Sayfa {page}/{Math.ceil(compare.total_rows/20)}</span>
      <button type="button" className="secondary" disabled={busy||page>=Math.ceil(compare.total_rows/20)}
       onClick={()=>fetchComparison(page+1)}>Sonraki</button>
     </div>}
     <p className="hint">Değişim sınıfları: {Object.entries(compare.counts)
       .map(([key,n])=>(labels[key]??key)+": "+n).join(" · ")}</p>
    </div>}
   </div>
   <div className="m51-divider stack">
    <h3 className="m51-subtitle">Miktar / fiyat değişimi simülasyonu</h3>
    <p className="hint">İlgili taslağı ve pozunu seç; mevcut miktar veya fiyatı değiştir.
     Bu işlem revizyon kaydı oluşturmaz.</p>
    <label>Simülasyonun kaynak taslağı
     <select value={scenarioId} onChange={e=>{setScenarioId(e.target.value);setSimulation(null);}}>
      <option value="">Taslak seçin</option>
      {history.map(h=><option key={h.id} value={h.id}>
       {h.title} · {new Date(h.created_at).toLocaleString("tr-TR")}
      </option>)}
     </select>
    </label>
    {snapshot&&<>
     <label>İmalat / Poz
      <select value={candidateId} onChange={e=>selectCandidate(e.target.value)}>
       {snapshot.lines.map(line=><option key={line.candidate_id} value={line.candidate_id}>
        #{line.source_row} · {line.position_code} · {line.description}
       </option>)}
      </select>
     </label>
     <div className="m51-fields">
      <label>Simüle edilen miktar (aynı birim)
       <input inputMode="decimal" value={quantity} onChange={e=>{setQuantity(e.target.value);setSimulation(null);}}
        placeholder="Örn. 13.0000"/></label>
      <label>Simüle edilen birim fiyat (TRY)
       <input inputMode="decimal" value={unitPrice} onChange={e=>{setUnitPrice(e.target.value);setSimulation(null);}}
        placeholder="Örn. 1400.00"/></label>
     </div>
     <div className="flex between"><span className="hint">
       Simülasyon yeni taslak veya mühendis onayı üretmez.</span>
      <button type="button" disabled={!canSimulate} onClick={simulate}>
       Simülasyonu hesapla</button></div>
    </>}
    {simulation&&<div className="stack">
      <div className="m51-summary">
       <div className="m51-stat"><small>Eski kayıt toplamı</small><strong>{money(simulation.baseline_total)}</strong></div>
       <div className="m51-stat"><small>Simüle edilen toplam</small><strong>{money(simulation.simulated_total)}</strong></div>
       <div className="m51-stat"><small>Fark (kaydedilmedi)</small><strong>{diff(simulation.difference)}</strong></div>
      </div>
      {simulation.rows.map(row=><p key={row.position_code+row.source_row} className="m51-note">
       {row.position_code}: miktar etkisi {diff(row.quantity_effect)};
       fiyat etkisi {diff(row.price_effect)};
       yuvarlama farkı {money(row.rounding_adjustment)}. <strong>Yalnızca simülasyon.</strong>
      </p>)}
     </div>}
   </div>
  </div>
 </details>;
}
