"use client";
import {useEffect,useState} from "react";

type Job = {id:string;import_id:string;status:string;processed_rows:number;total_rows:number;
 lease_owner_active:boolean;cancelled_by_operator:boolean;cancel_reason:string|null};
type Source = {id:string;filename:string;sha256:string;created_at:string;
 row_count:number;is_latest:boolean;excluded:boolean;exclusion_reason:string|null};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";
async function safeCall<T>(path:string,token:string,data?:unknown):Promise<T>{
 const response=await fetch(BASE+path,{method:data?"POST":"GET",cache:"no-store",
  headers:{Authorization:"Bearer "+token,...(data?{"Content-Type":"application/json"}:{})},
  body:data?JSON.stringify(data):undefined});
 if(!response.ok){const error=await response.json().catch(()=>({detail:"HTTP "+response.status}));
  throw new Error(typeof error.detail==="string"?error.detail:"HTTP "+response.status);}
 return response.json() as Promise<T>;
}
export default function SafetyControls({token,project,onChanged}:{
 token:string|null;project:string;onChanged:()=>Promise<void>|void
}){
 const [jobs,setJobs]=useState<Job[]>([]);
 const [sources,setSources]=useState<Source[]>([]);
 const [selectedJob,setSelectedJob]=useState("");
 const [selectedSource,setSelectedSource]=useState("");
 const [jobReason,setJobReason]=useState("");
 const [sourceReason,setSourceReason]=useState("");
 const [jobConfirm,setJobConfirm]=useState(false);
 const [sourceConfirm,setSourceConfirm]=useState(false);
 const [busy,setBusy]=useState(false);
 const [message,setMessage]=useState("");
 const [error,setError]=useState("");
 const prefix="/api/projects/"+project+"/m521";
 async function refresh(){
  if(!token||!project)return;
  const [j,s]=await Promise.all([safeCall<Job[]>(prefix+"/jobs",token),
    safeCall<Source[]>(prefix+"/imports",token)]);
  setJobs(j);setSources(s);
 }
 useEffect(()=>{
  let mounted=true;setJobs([]);setSources([]);setSelectedJob("");setSelectedSource("");
  setMessage("");setError("");setJobConfirm(false);setSourceConfirm(false);
  if(!token||!project)return;
  Promise.all([safeCall<Job[]>(prefix+"/jobs",token),
   safeCall<Source[]>(prefix+"/imports",token)]).then(([j,s])=>{
    if(mounted){setJobs(j);setSources(s);}
   }).catch(e=>{if(mounted)setError(e instanceof Error?e.message:String(e));});
  return()=>{mounted=false;};
 },[token,project,prefix]);
 async function execute(kind:"cancel"|"exclude"){
  if(!token||busy)return;
  const id=kind==="cancel"?selectedJob:selectedSource;
  const reason=kind==="cancel"?jobReason.trim():sourceReason.trim();
  if(!id||reason.length<10)return;
  setBusy(true);setMessage("");setError("");
  try{
   const endpoint=kind==="cancel"?
    prefix+"/jobs/"+id+"/cancel":prefix+"/imports/"+id+"/exclude";
   await safeCall(endpoint,token,{reason});
   setMessage(kind==="cancel"?
    "Bekleyen iş iptal edildi. Çalıştırma kaydı ve kanıtları korundu.":
    "Excel kaynağı yeni M4.3 işlemine kapatıldı; geçmişten silinmedi.");
   setSelectedJob("");setSelectedSource("");setJobReason("");setSourceReason("");
   setJobConfirm(false);setSourceConfirm(false);
   await refresh();
   await onChanged();
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 const candidate=jobs.find(j=>j.id===selectedJob);
 const file=sources.find(s=>s.id===selectedSource);
 return <details className="m521-controls">
  <summary>M5.2.1 · İş kuyruğu ve kaynak güvenliği</summary>
  <div className="stack">
   <p className="hint">Bu kontroller eski metrajı, önceki mühendis kararlarını ve maliyet
    taslaklarını silmez. Çalışmaya başlamış bir M4.3 işi iptal edilmez.</p>
   {error&&<p role="alert" className="error">{error}</p>}
   {message&&<p role="status" className="success">{message}</p>}
   <button type="button" className="secondary" onClick={()=>refresh().catch(e=>setError(String(e)))}
    disabled={busy}>Durumları yenile</button>
   <div className="stack">
    <h3>Bekleyen M4.3 işlerini yönet</h3>
    <label>İptal edilecek iş
     <select value={selectedJob} onChange={e=>{setSelectedJob(e.target.value);setJobConfirm(false);}}>
      <option value="">İş seçin (yalnızca kuyrukta)</option>
      {jobs.map(j=><option key={j.id} value={j.id} disabled={j.status!=="queued"||j.lease_owner_active}>
       {j.id.slice(0,8)} · {j.status} · {j.processed_rows}/{j.total_rows}
      </option>)}
     </select></label>
    {candidate&&<p className="hint">İş: {candidate.id} — {candidate.status} — {candidate.processed_rows}/{candidate.total_rows}</p>}
    <label>İptal gerekçesi
     <input value={jobReason} maxLength={500} placeholder="Örn. yanlış Excel ile oluşturulan iş"
      onChange={e=>setJobReason(e.target.value)}/></label>
    <label className="m52-check"><input type="checkbox" checked={jobConfirm}
     onChange={e=>setJobConfirm(e.target.checked)}/>
     Bu işin sıradan çıkarılacağını ve eski verilerin korunacağını onaylıyorum.</label>
    <button type="button" className="secondary" disabled={busy||!jobConfirm||jobReason.trim().length<10||
     !candidate||candidate.status!=="queued"||candidate.lease_owner_active}
      onClick={()=>execute("cancel")}>Seçili kuyruk işini güvenli iptal et</button>
   </div>
   <div className="m52-apply stack">
    <h3>Hatalı Excel kaynağını kullanım dışı bırak</h3>
    <p className="warning">Bu pilot sürümde kullanım dışı bırakma geri alınamaz.
     Kaynak geçmişte kalır. Son Excel'i kapatırsan yeni teknik analiz için daha yeni, temiz bir Excel yüklemelisin.
     Yanlışlıkla işlem yapmamak için kaynak dosyasını ve SHA-256 izini kontrol et.</p>
    <label>Kaynak Excel seç
     <select value={selectedSource} onChange={e=>{setSelectedSource(e.target.value);setSourceConfirm(false);}}>
      <option value="">Kaynak seçin</option>
      {sources.map(s=><option key={s.id} value={s.id} disabled={s.excluded}>
       {s.filename} · {s.id.slice(0,8)}{s.is_latest?" · Son kayıt":""}{s.excluded?" · Kullanım dışı":""}
      </option>)}
     </select></label>
    {file&&<div className="m521-source"><p className="hint">Kaynak: {file.filename}
     {file.is_latest?" — SON KAYIT":""}</p><p className="hint">SHA-256: <code>{file.sha256}</code></p></div>}
    <label>Kaynağı kullanım dışı bırakma gerekçesi
     <input value={sourceReason} maxLength={500}
      onChange={e=>setSourceReason(e.target.value)}
      placeholder="Örn. birim tanınmadı, Türkçe karakterler bozuk"/></label>
    <label className="m52-check"><input type="checkbox" checked={sourceConfirm}
      onChange={e=>setSourceConfirm(e.target.checked)}/>
      Bu kaynakla yeni M4.3 analizi başlatılmasını engellemek istiyorum.</label>
    <button type="button" className="secondary" disabled={busy||!file||file.excluded||
      !sourceConfirm||sourceReason.trim().length<10} onClick={()=>execute("exclude")}>
      Kaynağı kullanım dışı bırak (silmeden)</button>
   </div>
  </div>
 </details>;
}
