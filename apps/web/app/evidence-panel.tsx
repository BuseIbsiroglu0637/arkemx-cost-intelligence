"use client";
import {useEffect,useState} from "react";

type Quote={excerpt:string;start:number;end:number;offset_basis:string}|null;
type Check={key:string;metraj:{value:string|null;quote:Quote};catalog:{value:string|null;quote:Quote};
 status:"match"|"block"|"review"|"not_specified";code:string|null};
type Evidence={schema:string;version:string;status:"compatible"|"blocked"|"review";
 approval_allowed:boolean;blockers:string[];review_flags:string[];checks:Check[];
 evidence_sha256:string;source_refs:{metraj?:{source_row:number;import_sha256:string;revision_id:string|null};
 catalog?:{position_code:string;version_sha256:string}};
 sources:{metraj:{normalized_text:string;sha256:string};catalog:{normalized_text:string;sha256:string}};
 statement:string};
type Candidate={id:string;code:string;description:string;similarity:number;approvable:boolean;evidence:Evidence|null};
type Item={id:string;source_row:number;description:string;stale:boolean;candidates:Candidate[]};
type Result={run:null|{id:string;algorithm:string;source:string;catalog_period:string;rights_active:boolean};
 items:Item[];message?:string};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";
async function query<T>(path:string,token:string,method:"GET"|"POST"="GET"):Promise<T>{
 const res=await fetch(BASE+path,{method,headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
 if(!res.ok){const err=await res.json().catch(()=>({detail:`HTTP ${res.status}`}));
  throw new Error(typeof err.detail==="string"?err.detail:`HTTP ${res.status}`);}
 return res.json() as Promise<T>;
}
const labels:Record<string,string>={
 compatible:"Sınırlı kurallarda uyumlu",blocked:"Onay engelli",review:"Mühendis incelemesi gerekli",
 match:"Eşleşti",block:"Çelişki",not_specified:"Belirtilmedi",
};
const rendered=(value:string|null|undefined)=>value??"Kaynakta belirtilmedi";
const sourceLabel=(c:Check["metraj"])=>c.quote?`“${c.quote.excerpt}” (${c.quote.start}–${c.quote.end})`:"Kaynak ifadesi yok";
export default function EvidencePanel({token,project,refreshKey,onMatch}:{
 token:string|null;project:string;refreshKey:number;onMatch:()=>void
}){
 const [data,setData]=useState<Result|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [message,setMessage]=useState("");
 useEffect(()=>{
  if(!token||!project){setData(null);return;}
  let active=true;
  setData(null);setError("");setMessage("");
  query<Result>(`/api/projects/${project}/m41/latest`,token)
   .then(v=>{if(active)setData(v);})
   .catch(e=>{if(active)setError(e instanceof Error?e.message:String(e));});
  return()=>{active=false;};
 },[token,project,refreshKey]);
 async function run(){
  if(!token)return;
  setBusy(true);setError("");setMessage("");
  try{
   const r=await query<{row_count:number;candidate_count:number}>(`/api/projects/${project}/m41/run`,token,"POST");
   setData(await query<Result>(`/api/projects/${project}/m41/latest`,token));
   setMessage(`${r.row_count} metraj satırında ${r.candidate_count} kaynaklı teknik kanıt saklandı. Önceki koşular korunur.`);
   onMatch();
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 return <section className="card stack" aria-label="M4.1 teknik kanıt modeli">
  <div className="flex between"><div>
   <h2>M4.1 · Teknik kapsam ve kaynaklı kanıt</h2>
   <p className="hint">Beton sınıfı, TS EN standardı ve dahil/hariç kapsam ifadelerinin kaynak izi</p>
  </div><span className="tag">Kanıt şeması v1</span></div>
  <p className="notice">Bu sürüm yalnızca metraj ve poz tariflerinde açıkça yazılı ifadeleri karşılaştırır.
   Tam poz şartnamesi veya alt analizler henüz işlenmiyor. Bilgi yoksa sistem tahmin ederek onay vermez.</p>
  {error&&<p className="error" role="alert">{error}</p>}
  {message&&<p className="success" role="status">{message}</p>}
  <div className="flex between"><p className="hint">Son M2/M3/M4 çalışmasının kaynak sürümüyle yeni ve bağımsız bir M4.1 çalışması oluşturulur.</p>
   <button disabled={!token||busy} onClick={run}>{busy?"İşleniyor...":"Kaynaklı teknik kanıt oluştur"}</button></div>
  {!data?.run&&<div className="empty">Henüz M4.1 kanıt çalışması yok. Önce güncel katalogla bir eşleştirme yapın.</div>}
  {data?.run&&<div className="flex"><span className="tag">{data.run.source} · {data.run.catalog_period}</span>
   <span className="tag">Sürüm: {data.run.algorithm}</span></div>}
  {data?.run&&!data.run.rights_active&&<p className="warning">Katalog kullanım hakkı aktif değil. Yeni onay engellidir.</p>}
  {data?.items.map(item=><article key={item.id} className="match-row">
   <strong>#{item.source_row} · {item.description}</strong>
   {item.stale&&<p className="warning">Metraj değişmiş; rapor güncel değil.</p>}
   {item.candidates.map(c=><div key={c.id} className="match-candidate">
    <strong>{c.code} · {c.description}</strong>
    {!c.evidence?<p className="warning">Kanıt eksik: onay engelli.</p>:
     <>
      <p><strong>{labels[c.evidence.status]}</strong></p>
      {!!c.evidence.blockers.length&&<p className="warning">Engel: {c.evidence.blockers.join(", ")}</p>}
      {!!c.evidence.review_flags.length&&<p className="warning">İnceleme: {c.evidence.review_flags.join(", ")}</p>}
      <div className="table-scroll"><table><thead><tr><th>İddia</th><th>Metraj değeri / alıntı</th>
       <th>Katalog değeri / alıntı</th><th>Karar</th></tr></thead><tbody>
       {c.evidence.checks.map(check=><tr key={check.key}>
        <td>{check.key}</td>
        <td>{rendered(check.metraj.value)}<p className="hint">{sourceLabel(check.metraj)}</p></td>
        <td>{rendered(check.catalog.value)}<p className="hint">{sourceLabel(check.catalog)}</p></td>
        <td>{labels[check.status]}</td>
       </tr>)}</tbody></table></div>
      <p className="hint">Kaynak satırı: {c.evidence.source_refs.metraj?.source_row??"—"} · Poz: {c.evidence.source_refs.catalog?.position_code??"—"}</p>
      <p className="hint">Kanıt SHA-256: <code>{c.evidence.evidence_sha256}</code></p>
      <p className="hint">Alıntı konumları normalleştirilmiş tarife aittir; özgün Excel hücre koordinatı değildir.</p>
     </>}
   </div>)}
  </article>)}
 </section>;
}
