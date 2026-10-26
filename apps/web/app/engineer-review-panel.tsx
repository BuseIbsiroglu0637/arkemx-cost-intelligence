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
type ReviewedItem={candidate_id:string;work_item_id:string;run_id:string;code:string;
 metraj:string;reason:string;evidence_sha256:string};
const REVIEW_CONFIRM="I_REVIEWED_THIS_CANDIDATE_EVIDENCE";
const genericReasons=new Set(["kendi gerekçem","kendi gerekcem","test gerekçesi","test gerekcesi",
 "deneme gerekçesi","deneme gerekcesi","kontrol edildi","uygun bulundu","onay veriyorum",
 "gerekçe yazılacak","gerekce yazilacak","inceledim onaylıyorum","incelendi onaylandı",
 "incelendi onaylandi"]);
function reasonIsSpecific(value:string):boolean {
 const text=value.trim().replace(/\s+/g," ");
 const words=text.match(/\p{L}+/gu)??[];
 const informative=new Set(words.filter(word=>word.length>=3).map(word=>word.toLocaleLowerCase("tr")));
 return text.length>=10 && text.length<=500 &&
   !genericReasons.has(text.toLocaleLowerCase("tr")) &&
   words.join("").length>=12 && informative.size>=3;
}
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
 const [controlled,setControlled]=useState(false);
 const [reviewChecked,setReviewChecked]=useState(false);
 const [staged,setStaged]=useState<ReviewedItem[]>([]);
 const [finalChecked,setFinalChecked]=useState(false);
 const [batchBusy,setBatchBusy]=useState(false);


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
  setSelected(null);setDetail(null);setReason("");setControlled(false);
  setReviewChecked(false);setStaged([]);setFinalChecked(false);},[project]);

 async function inspect(candidateId:string){
  if(selected===candidateId){setSelected(null);setDetail(null);return;}
  if(!token)return;
  setSelected(candidateId);setDetail(null);setDetailError("");setReason("");
  setReviewChecked(false);setLoadingDetail(true);
  try{setDetail(await api<Detail>(`/api/projects/${project}/m42/candidates/${candidateId}`,token));}
  catch(err){setDetailError(err instanceof Error?err.message:String(err));}
  finally{setLoadingDetail(false);}
 }
 function toggleControlled(){
  const next=!controlled;
  setControlled(next);setStatus(next?"compatible":"all");setDecision(next?"undecided":"all");
  setPage(1);setPageSize(next?10:20);setSearch("");setDraftSearch("");
  setSelected(null);setDetail(null);setReviewChecked(false);setReason("");
  setStaged([]);setFinalChecked(false);setMessage("");setError("");
 }
 function stageReviewed(){
  if(!queue?.run||!detail||!detail.evidence||!detail.can_approve||
     !controlled||!reviewChecked||!reasonIsSpecific(reason))return;
  const row=queue.rows.find(x=>x.candidate_id===detail.candidate_id);
  if(!row||!row.can_approve||row.last_decision||
     staged.some(x=>x.work_item_id===row.work_item_id)||
     staged.some(x=>x.candidate_id===row.candidate_id)||staged.length>=10){
   setError("Bu aday inceleme listesine eklenemiyor: karar, tekrar veya seçim sınırını kontrol edin.");
   return;
  }
  setStaged(rows=>[...rows,{candidate_id:row.candidate_id,work_item_id:row.work_item_id,
   run_id:queue.run!.id,code:row.code,metraj:row.metraj,
   reason:reason.trim(),evidence_sha256:detail.evidence!.evidence_sha256}]);
  setFinalChecked(false);setReviewChecked(false);setReason("");
  setSelected(null);setDetail(null);setMessage("Bir adayın kanıtı ve gerekçesi inceleme listesine eklendi.");
 }
 async function saveReviewed(){
  if(!token||!project||!queue?.run||!finalChecked||batchBusy||staged.length===0)return;
  const copy=[...staged];let saved=0;
  setBatchBusy(true);setMessage("");setError("");
  try{
   for(const entry of copy){
    if(entry.run_id!==queue.run.id)throw new Error("Çalışma değişti. Kaydedilmemiş seçimleri yeniden inceleyin.");
    const current=await api<Detail>(`/api/projects/${project}/m42/candidates/${entry.candidate_id}`,token);
    if(!current.can_approve||current.evidence?.evidence_sha256!==entry.evidence_sha256)
     throw new Error(`${entry.code}: teknik kanıt veya onay uygunluğu değişti. Kaydedilmedi.`);
    await api(`/api/projects/${project}/m42/controlled-decisions`,token,"POST",{
     run_id:entry.run_id,candidate_id:entry.candidate_id,
     evidence_sha256:entry.evidence_sha256,
     reason:entry.reason,confirmation:REVIEW_CONFIRM});
    saved+=1;
    setStaged(rows=>rows.filter(x=>x.candidate_id!==entry.candidate_id));
   }
   setMessage(`${saved} ayrı mühendis kararı, mevcut M2 karar kapısından doğrulanarak kaydedildi.`);
  }catch(err){
   setError(`Seri kayıt durduruldu. ${saved} karar için başarı yanıtı alındı. `+
    "Diğer adayların durumunu karar geçmişinden doğrulayın; otomatik tekrar gönderim yapılmadı. "+
    (err instanceof Error?err.message:String(err)));
  }finally{
   setFinalChecked(false);setBatchBusy(false);setRevision(x=>x+1);
  }
 }
 async function decide(action:"approve"|"reject"){
  if(!token||!queue?.run||!detail||busy||!reasonIsSpecific(reason))return;
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
   <div className="m421-toggle">
    <div><h3>M4.2.1 · Kontrollü seri inceleme</h3>
     <p className="hint">Her adayın kanıtı tek tek açılır ve ayrı gerekçe yazılır.
      Onay engelli adaylar seçilemez; en fazla 10 incelenmiş aday sırayla kaydedilir.</p></div>
    <button type="button" className="secondary" onClick={toggleControlled}
     disabled={batchBusy}>{controlled?"Seri incelemeyi kapat":"Seri incelemeyi aç"}</button>
   </div>
   {controlled&&<div className="m421-workspace" aria-label="İncelenmiş karar listesi">
    <div className="flex between"><strong>İncelenen adaylar · {staged.length}/10</strong>
      <span className="tag">Uyumlu + kararsız adaylar</span></div>
    <p className="hint">Bir adayın “Kanıt ve karar” ayrıntısını açın, kanıtını gözden geçirin,
     kişisel gerekçesini yazın ve inceleme listesine ekleyin. Toplu otomatik onay yoktur.</p>
    {staged.length>0?<><div className="table-scroll m421-list"><table>
     <thead><tr><th>Poz</th><th>İmalat / gerekçe</th><th>Kanıt</th><th>İşlem</th></tr></thead>
     <tbody>{staged.map(row=><tr key={row.candidate_id}>
      <td><strong>{row.code}</strong></td>
      <td><div>{row.metraj}</div><p className="m422-reason">{row.reason}</p></td>
      <td><code title={row.evidence_sha256}>{row.evidence_sha256.slice(0,12)}…</code></td>
      <td><button type="button" className="secondary" disabled={batchBusy}
       onClick={()=>{setStaged(all=>all.filter(x=>x.candidate_id!==row.candidate_id));setFinalChecked(false);}}>
       Listeden çıkar</button></td></tr>)}</tbody></table></div>
      <label className="m421-consent"><input type="checkbox" checked={finalChecked} disabled={batchBusy}
       onChange={e=>setFinalChecked(e.target.checked)}/>
       <span>Listedeki her adayın kanıtını ayrı ayrı inceledim; kendi gerekçelerimle kararları kaydetmeyi onaylıyorum.</span>
      </label>
      <button type="button" onClick={saveReviewed} disabled={batchBusy||!finalChecked||staged.length===0}>
       {batchBusy?"Kararlar doğrulanarak kaydediliyor…":`${staged.length} bireysel kararı sırayla kaydet`}
      </button>
     </>:<p className="hint">İnceleme listesi henüz boş.</p>}
   </div>}
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
       disabled={controlled&&filter!=="compatible"} aria-pressed={status===filter}>
       <strong>{count}</strong><span>{title}</span>
      </button>)}
   </div>
   <div className="m422-current-summary" aria-label="Güncel çalışma kararları">
    <strong>Yalnızca güncel M4.3 çalışmasının kararları</strong>
    <span>{approvals.approved??0} onay · {approvals.rejected??0} ret · {approvals.undecided??0} kararsız</span>
    <p className="hint">Önceki çalışmalarda verilen kararlar bu sayaca eklenmez. 300 aday, 100 farklı metraj satırına aittir.</p>
   </div>
   <form className="review-filters" onSubmit={submitSearch}>
    <label>Teknik durum<select value={status} disabled={controlled}
      onChange={e=>filterStatus(e.target.value as Status)}>
     <option value="all">Tüm durumlar</option><option value="review">Uzman incelemesi</option>
     <option value="blocked">Engelli</option><option value="compatible">Uyumlu aday</option>
     <option value="missing">Kanıt eksik</option></select></label>
    <label>Son mühendis kararı<select value={decision} disabled={controlled}
      onChange={e=>filterDecision(e.target.value as Decision)}>
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
     <label>Karar gerekçesi (teknik bulgu ve değerlendirme)
      <textarea value={reason} maxLength={500} rows={3} onChange={e=>setReason(e.target.value)}
       aria-describedby="m422-reason-hint" aria-invalid={reason.length>0&&!reasonIsSpecific(reason)}
       placeholder="Örn. Poz kimliği 004, C25/30 sınıfı ve nakliye dahil kapsamı doğrulandı; diğer kapsamlar belirtilmemiştir."/></label>
     <p id="m422-reason-hint" className={reason.length>0&&!reasonIsSpecific(reason)?"warning":"hint"}>
      Kontrol ettiğiniz teknik kanıtı açıklayın. Yalnızca nokta, “kendi gerekçem” veya genel ifadeler kabul edilmez.
     </p>
     {controlled?<div className="m421-stage">
      <label className="m421-consent"><input type="checkbox" checked={reviewChecked}
       disabled={!detail.can_approve} onChange={e=>setReviewChecked(e.target.checked)}/>
       <span>Bu adaya ait teknik kanıtı, kimlik eşleşmesini ve SHA-256 bilgisini inceledim.</span>
      </label>
      <button type="button" onClick={stageReviewed}
       disabled={!detail.can_approve||!reviewChecked||!reasonIsSpecific(reason)||
        staged.length>=10||staged.some(x=>x.candidate_id===detail.candidate_id)||
        !queue?.rows.some(x=>x.candidate_id===detail.candidate_id&&!x.last_decision)}>
       İncelediğim adayı listeye ekle</button>
      <p className="hint">Bu işlem henüz karar kaydetmez. Kararlar yukarıdaki ayrı onayla sırayla kaydedilir.</p>
     </div>:<div className="flex">
      <button disabled={busy||!reasonIsSpecific(reason)||!detail.can_approve} onClick={()=>decide("approve")}
       type="button" title={!detail.can_approve?"Teknik kanıt, metraj veya katalog onaya uygun değil":"Mühendis onayını kaydet"}>
       Mühendis olarak onayla</button>
      <button disabled={busy||!reasonIsSpecific(reason)} className="secondary" type="button" onClick={()=>decide("reject")}>
       Reddet</button>
     </div>}
     {!detail.can_approve&&<p className="warning">Onay yalnızca güncel, kullanım hakkı aktif ve teknik olarak uygun adaylarda mümkündür.</p>}
    </div>
    <h4>Karar geçmişi (aynı metraj kalemi ve poz)</h4>
    {detail.history.length===0?<p className="hint">Henüz bir mühendis kararı yok.</p>:<>
     <div className="m422-history-summary">
      <span className="m422-current-label">Güncel çalışma: {detail.history.filter(h=>h.current_run).length} karar</span>
      <span className="m422-historical-label">Tarihî çalışma: {detail.history.filter(h=>!h.current_run).length} karar</span>
     </div>
     {detail.history.some(h=>h.current_run)&&<div className="m422-history-current">
      <strong>Güncel çalışmaya ait kararlar</strong>
      <div className="table-scroll"><table><thead><tr><th>Karar</th><th>Mühendis</th><th>Tarih</th><th>Gerekçe</th></tr></thead>
       <tbody>{detail.history.filter(h=>h.current_run).map((h,i)=><tr key={h.run_id+"-"+i}>
        <td>{label[h.action]??h.action}</td><td>{h.reviewer}</td>
        <td>{new Date(h.at).toLocaleString("tr-TR")}</td><td>{h.reason??"—"}</td>
       </tr>)}</tbody></table></div>
     </div>}
     {detail.history.some(h=>!h.current_run)&&<details className="m422-history-archive">
      <summary>Tarihî kararları göster ({detail.history.filter(h=>!h.current_run).length})</summary>
      <p className="hint">Önceki analizlerin denetim kayıtlarıdır; güncel çalışmaya onay aktarmaz.</p>
      <div className="table-scroll"><table><thead><tr><th>Karar</th><th>Mühendis</th><th>Tarih</th><th>Gerekçe</th><th>Çalışma kimliği</th></tr></thead>
       <tbody>{detail.history.filter(h=>!h.current_run).map((h,i)=><tr key={h.run_id+"-"+i}>
        <td>{label[h.action]??h.action}</td><td>{h.reviewer}</td>
        <td>{new Date(h.at).toLocaleString("tr-TR")}</td><td>{h.reason??"—"}</td>
        <td><code>{h.run_id.slice(0,8)}…</code></td>
       </tr>)}</tbody></table></div>
     </details>}
    </>}
    {detail.history_limited&&<p className="hint">En son 50 karar gösteriliyor; sayılar bu listeyi temel alır.</p>}
   </>}
  </div>}
 </section>;
}
