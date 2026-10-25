"use client";
import {useEffect,useRef,useState} from "react";

type Catalog={version_id:string;institution:string;period:string;year:number;positions:number};
type Job={id:string;status:"queued"|"running"|"completed"|"failed"|"blocked";
 run_id:string;total_rows:number;processed_rows:number;candidate_count:number;
 percent:number;failure_reason:string|null;published:boolean;requires_local_worker:boolean;
 version_id:string};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";
async function call<T>(url:string,token:string,method:"GET"|"POST"="GET",body?:object):Promise<T>{
 const r=await fetch(BASE+url,{method,headers:{Authorization:`Bearer ${token}`,
  ...(body?{"Content-Type":"application/json"}:{})},
  body:body?JSON.stringify(body):undefined,cache:"no-store"});
 if(!r.ok){const info=await r.json().catch(()=>({detail:`HTTP ${r.status}`}));
  throw new Error(typeof info.detail==="string"?info.detail:`HTTP ${r.status}`);}
 return r.json() as Promise<T>;
}
const label:Record<string,string>={
 queued:"İşlem sırasında bekliyor",running:"İşleniyor",completed:"Tamamlandı",
 failed:"Hata — yeniden denenebilir",blocked:"Kaynak/metraj değişti — yeni iş oluştur"};
export default function BulkPanel({token,project,onCompleted}:{
 token:string|null;project:string;onCompleted:()=>void;
}){
 const [catalogs,setCatalogs]=useState<Catalog[]>([]);
 const [version,setVersion]=useState("");
 const [job,setJob]=useState<Job|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [message,setMessage]=useState("");
 const announced=useRef<string|null>(null);
 useEffect(()=>{
  if(!token||!project){setCatalogs([]);setJob(null);return;}
  let alive=true;
  announced.current=null;setError("");setMessage("");setVersion("");setJob(null);
  call<Catalog[]>(`/api/projects/${project}/m43/catalogs`,token).then(c=>{
   if(alive){setCatalogs(c);setVersion(c[0]?.version_id??"");}
  }).catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e));});
  call<Job[]>(`/api/projects/${project}/m43/jobs`,token).then(j=>{
   if(alive)setJob(j[0]??null);
  }).catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e));});
  return()=>{alive=false;};
 },[token,project]);
 useEffect(()=>{
  if(!token||!project||!job||!(job.status==="queued"||job.status==="running"))return;
  let active=true;
  const timer=setInterval(()=>{
   call<Job>(`/api/projects/${project}/m43/jobs/${job.id}`,token)
    .then(next=>{
      if(!active)return;
      setJob(next);
      if(next.status==="completed"&&announced.current!==next.id){
       announced.current=next.id;
       onCompleted();
      }
    }).catch(e=>{if(active)setError(e instanceof Error?e.message:String(e));});
  },2000);
  return()=>{active=false;clearInterval(timer);};
 },[job?.id,job?.status,token,project,onCompleted]);
 async function enqueue(){
  if(!token||!project||!version)return;
  setBusy(true);setError("");setMessage("");
  try{
   const key=crypto.randomUUID();
   const next=await call<Job>(`/api/projects/${project}/m43/jobs`,token,"POST",{
    version_id:version,idempotency_key:key});
   setJob(next);setMessage("İş kalıcı kuyruğa eklendi. Ayrı PowerShell penceresinde yerel işçiyi başlatın.");
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 async function retry(){
  if(!token||!project||!job)return;
  setBusy(true);setError("");setMessage("");
  try{setJob(await call<Job>(`/api/projects/${project}/m43/jobs/${job.id}/retry`,token,"POST"));
   setMessage("Kalan satırlar için yeniden deneme kuyruğa alındı.");}
  catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 const active=job?.status==="queued"||job?.status==="running";
 return <section className="card stack" aria-label="M4.3 toplu metraj işleme">
  <div className="flex between"><div>
   <h2>M4.3 · Toplu metraj ve teknik karşılaştırma</h2>
   <p className="hint">500 satıra kadar metraj · kayıtlı ilerleme · kesintiden sonra kaldığı yerden devam</p>
  </div><span className="tag">Ücretsiz yerel işçi</span></div>
  <p className="notice">Aynı projede tek toplu iş çalışır. API isteği yalnız kuyruğa ekler.
   Hesaplama ayrı yerel Python işçisi açıkken yapılır. Eksik veya iptal edilmiş katalog izniyle işlem başlatılmaz.</p>
  {error&&<p role="alert" className="error">{error}</p>}
  {message&&<p role="status" className="success">{message}</p>}
  <div className="review-top">
   <label style={{flex:1}}>Onaylı poz kataloğu
    <select value={version} onChange={e=>setVersion(e.target.value)}>
     {catalogs.length===0?<option value="">Onaylı katalog bulunamadı</option>:
      catalogs.map(c=><option value={c.version_id} key={c.version_id}>
       {c.institution} · {c.year}/{c.period} · {c.positions} poz</option>)}
    </select>
   </label>
   <button type="button" onClick={enqueue} disabled={busy||!token||!version||!!active}>
    {busy?"İşleniyor...":"500 satıra kadar toplu iş başlat"}</button>
  </div>
  {job&&<div className="bulk-progress">
   <div className="flex between"><strong>{label[job.status]??job.status}</strong>
    <span>{job.processed_rows} / {job.total_rows} satır · {job.percent}%</span></div>
   <progress max={job.total_rows||1} value={job.processed_rows} aria-label="İşlenen satır ilerlemesi"/>
   <p className="hint">Kaydedilen poz adayı: {job.candidate_count}. Tamamlanmadan mühendis onayına açılmaz.</p>
   {job.failure_reason&&<p className="warning">Neden: {job.failure_reason}</p>}
   {job.status==="failed"&&<button type="button" className="secondary" disabled={busy} onClick={retry}>
    Kaldığı yerden yeniden dene</button>}
   {job.status==="completed"&&<p className="success">Toplu iş tamamlandı. M4.2 inceleme listesindeki filtrelerle adayları kontrol edin.</p>}
   {active&&<div className="hint">
    Bu cihazda ikinci PowerShell penceresinde <code>.\.venv\Scripts\python.exe -m app.m43_worker --watch</code>
    komutu çalışmalıdır. Worker kapalıyken kuyruk bekler; yeniden açılınca devam eder.
   </div>}
  </div>}
  <p className="hint">Pilot sınırları: <strong>500 metraj satırı, 500 katalog pozu, satır başına en çok 3 aday</strong>.
   Performans sayıları gerçek cihazda ayrıca ölçülmelidir; otomatik onay verilmez.</p>
 </section>;
