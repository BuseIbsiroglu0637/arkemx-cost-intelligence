"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";

type Status="all"|"compatible"|"review"|"blocked"|"missing";
type Decision="all"|"approved"|"rejected"|"undecided";
type History={action:string;reason:string|null;at:string;reviewer:string;run_id:string;current_run:boolean};
type Quote={excerpt:string;start:number;end:number}|null;
type Check={key:string;status:string;code:string|null;
 metraj:{value:string|null;quote:Quote};catalog:{value:string|null;quote:Quote}};
type Evidence={status:string;checks:Check[];blockers:string[];review_flags:string[];
 evidence_sha256:string;source_refs:{metraj?:{source_row:number};catalog?:{position_code:string}}};
type Detail={candidate_id:string;code:string;position:string;metraj:string;rights_active:boolean;
 stale:boolean;can_approve:boolean;identity_issue:string|null;evidence:Evidence|null;history:History[];history_limited:boolean};
type Candidate={candidate_id:string;work_item_id:string;source_row:number;metraj:string;
 code:string;position:string;rank:number;similarity:number;status:Status|"missing";
 stale:boolean;can_approve:boolean;identity_issue:string|null;last_decision:null|{action:string;at:string;reason:string|null}};
type Queue={run:null|{id:string;catalog:string;year:number;period:string;
 rights_active:boolean;outdated_import:boolean;row_count:number;row_limit:number;catalog_position_limit:number;
 candidate_count:number};total:number;page:number;page_size:number;rows:Candidate[];
 summary:{statuses?:Record<string,number>;decisions?:Record<string,number>};message?:string};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";
async function api<T>(path:string,token:string,method:"GET"|"POST"="GET",body?:unknown):Promise<T>{
 const r=await fetch(BASE+path,{method,cache:"no-store",headers:{
  Authorization:`Bearer ${token}`,...(body?{"Content-Type":"application/json"}:{})},
  body:body?JSON.stringify(body):undefined});
 if(!r.ok){const error=await r.json().catch(()=>({detail:`HTTP ${r.status}`}));
  throw new Error(typeof error.detail==="string"?error.detail:`HTTP ${r.status}`);}
 return r.json() as Promise<T>;
}
const label:Record<string,string>={
 compatible:"Kurallara göre uyumlu",review:"Uzman incelemesi",blocked:"Onay engelli",
 missing:"Kanıt eksik",approve:"Onaylandı",reject:"Reddedildi",match:"Aynı",
 block:"Çelişki",not_specified:"Belirtilmemiş",
};
const badge=(status:string)=>`review-state review-${status}`;
const display=(value:string|null)=>value??"Belirtilmemiş";
const quote=(q:Quote)=>q?`“${q.excerpt}” (${q.start}–${q.end})`:"Kanıt gösterilmedi";
export default function EngineerReviewPanel({token,project,refreshKey,onGoToBulk}:{
 token:string|null;project:string;refreshKey:number;onGoToBulk:()=>void
}){
 const [status,setStatus]=useState<Status>("all");
 const [decision,setDecision]=useState<Decision>("all");
 const [draftSearch,setDraftSearch]=useState("");
 const [search,setSearch]=useState("");
 const [page,setPage]=useState(1);
 const [pageSize,setPageSize]=useState(20);
 const [revision,setRevision]=useState(0);
 const [queue,setQueue]=useState<Queue|null>(null);
 const [selected,setSelected]=useState<string|null>(null);
 const [detail,setDetail]=useState<Detail|null>(null);
 const [reason,setReason]=useState("");
 const [busy,setBusy]=useState(false);
 const [loadingDetail,setLoadingDetail]=useState(false);
 const [error,setError]=useState("");
 const [detailError,setDetailError]=useState("");
 const [message,setMessage]=useState("");

 const load=useCallback(async()=>{
  if(!token||!project){setQueue(null);return;}
  const params=new URLSearchParams({status,decision,q:search,page:String(page),page_size:String(pageSize)});
  return api<Queue>(`/api/projects/${project}/m42/queue?${params.toString()}`,token);
 },[token,project,status,decision,search,page,pageSize]);

 useEffect(()=>{
  let active=true;
  setQueue(null);setError("");
  load().then(result=>{if(active&&result)setQueue(result);})
   .catch(err=>{if(active)setError(err instanceof Error?err.message:String(err));});
  return()=>{active=false;};
 },[load,refreshKey,revision]);

 useEffect(()=>{setPage(1);setStatus("all");setDecision("all");setSearch("");setDraftSearch("");
  setSelected(null);setDetail(null);setReason("");},[project]);

 async function inspect(candidateId:string){
  if(selected===candidateId){setSelected(null);setDetail(null);return;}
  if(!token)return;
  setSelected(candidateId);setDetail(null);setDetailError("");setReason("");setLoadingDetail(true);
  try{setDetail(await api<Detail>(`/api/projects/${project}/m42/candidates/${candidateId}`,token));}
  catch(err){setDetailError(err instanceof Error?err.message:String(err));}
  finally{setLoadingDetail(false);}
 }
 async function decide(action:"approve"|"reject"){
  if(!token||!queue?.run||!detail||busy||reason.trim().length<10)return;
  if(action==="approve"&&!detail.can_approve)return;
  setBusy(true);setError("");setMessage("");
  try{
   await api(`/api/projects/${project}/m2/decisions`,token,"POST",{
    run_id:queue.run.id,candidate_id:detail.candidate_id,action,reason:reason.trim()});
   const current=await api<Detail>(`/api/projects/${project}/m42/candidates/${detail.candidate_id}`,token);
   setDetail(current);setReason("");setRevision(v=>v+1);
   setMessage(action==="approve"?"Mühendis onayı kaydedildi.":"Ret kararı kaydedildi.");
  }catch(err){setError(err instanceof Error?err.message:String(err));}
  finally{setBusy(false);}
 }
 function submitSearch(event:FormEvent<HTMLFormElement>){
  event.preventDefault();setPage(1);setSearch(draftSearch.trim());setSelected(null);setDetail(null);
 }
 function filterStatus(s:Status){setPage(1);setStatus(s);setSelected(null);setDetail(null);}
 function filterDecision(s:Decision){setPage(1);setDecision(s);setSelected(null);setDetail(null);}
 const total=queue?.total??0;
 const lastPage=Math.max(1,Math.ceil(total/pageSize));
 const statuses=queue?.summary?.statuses??{};
 const approvals=queue?.summary?.decisions??{};
 return <section className="card review-panel" aria-label="M4.2 mühendis inceleme merkezi">
  <div className="flex between">
   <div><h2>M4.2 · Mühendis inceleme merkezi</h2>
    <p className="hint">Filtrelenebilir poz adayları · isteğe bağlı kanıt ayrıntısı · karar geçmişi</p></div>
   <span className="tag">Mühendis çalışma masası</span>
  </div>
  <div className="review-top">
   <p className="hint">M4.2 yalnızca tamamlanan teknik karşılaştırmaları incelemek içindir.
    Klasik M4.1 çalışmaları en fazla <strong>100 metraj satırı</strong>, M4.3 toplu çalışmaları en fazla
    <strong> 500 metraj satırı</strong> destekler. Katalog sınırı <strong>500 poz</strong>;
    adaylar sunucudan sayfa sayfa getirilir.
    {queue?.run&&<> Bu çalışmada <strong>{queue.run.row_count} satır</strong> incelendi
    (çalışma üst sınırı: {queue.run.row_limit}).</>}</p>
   <button type="button" className="secondary" onClick={onGoToBulk}>Yeni toplu analiz için M4.3 bölümüne git</button>
  </div>
  {error&&<p role="alert" className="error">{error}</p>}
  {message&&<p role="status" className="success">{message}</p>}
  {!queue&&<p className="hint" role="status">İnceleme listesi yükleniyor...</p>}
  {queue?.run&&<>
   <div className="flex">
    <span className="tag">Kurum: {queue.run.catalog}</span>
    <span className="tag">Dönem: {queue.run.year} / {queue.run.period}</span>
    <span className="tag">{queue.run.candidate_count} poz adayı</span>
   </div>
   {!queue.run.rights_active&&<p role="alert" className="warning">Katalog izni aktif değil; yeni mühendis onayı engelli.</p>}
   {queue.run.outdated_import&&<p role="alert" className="warning">Metraj değişmiş. Yeni çalıştırma yapılmadan onay verilemez.</p>}
   {queue.rows.some(c=>c.identity_issue)&&<p role="alert" className="warning">
    Bazı önerilerde poz kimliği uyuşmazlığı veya eski çalışmadan kalan kimlik kanıtı eksikliği bulunuyor.
    Bu satırlara onay verilemez. Eski çalışmanın teknik durum sayaçları tarihî kanıta aittir;
    güncel 100/200 durumunu görmek için M4.3'te yeniden analiz oluşturun.
   </p>}
   <div className="review-stats" aria-label="Tüm çalışmanın karar sayıları">
    {([
      ["all","Tüm adaylar",queue.run.candidate_count],
      ["review","İnceleme",statuses.review??0],
      ["blocked","Engelli",statuses.blocked??0],
      ["compatible","Uyumlu aday",statuses.compatible??0],
      ["missing","Kanıt eksik",statuses.missing??0],
     ] as const).map(([filter,title,count])=>
      <button type="button" key={filter}
       className={`review-stat ${status===filter?"active":""}`} onClick={()=>filterStatus(filter)}
       aria-pressed={status===filter}>
       <strong>{count}</strong><span>{title}</span>
      </button>)}
   </div>
   <p className="hint">Son kararlar: {approvals.approved??0} onay · {approvals.rejected??0} ret · {approvals.undecided??0} kararsız.
    Bu sayılar adayları gösterir, benzersiz metraj kalemi sayısını değil.</p>
   <form className="review-filters" onSubmit={submitSearch}>
    <label>Teknik durum<select value={status} onChange={e=>filterStatus(e.target.value as Status)}>
     <option value="all">Tüm durumlar</option><option value="review">Uzman incelemesi</option>
     <option value="blocked">Engelli</option><option value="compatible">Uyumlu aday</option>
     <option value="missing">Kanıt eksik</option></select></label>
    <label>Son mühendis kararı<select value={decision} onChange={e=>filterDecision(e.target.value as Decision)}>
     <option value="all">Tüm kararlar</option><option value="undecided">Karar verilmemiş</option>
     <option value="approved">Onaylanmış</option><option value="rejected">Reddedilmiş</option></select></label>
    <label>Ara<input value={draftSearch} maxLength={120} onChange={e=>setDraftSearch(e.target.value)}
      placeholder="Poz kodu veya imalat tarifi"/></label>
    <button type="submit" className="secondary">Filtrele</button>
   </form>
   <div className="table-scroll"><table className="review-table">
    <thead><tr><th>Satır</th><th>Metraj ve önerilen poz</th><th>Teknik durum</th><th>Son karar</th><th>İncele</th></tr></thead>
    <tbody>{queue.rows.map(c=><tr key={c.candidate_id}>
     <td className="number">{c.source_row}</td>
     <td><strong>{c.metraj}</strong><div className="hint">{c.code} · {c.position}</div></td>
     <td><span className={badge(c.identity_issue?"blocked":c.status)}>{c.identity_issue?"Kimlik onayı engelli":label[c.status]??c.status}</span>
      {c.stale&&<div className="warning">Güncel değil</div>}
      {c.identity_issue&&<div className="warning">Poz kimliği onaya kapalı: {c.identity_issue}</div>}</td>
     <td>{c.last_decision?label[c.last_decision.action]??c.last_decision.action:"Karar yok"}</td>
     <td><button type="button" className="secondary" aria-expanded={selected===c.candidate_id}
       aria-controls="engineer-detail" onClick={()=>inspect(c.candidate_id)}>
       {selected===c.candidate_id?"Kapat":"Kanıt ve karar"}</button></td>
    </tr>)}</tbody></table>
    {queue.rows.length===0&&<div className="empty">Bu filtrelerle eşleşen poz adayı bulunamadı.</div>}
   </div>
   <div className="review-pagination">
    <p className="hint">{total} sonuç · Sayfa {page} / {lastPage}</p>
    <div className="flex">
     <label>Sayfada<select value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1);setSelected(null);setDetail(null);}}>
      <option value={10}>10</option><option value={20}>20</option><option value={50}>50</option></select></label>
     <button type="button" className="secondary" onClick={()=>{setPage(v=>v-1);setSelected(null);setDetail(null);}}
      disabled={page<=1}>Önceki</button>
     <button type="button" className="secondary" onClick={()=>{setPage(v=>v+1);setSelected(null);setDetail(null);}}
      disabled={page>=lastPage}>Sonraki</button>
    </div>
   </div>
  </>}
  {queue?.run===null&&<div className="empty">Henüz tamamlanmış teknik karşılaştırma bulunamadı. M4.3 bölümünde izinli kataloğu seçip toplu işi başlatın; sonuçlar tamamlanınca burada görünecek.</div>}
  {selected&&<div className="review-detail" id="engineer-detail" aria-label="Teknik kanıt ve mühendis kararı">
   <h3>Kanıt ve karar geçmişi</h3>
   {loadingDetail&&<p role="status">Kanıt yükleniyor...</p>}
   {detailError&&<p role="alert" className="error">{detailError}</p>}
   {detail&&<>
    <p><strong>{detail.code}</strong> · {detail.position}</p>
    {detail.stale&&<p className="warning">Kaynak veya metraj güncel değil; onay kapalı.</p>}
    {detail.identity_issue&&<p role="alert" className="warning">
     Poz kimliği denetimi: {detail.identity_issue}. Onay vermeden önce M4.3'ü yeniden çalıştırıp güncel kanıt oluşturun.
    </p>}
    {detail.evidence?<><p><span className={badge(detail.evidence.status)}>
      {label[detail.evidence.status]??detail.evidence.status}</span></p>
     {!!detail.evidence.blockers.length&&<p className="warning">Engeller: {detail.evidence.blockers.join(", ")}</p>}
     {!!detail.evidence.review_flags.length&&<p className="warning">İnceleme: {detail.evidence.review_flags.join(", ")}</p>}
     <div className="table-scroll"><table><thead><tr><th>Teknik iddia</th><th>Metraj kanıtı</th><th>Katalog kanıtı</th><th>Sonuç</th></tr></thead>
      <tbody>{detail.evidence.checks.map(ch=><tr key={ch.key}><td>{ch.key}</td>
       <td>{display(ch.metraj.value)}<p className="hint">{quote(ch.metraj.quote)}</p></td>
       <td>{display(ch.catalog.value)}<p className="hint">{quote(ch.catalog.quote)}</p></td>
       <td>{label[ch.status]??ch.status}</td></tr>)}</tbody>
     </table></div>
     <p className="hint">Kanıt SHA-256: <code>{detail.evidence.evidence_sha256}</code></p>
    </>:<p className="warning">Doğrulanmış teknik kanıt bulunamadı; mühendis onayı kapalı.</p>}
    <div className="review-decision">
     <h4>Mühendis kararı</h4>
     <label>Karar gerekçesi (en az 10 karakter)
      <textarea value={reason} maxLength={500} rows={3} onChange={e=>setReason(e.target.value)}
       placeholder="İncelenen teknik kanıtı ve gerekçenizi belirtin"/></label>
     <div className="flex">
      <button disabled={busy||reason.trim().length<10||!detail.can_approve} onClick={()=>decide("approve")}
       type="button" title={!detail.can_approve?"Teknik kanıt, metraj veya katalog onaya uygun değil":"Mühendis onayını kaydet"}>
       Mühendis olarak onayla</button>
      <button disabled={busy||reason.trim().length<10} className="secondary" type="button" onClick={()=>decide("reject")}>
       Reddet</button>
     </div>
     {!detail.can_approve&&<p className="warning">Onay yalnızca güncel, kullanım hakkı aktif ve teknik olarak uygun adaylarda mümkündür.</p>}
    </div>
    <h4>Karar geçmişi (aynı metraj kalemi ve poz)</h4>
    {detail.history.length===0?<p className="hint">Henüz bir mühendis kararı yok.</p>:
     <div className="table-scroll"><table><thead><tr><th>Karar</th><th>Mühendis</th><th>Tarih</th><th>Gerekçe</th><th>Kaynak çalışma</th></tr></thead><tbody>
      {detail.history.map((h,i)=><tr key={h.run_id+"-"+i}>
       <td>{label[h.action]??h.action}</td><td>{h.reviewer}</td>
       <td>{new Date(h.at).toLocaleString("tr-TR")}</td><td>{h.reason??"—"}</td>
       <td>{h.current_run?"Güncel çalışma":"Tarihî çalışma"}</td>
      </tr>)}</tbody></table></div>}
    {detail.history_limited&&<p className="hint">En son 50 karar gösteriliyor.</p>}
   </>}
  </div>}
 </section>;
}
