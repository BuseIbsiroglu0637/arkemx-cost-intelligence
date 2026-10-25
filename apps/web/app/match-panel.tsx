"use client";
import {useEffect, useState} from "react";

type Candidate = {
  id: string; position_id: string; code: string; description: string; unit: string;
  similarity: number; reasons: string[]; warnings: string[]; approvable: boolean; rank: number
};
type MatchedItem = {
  id: string; source_row: number; description: string; quantity: string|null; unit: string|null;
  review_required: boolean; stale?: boolean; candidates: Candidate[];
  decision: {action:string;candidate_id:string;reason?:string|null}|null
};
type Latest = {run: null|{
  id:string; row_count:number; candidate_count:number; algorithm:string;
  catalog_period:string; source:string; synthetic:boolean; scores_are_probabilities:boolean;
  parent_run_id?:string|null;changed_item_count?:number;outdated_import?:boolean;
  rights_active?:boolean;catalog_year?:number;catalog_sha256?:string
}; items: MatchedItem[]};

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
async function call<T>(url: string, token: string, method: "GET"|"POST"="GET", body?:object):Promise<T>{
  const response = await fetch(BASE+url,{method,headers:{"Authorization":`Bearer ${token}`,...(body?{"Content-Type":"application/json"}:{})},
    body:body?JSON.stringify(body):undefined,cache:"no-store"});
  if(!response.ok){
    const data = await response.json().catch(()=>({detail:`HTTP ${response.status}`}));
    throw new Error(typeof data.detail==="string"?data.detail:`HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export default function MatchPanel({token,project,refreshKey}:{token:string|null;project:string;refreshKey:number}){
  const [result,setResult]=useState<Latest|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [localAI,setLocalAI]=useState(false);

  useEffect(()=>{
    if(!token||!project){setResult(null);return;}
    let alive=true;
    setResult(null);setMessage("");setError("");
    call<Latest>(`/api/projects/${project}/m2/latest`,token)
      .then(data=>{if(alive)setResult(data);}).catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e));});
    return()=>{alive=false;};
  },[token,project,refreshKey]);

  async function start(){
    if(!token)return;
    setBusy(true);setError("");setMessage("");
    try {
      await call("/api/m2/demo-catalog",token,"POST");
      const response=await call<{row_count:number;candidate_count:number}>(`/api/projects/${project}/m2/run`,token,"POST",
        {use_local_ollama:localAI});
      setResult(await call<Latest>(`/api/projects/${project}/m2/latest`,token));
      setMessage(`${response.row_count} satır tarandı, ${response.candidate_count} aday üretildi. Kararlar yalnızca mühendis onayıyla verilir.`);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function decide(candidate:Candidate,action:"approve"|"reject"){
    if(!token||!result?.run)return;
    if(action==="approve"&&!candidate.approvable)return;
    setBusy(true);setError("");setMessage("");
    try{
      await call(`/api/projects/${project}/m2/decisions`,token,"POST",
        {run_id:result.run.id,candidate_id:candidate.id,action,reason:action==="reject"?"İnceleme sonrası reddedildi":null});
      setResult(await call<Latest>(`/api/projects/${project}/m2/latest`,token));
      setMessage(action==="approve"?"Mühendis seçimi kaydedildi.":"Ret kararı kaydedildi.");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }

  return <section className="card stack" aria-label="M2 poz eşleştirme">
    <div className="flex between"><div><h2>M2 · AI Poz Eşleştirme</h2><p className="hint">Metin benzerliği + zorunlu malzeme, ebat ve birim denetimi.</p></div><span className="tag">{result?.run&&!result.run.synthetic?"HAK ONAYLI KATALOG":"SENTETİK DEMO"}</span></div>
    <p className="notice">M2 düğmesi sentetik DEMO- kodlarını kullanır. M3 düğmesi yalnızca kullanım hakları kayda alınmış katalogları kullanır.
      Her iki durumda da benzerlik puanı doğruluk olasılığı değildir; mühendis kontrolü zorunludur.</p>
    <div className="flex between">
      <label className="match-check"><input type="checkbox" checked={localAI} onChange={e=>setLocalAI(e.target.checked)}/>
        Yerel Ollama varsa ek yeniden sıralama yap (isteğe bağlı)</label>
      <button disabled={busy||!token} onClick={start}>{busy?"İşleniyor...":"Sentetik katalogla poz önerilerini oluştur"}</button>
    </div>
    {error&&<div className="error" role="alert">{error}</div>}
    {message&&<div className="success" role="status">{message}</div>}
    {result?.run&&<div className="flex">
      <div className="kpi"><b>{result.run.row_count}</b><span>İncelenen kalem</span></div>
      <div className="kpi"><b>{result.run.candidate_count}</b><span>Poz adayı</span></div>
      <div className="kpi"><b>{result.items.filter(item=>!item.stale&&item.decision?.action==="approve").length}</b><span>Mühendis onaylı</span></div>
      <p className="hint">Katalog: {result.run.source} / {result.run.catalog_year} / {result.run.catalog_period} · Motor: {result.run.algorithm}</p>
      {result.run.rights_active===false&&<p className="warning">Kaynak kullanım izni geri çekilmiş; yeni onay kapalı.</p>}
      {result.run.parent_run_id&&<p className="hint">Yeni eşleştirmede {result.run.changed_item_count} kalem yeniden hesaplandı. Önceki onaylar otomatik taşınmadı.</p>}
    </div>}
    {result?.run&&result.items.map(item=><article key={item.id} className="match-row">
      <div className="flex between"><strong>#{item.source_row} · {item.description}</strong>
        {item.review_required&&<span className="warning">Metraj kontrolü gerekli</span>}
        {item.stale&&<span className="warning">Eski hesaplama: yeniden eşleştir</span>}</div>
      <p className="hint">Miktar: {item.quantity??"belirsiz"} · Birim: {item.unit??"belirsiz"}</p>
      {item.candidates.length===0&&<p className="warning">Uygun katalog adayı bulunamadı. Poz uydurulmadı.</p>}
      {item.candidates.map(candidate=><div className="match-candidate" key={candidate.id}>
        <div className="flex between"><div><strong>{candidate.code}</strong> · {candidate.description}</div>
          <span className="tag">Metin benzerliği: {candidate.similarity.toFixed(2)}</span></div>
        <p className="hint">{candidate.unit} · {candidate.reasons.join(" · ")}</p>
        {!!candidate.warnings.length&&<p className="warning">Kontrol: {candidate.warnings.join(", ")}</p>}
        <div className="flex">
          <button disabled={busy||!candidate.approvable||!!item.stale||result?.run?.rights_active===false} onClick={()=>decide(candidate,"approve")}>Mühendis onayı</button>
          <button disabled={busy} className="secondary" onClick={()=>decide(candidate,"reject")}>Reddet</button>
          {item.decision?.candidate_id===candidate.id&&<span className="tag">
            {item.stale?"Tarihî karar (güncel değil): ":"Son karar: "}{item.decision.action==="approve"?"Onaylandı":"Reddedildi"}</span>}
        </div>
      </div>)}
    </article>)}
    {result?.run===null&&<div className="empty">Önce bir Excel metrajını kaydedin, sonra sentetik katalogla ilk eşleştirme testini başlatın.</div>}
  </section>;
}