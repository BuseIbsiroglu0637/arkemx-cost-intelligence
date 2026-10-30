"use client";
import {useEffect,useMemo,useState} from "react";
import CostAnalysisPanel from "./cost-analysis-panel";

type Candidate = {candidate_id:string;source_row:number;description:string;position_code:string;
 quantity:string;unit:string;evidence_sha256:string};
type Eligible = {run_id:string;row_count:number;eligible_count:number;items:Candidate[]};
type Estimate = {id:string;title:string;total:string;line_count:number;created_at:string;currency:string;status:string;snapshot_sha256:string};
type CostLine = {source_row:number;description:string;position_code:string;quantity:string;
 unit:string;unit_price:string;amount:string;price_source:string};
type Detail = Estimate & {lines:CostLine[]};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";

async function request<T>(path:string,token:string,method:"GET"|"POST"="GET",body?:unknown):Promise<T>{
 const r=await fetch(BASE+path,{method,cache:"no-store",headers:{
  Authorization:"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},
  body:body?JSON.stringify(body):undefined});
 if(!r.ok){const e=await r.json().catch(()=>({detail:"HTTP "+r.status}));
  throw new Error(typeof e.detail==="string"?e.detail:"HTTP "+r.status);}
 return r.json() as Promise<T>;
}

export default function CostPanel({token,project}:{token:string|null;project:string}){
 const [eligible,setEligible]=useState<Eligible|null>(null);
 const [history,setHistory]=useState<Estimate[]>([]);
 const [detail,setDetail]=useState<Detail|null>(null);
 const [chosen,setChosen]=useState<Record<string,boolean>>({});
 const [prices,setPrices]=useState<Record<string,string>>({});
 const [title,setTitle]=useState("Proje maliyet taslağı");
 const [priceSource,setPriceSource]=useState("");
 const [search,setSearch]=useState("");
 const [page,setPage]=useState(1);
 const [detailPage,setDetailPage]=useState(1);
 const [error,setError]=useState("");
 const [blocked,setBlocked]=useState("");
 const [notice,setNotice]=useState("");
 const [busy,setBusy]=useState(false);
 const [loading,setLoading]=useState(true);
 const [refresh,setRefresh]=useState(0);
 useEffect(()=>{
  if(!token||!project){setLoading(false);return;}
  let active=true;setLoading(true);setDetail(null);setEligible(null);
  setChosen({});setPrices({});setError("");setBlocked("");setNotice("");
  Promise.allSettled([
   request<Eligible>("/api/projects/"+project+"/m5/eligible",token),
   request<Estimate[]>("/api/projects/"+project+"/m5/estimates",token)
  ]).then(results=>{
   if(!active)return;
   if(results[0].status==="fulfilled")setEligible(results[0].value);
   else setBlocked(results[0].reason instanceof Error?results[0].reason.message:String(results[0].reason));
   if(results[1].status==="fulfilled")setHistory(results[1].value);
   else setError(results[1].reason instanceof Error?results[1].reason.message:String(results[1].reason));
   setLoading(false);
  });
  return()=>{active=false;};
 },[token,project,refresh]);
 const visible=useMemo(()=>{
  const term=search.toLocaleLowerCase("tr-TR").trim();
  const rows=eligible?.items??[];
  return term?rows.filter(v=>(v.description+" "+v.position_code+" "+v.source_row)
    .toLocaleLowerCase("tr-TR").includes(term)):rows;
 },[eligible,search]);
 const pages=Math.max(1,Math.ceil(visible.length/20));
 const shown=visible.slice((page-1)*20,page*20);
 const selected=Object.keys(chosen).filter(id=>chosen[id]);
 const valid=Boolean(!busy&&eligible&&selected.length&&title.trim().length>=3
   &&priceSource.trim().length>=10&&selected.every(id=>{
    const p=prices[id]||"";
    return /^[0-9]{1,9}(\.[0-9]{1,4})?$/.test(p)&&Number(p)>0;
   }));
 async function save(){
  if(!token||!eligible||!valid)return;
  setBusy(true);setError("");setNotice("");
  try{
   const e=await request<Estimate>("/api/projects/"+project+"/m5/estimates",token,"POST",{
    run_id:eligible.run_id,title:title.trim(),request_key:crypto.randomUUID(),
    lines:selected.map(id=>({candidate_id:id,unit_price:prices[id],price_source:priceSource.trim()}))
   });
   setHistory(await request<Estimate[]>("/api/projects/"+project+"/m5/estimates",token));
   setDetailPage(1);
   setDetail(await request<Detail>("/api/projects/"+project+"/m5/estimates/"+e.id,token));
   setChosen({});
   setNotice("Taslak kaydedildi. Nihai teklif veya otomatik mühendis onayı oluşturulmadı.");
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 async function show(id:string){
  if(!token)return;
  setBusy(true);setError("");
  try{setDetailPage(1);setDetail(await request<Detail>("/api/projects/"+project+"/m5/estimates/"+id,token));}
  catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 async function csv(id:string){
  if(!token)return;
  setBusy(true);setError("");
  try{
   const r=await fetch(BASE+"/api/projects/"+project+"/m5/estimates/"+id+"/csv",{
     headers:{Authorization:"Bearer "+token},cache:"no-store"});
   if(!r.ok)throw new Error("CSV dışa aktarım hatası: HTTP "+r.status);
   const blob=await r.blob();
   const url=URL.createObjectURL(blob);
   const a=document.createElement("a");
   a.href=url;a.download="arkemx-m5-"+id+".csv";
   document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 return <details className="card cost-advanced" aria-label="Resmî maliyet işlemleri">
  <summary>Resmî maliyet taslakları ve gelişmiş işlemler</summary>
  <div className="cost-panel">
  <div className="card stack">
   <div className="flex between"><div><h2>Taslak maliyet hesabı</h2>
    <p className="hint">Onaylı poz × elle girilen birim fiyat · kaynaklı hesap geçmişi</p></div>
    <span className="tag">Yerel pilot</span></div>
   <p className="cost-note">Resmî birim fiyat otomatik kullanılmaz. Kullanıcı fiyat kaynağını açıklayarak TRY tutarı girer.
    Sonuç nihai teklif veya onaylanmış maliyet değildir.</p>
   {loading&&<p role="status">Pozlar ve taslaklar yükleniyor...</p>}
   {blocked&&<p className="warning" role="alert">Yeni hesap oluşturulamıyor: {blocked}.
     Bekleyen toplu iş, metraj revizyonu, kaynak hakkı ve mühendis onaylarını kontrol edin.</p>}
   {error&&<p className="error" role="alert">{error}</p>}
   {notice&&<p className="success" role="status">{notice}</p>}
   <div className="flex between"><p className="hint">Maliyet hesabına alınabilir poz:
     <strong> {eligible?.eligible_count??"—"}</strong></p>
     <button type="button" className="secondary" disabled={busy||loading} onClick={()=>setRefresh(v=>v+1)}>Yenile</button>
   </div>
   {eligible&&<div className="stack">
     <p className="hint">İncelenen çalışmada {eligible.row_count} metraj satırı var; {eligible.eligible_count} aday maliyet hesabına alınabilir. Taslak aşağıda seçtiğiniz satırları kapsar. İncelemesi tamamlanmayan satırlar fiyatlandırılmaz.</p>
     <label>Taslak başlığı<input maxLength={160} value={title}
       onChange={e=>setTitle(e.target.value)} placeholder="Örn. Kaba inşaat maliyeti"/></label>
     <label>Fiyat kaynağı (tüm seçili satırlar için; en az 10 karakter)
       <input maxLength={200} value={priceSource} onChange={e=>setPriceSource(e.target.value)}
        placeholder="Örn. Firmamızın manuel sentetik birim fiyatı"/></label>
     <div className="cost-toolbar"><label>Poz veya imalat ara
       <input value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}}
         placeholder="Poz kodu / imalat adı"/></label>
       <span className="hint">{visible.length} sonuç · {selected.length} seçili · Sayfa {page}/{pages}</span>
     </div>
     {eligible.items.length===0?<div className="empty">
       <strong>Henüz fiyatlandırılabilir poz yok.</strong>
       <p className="hint">Pozları incele adımında, mühendis kararı ve gerekli kontrolleri tamamlanan adaylar burada görünür.</p>
      </div>:<div className="table-scroll"><table className="cost-table"><thead><tr>
       <th>Seç</th><th>Metraj / Poz</th><th>Miktar</th><th>Birim fiyat (₺)</th></tr></thead>
       <tbody>{shown.map(item=><tr key={item.candidate_id}>
        <td><input type="checkbox" aria-label={"Satır "+item.source_row+" seç"}
           checked={!!chosen[item.candidate_id]}
           onChange={e=>setChosen(v=>({...v,[item.candidate_id]:e.target.checked}))}/></td>
        <td><strong>#{item.source_row} · {item.description}</strong>
         <div className="hint">{item.position_code}</div></td>
        <td>{item.quantity} {item.unit}</td>
        <td><input inputMode="decimal" className="cost-price" placeholder="1250.00"
         aria-label={"Satır "+item.source_row+" birim fiyatı"} value={prices[item.candidate_id]??""}
         onChange={e=>setPrices(v=>({...v,[item.candidate_id]:e.target.value}))}/></td>
       </tr>)}</tbody></table></div>}
     {visible.length>20&&<div className="flex between">
       <button type="button" className="secondary" disabled={page<=1} onClick={()=>setPage(v=>v-1)}>Önceki</button>
       <span className="hint">Sayfa {page}/{pages}</span>
       <button type="button" className="secondary" disabled={page>=pages} onClick={()=>setPage(v=>v+1)}>Sonraki</button>
      </div>}
     <div className="cost-selection"><p className="hint">Seçilen: {selected.length}. Tutarlar sunucuda Decimal ile hesaplanır.</p>
      <button type="button" disabled={!valid} onClick={save}>{busy?"Kaydediliyor...":"Hesapla ve taslağı kaydet"}</button>
     </div>
    </div>}
  </div>
  <div className="card stack">
   <h2>Kayıtlı maliyet taslakları</h2>
   {history.length===0?<p className="hint">Kayıtlı taslak yok.</p>:
    <div className="cost-drafts">{history.map(d=><div className="flex between" key={d.id}>
     <div><strong>{d.title}</strong><div className="hint">
      {new Date(d.created_at).toLocaleString("tr-TR")} · {d.line_count} poz · {d.total} TRY · Taslak
     </div></div><button type="button" className="secondary" disabled={busy} onClick={()=>show(d.id)}>Ayrıntı</button>
    </div>)}</div>}
   {detail&&<div className="cost-result">
    <div className="flex between"><div><h3>{detail.title}</h3>
      <p className="hint">Değiştirilemez taslak · Resmî fiyat veya nihai teklif değil</p></div>
     <button type="button" className="secondary" disabled={busy} onClick={()=>csv(detail.id)}>CSV dışa aktar</button>
    </div>
    <strong className="amount">{detail.total} TRY</strong>
    <div className="table-scroll"><table><thead><tr><th>Satır</th><th>Poz</th><th>Miktar</th><th>Birim fiyat</th><th>Tutar</th></tr></thead>
     <tbody>{detail.lines.slice((detailPage-1)*20,detailPage*20).map((line,i)=><tr key={i}>
      <td>{line.source_row}</td><td>{line.position_code}<div className="hint">{line.description}</div></td>
      <td>{line.quantity} {line.unit}</td><td>{line.unit_price} ₺</td><td>{line.amount} ₺</td>
     </tr>)}</tbody></table></div>
    {detail.lines.length>20&&<div className="flex between">
      <button type="button" className="secondary" disabled={detailPage<=1} onClick={()=>setDetailPage(n=>n-1)}>Önceki</button>
      <span className="hint">Taslak satırları · Sayfa {detailPage}/{Math.ceil(detail.lines.length/20)}</span>
      <button type="button" className="secondary" disabled={detailPage>=Math.ceil(detail.lines.length/20)}
        onClick={()=>setDetailPage(n=>n+1)}>Sonraki</button>
    </div>}
    <p className="hint">Taslak SHA-256: <code>{detail.snapshot_sha256}</code></p>
   </div>}
  </div>
  <CostAnalysisPanel token={token} project={project} history={history}/>
  </div>
 </details>;
}

