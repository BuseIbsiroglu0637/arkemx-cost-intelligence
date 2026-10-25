"use client";
import {useEffect,useState} from "react";

type ComparisonField={key:string;label:string;metraj:string|number|number[]|null;
 catalog:string|number|number[]|null;status:"match"|"block"|"review"|"not_specified";reason:string};
type Technical={version:string;status:"compatible"|"blocked"|"review";
 manual_approval_allowed:boolean;blockers:string[];review_flags:string[];
 fields:ComparisonField[];metraj_excerpt:string;catalog_excerpt:string;lexical_similarity:number;
 score_is_probability:boolean};
type Candidate={id:string;code:string;description:string;unit:string;similarity:number;technical?:Technical};
type Item={id:string;source_row:number;description:string;stale:boolean;candidates:Candidate[]};
type Result={run:null|{id:string;algorithm:string;source:string;catalog_period:string;rights_active:boolean;
 candidate_count:number};items:Item[];message?:string};
type Quality={fixture:string;sample_size:number;precision:number;recall:number;
 false_positive:number;not_production_validation:boolean};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";
async function call<T>(url:string,token:string,method:"GET"|"POST"="GET"):Promise<T>{
 const response=await fetch(BASE+url,{method,headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
 if(!response.ok){const info=await response.json().catch(()=>({detail:`HTTP ${response.status}`}));
  throw new Error(typeof info.detail==="string"?info.detail:`HTTP ${response.status}`);}
 return response.json() as Promise<T>;
}
const value=(x:ComparisonField["metraj"])=>
 x===null||x===undefined?"Belirtilmemiş":Array.isArray(x)?x.join(" × "):String(x);
const statusLabel:{[key:string]:string}={
 blocked:"Onay engelli",review:"Uzman incelemesi gerekli",compatible:"Teknik kurallarda uyumlu",
 match:"Uyumlu",block:"Uyuşmazlık",not_specified:"Belirtilmemiş",
};
export default function TechnicalPanel({token,project,refreshKey,onMatch}:{
 token:string|null;project:string;refreshKey:number;onMatch:()=>void
}){
 const [result,setResult]=useState<Result|null>(null);
 const [quality,setQuality]=useState<Quality|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [message,setMessage]=useState("");
 useEffect(()=>{
  if(!token||!project){setResult(null);return;}
  let active=true;
  setError("");setMessage("");setResult(null);
  call<Result>(`/api/projects/${project}/m4/latest`,token).then(v=>{if(active)setResult(v);})
   .catch(e=>{if(active)setError(e instanceof Error?e.message:String(e));});
  call<Quality>("/api/m4/quality",token).then(v=>{if(active)setQuality(v);}).catch(()=>{});
  return()=>{active=false;};
 },[token,project,refreshKey]);
 async function run(){
  if(!token)return;
  setBusy(true);setError("");setMessage("");
  try{
   const created=await call<{row_count:number;candidate_count:number}>(`/api/projects/${project}/m4/run`,token,"POST");
   setResult(await call<Result>(`/api/projects/${project}/m4/latest`,token));
   setMessage(`${created.row_count} metraj kalemi incelendi, ${created.candidate_count} teknik karşılaştırma kaydedildi. Önceki mühendis onayları geçmişte kaldı.`);
   onMatch();
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 return <section className="card stack" aria-label="M4 teknik poz karşılaştırma">
  <div className="flex between">
   <div><h2>M4 · Akıllı teknik poz karşılaştırma</h2>
    <p className="hint">Malzeme, kalınlık, ebat, yüzey, yöntem ve birim özelliklerini ayrı ayrı denetler.</p></div>
   <span className="tag">Kural tabanlı v0.1</span>
  </div>
  <p className="notice">Metin benzerliği teknik uygunluk değildir. Kritik uyumsuzluklar onayı engeller; eksik bilgiler uzman incelemesi gerektirir.
   Bu kontrol, resmî teknik şartname değerlendirmesi yerine geçmez.</p>
  {error&&<div role="alert" className="error">{error}</div>}
  {message&&<div role="status" className="success">{message}</div>}
  <div className="flex between">
   <p className="hint">Son M2/M3 çalışmasının katalog sürümü kullanılır. 500 poz ve 100 metraj satırı sınırı vardır.</p>
   <button disabled={busy||!token} onClick={run}>{busy?"Karşılaştırılıyor...":"Teknik karşılaştırmayı çalıştır"}</button>
  </div>
  {quality&&<div className="flex">
   <div className="kpi"><b>{quality.sample_size}</b><span>Sentetik test çifti</span></div>
   <div className="kpi"><b>{(quality.precision*100).toFixed(0)}%</b><span>Sentetik kabul kesinliği</span></div>
   <div className="kpi"><b>{quality.false_positive}</b><span>Sentetik yanlış onay</span></div>
   <p className="hint">Bu değerler saha doğruluğu veya kalibre edilmiş güven oranı değildir.</p>
  </div>}
  {!result?.run&&<div className="empty">Henüz M4 çalıştırması yok. Önce M2 veya M3 ile bir poz katalog eşleştirmesi oluşturun.</div>}
  {result?.run&&<><div className="flex">
   <span className="tag">{result.run.source} · {result.run.catalog_period}</span>
   <span className="tag">{result.run.candidate_count} karşılaştırma adayı</span>
  </div>
  {!result.run.rights_active&&<p className="warning">Katalog izni etkin değil: yeni mühendis onayı engellidir.</p>}
  {result.items.map(item=><article className="match-row" key={item.id}>
   <strong>#{item.source_row} · {item.description}</strong>
   {item.stale&&<p className="warning">Metraj veya katalog değişti; yeniden eşleştirme gerekiyor.</p>}
   {item.candidates.length===0&&<p className="hint">Uygun sözcük benzerliğine sahip katalog poz adayı bulunamadı.</p>}
   {item.candidates.map(candidate=><div key={candidate.id} className="match-candidate">
    <div className="flex between"><strong>{candidate.code} · {candidate.description}</strong>
     <span className="tag">Metin: {candidate.similarity.toFixed(2)}</span></div>
    {!candidate.technical?<p className="warning">Teknik kanıt yok: otomatik karar verilmez.</p>:
     <>
      <strong>{statusLabel[candidate.technical.status]}</strong>
      {!!candidate.technical.blockers.length&&<p className="warning">Engeller: {candidate.technical.blockers.join(", ")}</p>}
      {!!candidate.technical.review_flags.length&&<p className="warning">İnceleme: {candidate.technical.review_flags.join(", ")}</p>}
      <div className="table-scroll"><table><thead><tr>
       <th>Teknik özellik</th><th>Metraj</th><th>Poz</th><th>Değerlendirme</th></tr></thead>
       <tbody>{candidate.technical.fields.map(field=><tr key={field.key}>
        <td>{field.label}</td><td>{value(field.metraj)}</td><td>{value(field.catalog)}</td>
        <td>{statusLabel[field.status]}</td></tr>)}</tbody>
      </table></div>
      <p className="hint">Özellikler yalnızca metraj açıklaması ve katalog tarifinden çıkarılmıştır. Mühendis onayı için M2 sonuç kartını kullan.</p>
     </>}
   </div>)}
  </article>)}
  </>}
 </section>;
}
