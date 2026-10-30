"use client";

import {useEffect, useState} from "react";
import styles from "./review.module.css";

type InputLine = {code:string;description:string;unit:string;quantity:string;unit_price:string;amount?:string;entry_type?:string};
type Revision = {id:string;version:number;items:InputLine[];reason:string;proposed_amount:string;source_current:boolean;created_at:string};
type Approval = {id:string;action:"approve"|"reject";reason:string;source_current:boolean;created_at:string};
type PilotState = {
  source_fingerprint:string;analysis_revision_id:string|null;evidence_ready:boolean;
  pilot_confirmed:boolean;engineering_approved:false;cost_allowed:false;
  last_event:{id:string;action:"accept"|"reopen";reason:string;source_current:boolean;created_at:string;recorded_by_id:string}|null;
};
type State = {
  work_item_id:string;candidate_code:string;source_fingerprint:string;pdf_sha256:string;
  pdf_page:number;pdf_price:string;pdf_price_verified:boolean;read_only_source:true;
  source_inputs:InputLine[];latest_revision:Revision|null;
  engineering:{engineering_approved:boolean;reviewer_eligible:boolean;evidence_ready:boolean;cost_allowed:false;review:Approval|null};
};
type Position = {
  code:string;description:string;unit:string;source_page?:number;
  source_price?:string|null;source_price_verified?:boolean;pdf_edition_date?:string;
  scope_excerpt?:string;analysis_inputs?:InputLine[];
  price_audit?:{inputs_total:string;reconciliation_addition_percent:number;reconciliation_addition:string;calculated_price:string;pdf_price:string;difference:string;status:string}|null;
};
const API=(process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000").replace(/\/$/,"");
const uuid=()=>crypto.randomUUID();
const trim=(s:string)=>s.trim();
const newRow=():InputLine=>({code:"",description:"",unit:"",quantity:"1",unit_price:"0,00"});
const fieldNames:Record<string,string>={
  code:"Poz/girdi kodu",description:"Açıklama",unit:"Birim",
  quantity:"Miktar",unit_price:"Birim fiyatı",items:"Analiz girdileri",
  expected_source_fingerprint:"Kaynak",request_key:"İşlem anahtarı",
};
function errorDetail(detail:unknown):string{
  if(typeof detail==="string")return detail;
  if(Array.isArray(detail)){
    const lines=detail.slice(0,5).map((entry:unknown)=>{
      if(!entry||typeof entry!=="object")return "Geçersiz analiz girdisi.";
      const issue=entry as {loc?:unknown;msg?:unknown;type?:unknown};
      const loc=Array.isArray(issue.loc)?issue.loc:[];
      const index=loc.findIndex(x=>typeof x==="number");
      const line=index>=0&&typeof loc[index]==="number"
        ? "Girdi "+(Number(loc[index])+1):"";
      const last=loc.length?String(loc[loc.length-1]):"";
      const field=fieldNames[last]??last;
      const message=typeof issue.msg==="string"?issue.msg:"Geçersiz veya eksik değer.";
      return [line,field].filter(Boolean).join(" · ")+": "+message;
    });
    return lines.join(" | ");
  }
  if(detail&&typeof detail==="object"){
    const value=detail as {msg?:unknown;message?:unknown};
    if(typeof value.msg==="string")return value.msg;
    if(typeof value.message==="string")return value.message;
  }
  return "Sunucu işlemi reddetti; analiz satırlarının zorunlu alanlarını kontrol et.";
}

export default function EditableEngineeringReview({projectId,importId,rowId,position,onPilotChanged}:{
  projectId:string;importId:string;rowId:string;position:Position;
  onPilotChanged?:()=>void;
}){
  const [data,setData]=useState<State|null>(null);
  const [pilot,setPilot]=useState<PilotState|null>(null);
  const [lines,setLines]=useState<InputLine[]>([]);
  const [editOpen,setEditOpen]=useState(false);
  const [reviewOpen,setReviewOpen]=useState(false);
  const [editReason,setEditReason]=useState("");
  const [reviewReason,setReviewReason]=useState("");
  const [ack,setAck]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const path="/api/projects/"+encodeURIComponent(projectId)+"/a330/imports/"+
    encodeURIComponent(importId)+"/items/"+encodeURIComponent(rowId);
  const pilotPath="/api/projects/"+encodeURIComponent(projectId)+"/a331/imports/"+
    encodeURIComponent(importId)+"/items/"+encodeURIComponent(rowId);
  async function call<T>(suffix:string,body?:unknown,root=path):Promise<T>{
    const token=sessionStorage.getItem("arkemx_dev_token");
    if(!token)throw Error("Oturum sona erdi. Yeniden giriş yap.");
    const res=await fetch(API+root+suffix,{method:body?"POST":"GET",cache:"no-store",
      headers:{Authorization:"Bearer "+token,...(body?{"Content-Type":"application/json"}:{})},
      ...(body?{body:JSON.stringify(body)}:{})});
    if(!res.ok){
      const info:unknown=await res.json().catch(()=>null);
      const detail=typeof info==="object"&&info!==null&&"detail" in info?
        errorDetail((info as {detail?:unknown}).detail):
        "İşlem tamamlanamadı (HTTP "+res.status+").";
      if(res.status===409)throw Error("Kaynak, poz veya önceki kayıt değişmiş. Yenile ve tekrar incele.");
      if(res.status===403)throw Error("Bu işlem için bağımsız doğrulanmış mühendis yetkisi gerekli.");
      throw Error(detail||"İşlem tamamlanamadı (HTTP "+res.status+").");
    }
    return res.json() as Promise<T>;
  }
  async function reload(keepEditing=false){
    const [state,pilotState]=await Promise.all([
      call<State>("/analysis"),call<PilotState>("/pilot/state",undefined,pilotPath),
    ]);
    if(state.work_item_id!==rowId||state.candidate_code!==position.code||
      state.read_only_source!==true||state.engineering.cost_allowed!==false||
      pilotState.cost_allowed!==false||pilotState.engineering_approved!==false||
      pilotState.source_fingerprint!==state.source_fingerprint||
      pilotState.analysis_revision_id!==(state.latest_revision?.id??null))
      throw Error("Poz, kanıt veya yetki bilgisi uyuşmuyor.");
    setData(state);
    setPilot(pilotState);
    if(!keepEditing){
      const existing=state.latest_revision?.source_current?state.latest_revision.items:
        state.source_inputs;
      setLines(existing.map(x=>({...x,quantity:x.quantity??"",
        unit_price:x.unit_price??""})));
    }
  }
  useEffect(()=>{
    let current=true;
    setBusy(true);setError("");setData(null);setPilot(null);
    void Promise.all([
      call<State>("/analysis"),call<PilotState>("/pilot/state",undefined,pilotPath),
    ]).then(([result,pilotResult])=>{
      if(!current)return;
      if(result.work_item_id!==rowId||result.candidate_code!==position.code||
        result.read_only_source!==true||result.engineering.cost_allowed!==false||
        pilotResult.cost_allowed!==false||pilotResult.engineering_approved!==false||
        pilotResult.source_fingerprint!==result.source_fingerprint||
        pilotResult.analysis_revision_id!==(result.latest_revision?.id??null))
        throw Error("Kaynak ve kayıt uyuşmuyor.");
      setData(result);
      setPilot(pilotResult);
      const rows=result.latest_revision?.source_current?result.latest_revision.items:
        result.source_inputs;
      setLines(rows.map(x=>({...x,quantity:x.quantity??"",unit_price:x.unit_price??""})));
    }).catch(e=>{if(current)setError(e instanceof Error?e.message:"Kaynak okunamadı.")})
      .finally(()=>{if(current)setBusy(false)});
    return ()=>{current=false};
    // This component has a key tied to the current row and candidate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[projectId,importId,rowId,position.code]);
  function change(index:number,field:keyof InputLine,value:string){
    setLines(old=>old.map((x,i)=>i===index?{...x,[field]:value}:x));
  }
  async function save(){
    if(!data||busy||lines.length<1)return;
    const invalidIndex=lines.findIndex(line=>!trim(line.code)||!trim(line.unit)||
      !trim(line.quantity)||!trim(line.unit_price));
    if(invalidIndex!==-1){
      setError("Girdi "+(invalidIndex+1)+": Kod, birim, miktar ve birim fiyatı doldur. Açıklama PDF'de yoksa boş bırakabilirsin.");
      return;
    }
    setBusy(true);setError("");setNotice("");
    try{
      await call<Revision>("/analysis/revisions",{
        items:lines.map(({code,description,unit,quantity,unit_price})=>({
          code:trim(code),description:trim(description),unit:trim(unit),
          quantity:trim(quantity),unit_price:trim(unit_price),
        })),
        reason:editReason.trim(),expected_source_fingerprint:data.source_fingerprint,
        expected_previous_revision_id:data.latest_revision?.id??null,request_key:uuid(),
      });
      await reload();
      onPilotChanged?.(); // A new draft invalidates any pilot accept on the previous revision.
      setEditOpen(false);
      setReviewOpen(true);
      setNotice("Analiz taslağı kaydedildi. Şimdi 3. adımda pilot kontrolü tamamlayabilirsin.");
      setEditReason("");
    }catch(e){setError(e instanceof Error?e.message:"Taslak kaydedilemedi.");}
    finally{setBusy(false)}
  }
  async function savePilotDecision(action:"accept"|"reopen"){
    if(!data||!pilot||busy||!ack||!data.latest_revision?.source_current||
      pilot.source_fingerprint!==data.source_fingerprint||
      pilot.analysis_revision_id!==data.latest_revision.id||
      (action==="accept"&&(!pilot.evidence_ready||pilot.pilot_confirmed))||
      (action==="reopen"&&!pilot.pilot_confirmed))return;
    setBusy(true);setError("");setNotice("");
    try{
      await call("/pilot/decisions",{
        action,reason:reviewReason.trim(),
        expected_source_fingerprint:pilot.source_fingerprint,
        expected_analysis_revision_id:data.latest_revision.id,
        expected_previous_event_id:pilot.last_event?.id??null,
        request_key:uuid(),
        acknowledgement:"I_REVIEWED_SOURCE_AND_THIS_IS_NOT_ENGINEER_SIGNOFF",
      },pilotPath);
      await reload(true);
      onPilotChanged?.();
      setNotice(action==="accept"
        ?"Pilot teknik inceleme onaylandı. Mühendis imzası veya maliyet izni oluşturulmadı."
        :"Pilot teknik onayı geri alındı; önceki kayıt geçmişte korunuyor.");
      setAck(false);setReviewReason("");
    }catch(e){setError(e instanceof Error?e.message:"Pilot teknik karar kaydedilemedi.");}
    finally{setBusy(false)}
  }
  return <>
    <details className={styles.projectEvidence} open={editOpen}
      onToggle={e=>setEditOpen(e.currentTarget.open)}>
      <summary>2 · Analizi düzenle</summary>
      <p>Malzeme, işçilik, miktar ve fiyatları düzenle. Orijinal PDF değişmez.</p>
      <details className={styles.a330SourceDetails}>
        <summary>Orijinal PDF kanıtını göster</summary>
        {position.scope_excerpt&&<p><strong>PDF poz tarifi:</strong> {position.scope_excerpt}</p>}
      <small>Kaynak PDF sayfa {position.source_page??"—"} · Orijinal fiyat: {position.source_price_verified?position.source_price+" TL/"+position.unit:"Doğrulanmadı"} · PDF değiştirilemez.</small>
      {position.analysis_inputs&&<ul>{position.analysis_inputs.map((x,i)=>
        <li key={i}>{x.code} · {x.description}: {x.quantity} {x.unit} × {x.unit_price} TL = {x.amount} TL</li>)}</ul>}
      {position.price_audit&&<p className={styles.priceReconciliation}>
        PDF analiz toplamı: {position.price_audit.inputs_total} TL · Kontrol eki %{position.price_audit.reconciliation_addition_percent}:
        {" "}{position.price_audit.reconciliation_addition} TL · PDF fiyatı: {position.price_audit.pdf_price} TL.
      </p>}
      </details>
      <div className={styles.a330Edit}>
        <small>Girdileri ekleyebilir, değiştirebilir veya çıkarabilirsin. Kaydedilen her taslak geçmişte saklanır.</small>
        {busy&&<p role="status">Kaynaklar yükleniyor…</p>}
        {data?.latest_revision&&<p className={styles.a330Note}>
          {data.latest_revision.source_current ? "Analiz kayıtlı" : "Analizi yeniden kontrol et"} ·
          Sürüm {data.latest_revision.version} · Taslak tutar {data.latest_revision.proposed_amount} TL
        </p>}
        {data&&lines.map((line,i)=><div className={styles.a330Line} key={i}>
          <label>Kod<input value={line.code} maxLength={80} disabled={busy}
            onChange={e=>change(i,"code",e.target.value)} /></label>
          <label>İmalat/girdi açıklaması<input value={line.description} maxLength={250} disabled={busy}
            onChange={e=>change(i,"description",e.target.value)} /></label>
          <label>Birim<input value={line.unit} maxLength={30} disabled={busy}
            onChange={e=>change(i,"unit",e.target.value)} /></label>
          <label>Miktar<input inputMode="decimal" value={line.quantity} disabled={busy}
            onChange={e=>change(i,"quantity",e.target.value)} /></label>
          <label>Birim fiyat (TL)<input inputMode="decimal" value={line.unit_price} disabled={busy}
            onChange={e=>change(i,"unit_price",e.target.value)} /></label>
          <button type="button" className="secondary" disabled={busy||lines.length===1}
            onClick={()=>setLines(x=>x.filter((_,n)=>n!==i))}>Çıkar</button>
        </div>)}
        {data&&<div className={styles.a330Actions}>
          <button type="button" className="secondary" disabled={busy||lines.length>=30}
            onClick={()=>setLines(x=>[...x,newRow()])}>+ Girdi ekle</button>
          <button type="button" className="secondary" disabled={busy}
            onClick={()=>setLines(data.source_inputs.map(x=>({...x})))}>
            PDF kaynak girdilerini geri getir</button>
        </div>}
        {data&&<label className={styles.a330Label}>Değişiklik gerekçesi (isteğe bağlı)
          <textarea rows={2} maxLength={1000} value={editReason} disabled={busy}
            placeholder="Örneğin: Eksik işçilik girdisini ekledim, poz kapsamı kontrol edilecek."
            onChange={e=>setEditReason(e.target.value)} /></label>}
        {data&&<button type="button" disabled={busy||lines.length===0}
          onClick={()=>void save()}>Analizi kaydet</button>}
      </div>
    </details>
    <details className={styles.a330Approval} open={reviewOpen}
      onToggle={e=>setReviewOpen(e.currentTarget.open)}>
      <summary>3 · Pilot kontrolü tamamla</summary>
      {!data||!pilot ? <p>Teknik karar bilgisi yükleniyor veya kaynak okunamıyor.</p> : <>
        <p className={pilot.pilot_confirmed ? styles.a330Note : undefined}>
          <strong>Durum:</strong> {pilot.pilot_confirmed ? "Pilot kontrol tamam" :
            pilot.last_event && !pilot.last_event.source_current
              ? "Önceki kontrol güncel değil" : "Kontrol bekliyor"}.
        </p>
        {!pilot.evidence_ready&&<p className={styles.a330Warning}>
          Önce 1. adımda şartname ile poz uyumunu doğrula.
        </p>}
        {!data.latest_revision?.source_current&&<p className={styles.a330Warning}>
          Önce 2. adımda analizi kaydet.
        </p>}
        <label className={styles.a330Label}>İnceleme notu (isteğe bağlı)
          <textarea rows={2} maxLength={1000} disabled={busy} value={reviewReason}
            placeholder="İstersen bir açıklama ekleyebilirsin."
            onChange={e=>setReviewReason(e.target.value)}/>
        </label>
        <label className={styles.a330Label}>
          <input type="checkbox" checked={ack} disabled={busy}
            onChange={e=>setAck(e.target.checked)}/>
          PDF, şartname ve analizi kontrol ettim; bunun resmî mühendis onayı olmadığını biliyorum.
        </label>
        <div className={styles.a330Actions}>
          {!pilot.pilot_confirmed ? <button type="button"
            disabled={busy||!ack||!pilot.evidence_ready||
              !data.latest_revision?.source_current}
            onClick={()=>void savePilotDecision("accept")}>Pilot kontrolü tamamla</button> :
          <button type="button" className="secondary"
            disabled={busy||!ack||!data.latest_revision?.source_current}
            onClick={()=>void savePilotDecision("reopen")}>Kontrolü yeniden aç</button>}
        </div>
        <small>Pilot kontrol kaydı resmî mühendis imzası değildir ve maliyet hesabına otomatik izin vermez.</small>
      </>}
    </details>
    {(error||notice)&&<p role={error?"alert":"status"} className={error?styles.a330Warning:styles.a330Note}>{error||notice}</p>}
  </>;
}
