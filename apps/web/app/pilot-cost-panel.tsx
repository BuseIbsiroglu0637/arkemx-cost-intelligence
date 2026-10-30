"use client";

import {useEffect, useRef, useState} from "react";

const API=(process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000").replace(/\/$/, "");
type Row={work_item_id:string;source_row:number;description:string;quantity:string|null;
  unit:string|null;review_required:boolean;amount?:string|null;reason?:string;
  unit_price?:string|null;price_source?:string|null;price_date?:string|null};
type Source={import_id:string;filename:string;source_sha256:string;rows:Row[]};
type Report=Source&{id?:string;title?:string;total:string;priced_count:number;excluded_count:number;
  coverage:"complete"|"partial";preview_sha256:string;calculation_basis:string};
type Saved={id:string;title:string;total:string;coverage:string};
type Draft={price:string;source:string;date:string};
type PdfPage={catalog:{sha256:string};rows:{work_item_id:string;
  saved_selection?:{code:string|null;current:boolean;pdf_sha256:string;revision_id:string|null};
  revision_id:string|null;suggestions:{code:string;unit:string;source_price:string|null;
    source_price_verified:boolean;technical_status:string;source_page?:number;pdf_edition_date?:string}[]}[]};

async function api<T>(path:string,token:string,init:RequestInit={}):Promise<T>{
  const response=await fetch(API+path,{...init,cache:"no-store",
    headers:{Authorization:"Bearer "+token,"Content-Type":"application/json",...init.headers}});
  if(!response.ok){
    const data=await response.json().catch(()=>null);
    const detail=data?.detail;
    throw Error(response.status===401?"Oturum sona erdi. Yeniden giriş yapın.":
      typeof detail==="string"?detail:Array.isArray(detail)?detail.map((x:{msg:string})=>x.msg).join("; "):
      "İşlem tamamlanamadı ("+response.status+").");
  }
  return response.json() as Promise<T>;
}
function money(value:string){
  const [whole,fraction="00"]=value.split(".");
  return new Intl.NumberFormat("tr-TR").format(BigInt(whole))+","+fraction.padEnd(2,"0").slice(0,2)+" TL";
}

export default function PilotCostPanel({token,project,onReview}:{
  token:string|null;project:string;onReview:()=>void;
}){
  const [source,setSource]=useState<Source|null>(null);
  const [draft,setDraft]=useState<Record<string,Draft>>({});
  const [commonSource,setCommonSource]=useState("");
  const [commonDate,setCommonDate]=useState("");
  const [title,setTitle]=useState("Proje maliyet pilotu");
  const [report,setReport]=useState<Report|null>(null);
  const [history,setHistory]=useState<Saved[]>([]);
  const [checked,setChecked]=useState(false);
  const [page,setPage]=useState(0);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [reload,setReload]=useState(0);
  const generation=useRef(0);
  const working=useRef(false);
  const requestKey=useRef<string|null>(null);
  const prefix="/api/projects/"+encodeURIComponent(project)+"/pilot-costs";

  useEffect(()=>{
    const controller=new AbortController();
    generation.current++;working.current=false;
    setSource(null);setDraft({});setReport(null);setHistory([]);setChecked(false);setPage(0);setError("");
    if(!token||!project)return;
    setBusy(true);
    Promise.allSettled([
      api<Source>(prefix+"/source",token,{signal:controller.signal}),
      api<Saved[]>(prefix+"/snapshots",token,{signal:controller.signal}),
    ]).then(([input,saved])=>{
      if(controller.signal.aborted)return;
      if(input.status==="fulfilled")setSource(input.value);else setError(String(input.reason.message));
      if(saved.status==="fulfilled")setHistory(saved.value);
    }).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
    return()=>{controller.abort();generation.current++;};
  },[token,project,prefix,reload]);

  function invalidate(){setReport(null);setChecked(false);requestKey.current=null;}
  function update(id:string,field:keyof Draft,value:string){
    invalidate();setDraft(prev=>({...prev,[id]:{...(prev[id]??{price:"",source:"",date:""}),[field]:value}}));
  }
  function payload(){
    const prices=source!.rows.filter(row=>draft[row.work_item_id]?.price.trim()).map(row=>({
      work_item_id:row.work_item_id,unit:row.unit??"",unit_price:draft[row.work_item_id].price,
      source:draft[row.work_item_id].source||commonSource,source_date:draft[row.work_item_id].date||commonDate,
    }));
    for(const price of prices){
      if(price.source.trim().length<10)throw Error("Fiyat girilen her satır için belge/teklif ve sayfa içeren bir kaynak belirtin.");
      if(!/^\d{4}-\d{2}-\d{2}$/.test(price.source_date))throw Error("Fiyat girilen satırların tarihini doldurun.");
    }
    return {import_id:source!.import_id,prices};
  }
  async function action(work:()=>Promise<void>){
    if(!token||working.current)return;
    working.current=true;setBusy(true);setError("");
    const current=generation.current;
    try{await work();}catch(e){if(current===generation.current)setError(e instanceof Error?e.message:"İşlem başarısız.");}
    finally{if(current===generation.current){working.current=false;setBusy(false);}}
  }
  async function preview(){
    if(!source||!token)return;
    const current=generation.current;
    const result=await api<Report>(prefix+"/preview",token,{method:"POST",body:JSON.stringify(payload())});
    if(current===generation.current){setReport(result);setChecked(false);requestKey.current=null;}
  }
  async function save(){
    if(!report||report.id||!token||!checked)return;
    const current=generation.current;
    requestKey.current??=crypto.randomUUID();
    const result=await api<Report>(prefix+"/snapshots",token,{method:"POST",body:JSON.stringify({
      ...payload(),title,expected_preview_sha256:report.preview_sha256,request_key:requestKey.current,
      acknowledgement:"I_REVIEWED_QUANTITIES_UNITS_AND_PRICE_SOURCES",
    })});
    if(current!==generation.current)return;
    setReport(result);setChecked(false);
    const saved=await api<Saved[]>(prefix+"/snapshots",token);
    if(current===generation.current)setHistory(saved);
  }
  async function open(id:string){
    if(!token)return;const current=generation.current;
    const result=await api<Report>(prefix+"/snapshots/"+encodeURIComponent(id),token);
    if(current===generation.current){setReport(result);setChecked(false);}
  }
  async function download(id:string){
    if(!token)return;const current=generation.current;
    const response=await fetch(API+prefix+"/snapshots/"+encodeURIComponent(id)+"/csv",{
      cache:"no-store",headers:{Authorization:"Bearer "+token}});
    if(!response.ok)throw Error("Rapor indirilemedi. Oturumu ve rapor bütünlüğünü kontrol edin.");
    const blob=await response.blob();if(current!==generation.current)return;
    const url=URL.createObjectURL(blob),anchor=document.createElement("a");
    anchor.href=url;anchor.download="arkemx-pilot-"+id+".csv";anchor.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function importPdfPrices(){
    if(!source||!token)return;
    const current=generation.current,importId=source.import_id,found:Record<string,Draft>={};
    let sha:string|null=null;
    for(let offset=0;offset<source.rows.length;offset+=20){
      const data=await api<PdfPage>("/api/projects/"+encodeURIComponent(project)+"/a318/imports/"+
        encodeURIComponent(importId)+"/suggestions?offset="+offset,token);
      if(current!==generation.current)return;
      if(sha&&sha!==data.catalog.sha256)throw Error("PDF kaynağı değişti; fiyatlar aktarılmadı.");
      sha=data.catalog.sha256;
      for(const row of data.rows){
        const selected=row.saved_selection;
        if(!selected?.current||selected.pdf_sha256!==sha||selected.revision_id!==row.revision_id)continue;
        const option=row.suggestions.find(p=>p.code===selected.code);
        const item=source.rows.find(r=>r.work_item_id===row.work_item_id);
        if(!option?.source_price_verified||!option.source_price||option.technical_status==="blocked"||
          !item||item.unit!==option.unit||item.review_required)continue;
        found[row.work_item_id]={price:option.source_price,date:"2026-01-01",
          source:`Kullanıcı PDF'si 2026/01; poz ${option.code}; sayfa ${option.source_page??"belirtilmemiş"}; SHA-256 ${sha}`};
      }
    }
    if(!Object.keys(found).length)throw Error("Aktarılabilir seçili PDF fiyatı yok. Pozları inceleyin veya kaynaklı fiyatı elle girin.");
    invalidate();
    // Preserve all user-entered prices. Transfer is a proposal requiring review.
    setDraft(prev=>{const next={...prev};for(const [id,value] of Object.entries(found))if(!prev[id]?.price)next[id]=value;return next;});
  }

  return <section className="card stack" aria-label="Kaynaklı maliyet pilotu">
    <h2>Kaynaklı maliyet pilotu</h2>
    <p>Metraj miktarını kaynaklı birim fiyatla hesaplayın, kontrol edin ve raporu kaydedin.</p>
    <p className="hint">Kullanıcı kontrollü pilot. Otomatik mühendis onayı veya resmî fiyat doğrulaması yapmaz.
      KDV, kâr ve genel gider ayrıca eklenmez; birim fiyatın kapsamını kontrol edin.</p>
    {error&&<p role="alert">{error}</p>}
    {busy&&<p role="status">İşlem sürüyor…</p>}
    <div className="flex"><button type="button" className="secondary" disabled={busy}
      onClick={()=>{setCommonSource("");setCommonDate("");setReload(x=>x+1);}}>Güncel Excel'i yükle · kaydedilmemiş fiyatlar temizlenir</button>
      <button type="button" className="secondary" onClick={onReview}>Pozları incele</button></div>
    {source&&<fieldset disabled={busy} className="stack">
      <legend>{source.filename} · {source.rows.length} metraj satırı</legend>
      <p className="hint">Son kaydedilen Excel kullanılır. Fiyatlar TRY / satırın birimi olmalı.
        Kaydedilmeyen girişler bu ekrandan ayrılınca silinir.</p>
      <label>Tüm satırlar için ortak fiyat kaynağı (satırda değiştirilebilir)
        <input value={commonSource} maxLength={500} placeholder="Örn. Tedarikçi teklifi ABC-42, sayfa 3"
          onChange={e=>{invalidate();setCommonSource(e.target.value);}}/></label>
      <label>Ortak fiyat tarihi<input type="date" value={commonDate}
        onInput={e=>{invalidate();setCommonDate(e.currentTarget.value);}}
        onChange={e=>{invalidate();setCommonDate(e.target.value);}}/></label>
      <button type="button" className="secondary" onClick={()=>void action(importPdfPrices)}>Seçili PDF fiyatlarını boş alanlara aktar</button>
      <div className="table-scroll"><table><thead><tr><th>İmalat / miktar</th><th>Birim fiyat TRY</th><th>Fiyat kaynağı / tarih</th></tr></thead>
        <tbody>{source.rows.slice(page*20,page*20+20).map(row=><tr key={row.work_item_id}>
          <td>{row.description}<br/><strong>{row.quantity??"Eksik"} {row.unit??"Birim eksik"}</strong><br/>
            <small>Excel satırı {row.source_row}{row.review_required?" · Metraj düzeltmesi gerekli":""}</small></td>
          <td><label>Satır {row.source_row} birim fiyatı<input inputMode="decimal" placeholder="1250,50"
            disabled={row.review_required||!row.unit||!row.quantity} value={draft[row.work_item_id]?.price??""}
            onChange={e=>update(row.work_item_id,"price",e.target.value)}/></label></td>
          <td><details><summary>Satıra özel kaynak ve tarih</summary>
            <label>Satır {row.source_row} fiyat kaynağı<input maxLength={500} value={draft[row.work_item_id]?.source??""}
              placeholder={commonSource||"Belge/teklif numarası ve sayfa"} onChange={e=>update(row.work_item_id,"source",e.target.value)}/></label>
            <label>Satır {row.source_row} fiyat tarihi<input type="date" value={draft[row.work_item_id]?.date??""}
              onInput={e=>update(row.work_item_id,"date",e.currentTarget.value)}
              onChange={e=>update(row.work_item_id,"date",e.target.value)}/></label>
          </details><small>{draft[row.work_item_id]?.source||commonSource||"Kaynak girilmedi"}<br/>
            {draft[row.work_item_id]?.date||commonDate||"Tarih girilmedi"}</small></td>
        </tr>)}</tbody></table></div>
      <div className="flex"><button type="button" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Önceki</button>
        <span>Sayfa {page+1} / {Math.ceil(source.rows.length/20)}</span>
        <button type="button" disabled={(page+1)*20>=source.rows.length} onClick={()=>setPage(p=>p+1)}>Sonraki</button></div>
      <button type="button" onClick={()=>void action(preview)}>Maliyeti hesapla</button>
    </fieldset>}
    {report&&<section className="stack" aria-label="Maliyet sonucu">
      <h3>{report.id?"Kayıtlı rapor: "+report.title:"Hesap önizlemesi"}</h3>
      <p><strong>{report.coverage==="complete"?"Girilen tüm satırların toplamı":"KISMİ ARA TOPLAM"}: {money(report.total)}</strong><br/>
        {report.priced_count} kalem fiyatlı · {report.excluded_count} kalem hesap dışında</p>
      {report.coverage==="partial"&&<p role="alert">Bu tutar tam proje maliyeti değildir. Hesap dışı kalemler sıfır TL sayılmaz.</p>}
      <p className="hint">{report.calculation_basis} Tüm satırların fiyatlanması, proje kapsamının veya teknik uygunluğun onaylandığı anlamına gelmez.</p>
      <details><summary>Hesap satırlarını ve eksikleri göster</summary><div className="table-scroll"><table>
        <thead><tr><th>Satır / imalat</th><th>Miktar × fiyat</th><th>Tutar</th><th>Kaynak / durum</th></tr></thead>
        <tbody>{report.rows.map(row=><tr key={row.work_item_id}><td>{row.source_row} · {row.description}</td>
          <td>{row.quantity??"—"} {row.unit} × {row.unit_price??"—"}</td><td>{row.amount?money(row.amount):"Hesap dışı"}</td>
          <td>{row.price_source} {row.price_date}<br/>{row.reason}</td></tr>)}</tbody></table></div></details>
      {report.id?<button type="button" disabled={busy} onClick={()=>void action(()=>download(report.id!))}>CSV raporunu indir</button>:
        <fieldset disabled={busy} className="stack"><label>Rapor adı<input value={title} maxLength={160} onChange={e=>setTitle(e.target.value)}/></label>
          <label><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/>
            Miktarları, birimleri, fiyat kaynaklarını ve hesap dışında kalan kalemleri kontrol ettim. Bu kayıt mühendis onayı değildir.</label>
          <button type="button" disabled={!checked||!report.priced_count||title.trim().length<3} onClick={()=>void action(save)}>Kontrol edilen raporu kaydet</button></fieldset>}
    </section>}
    <h3>Kayıtlı pilot raporları</h3>
    {!history.length?<p className="hint">Henüz kayıtlı rapor yok.</p>:history.map(entry=><div className="flex between" key={entry.id}>
      <span>{entry.title} · {money(entry.total)} · {entry.coverage==="partial"?"Kısmi":"Tüm satırlar fiyatlı"}</span>
      <button type="button" disabled={busy} onClick={()=>void action(()=>open(entry.id))}>Raporu aç</button></div>)}
  </section>;
}
