"use client";

import {useEffect, useState} from "react";
import styles from "./review.module.css";

type InputLine = {code:string;description:string;unit:string;quantity:string;unit_price:string;amount?:string;entry_type?:string};
type Revision = {id:string;version:number;items:InputLine[];reason:string;proposed_amount:string;source_current:boolean;created_at:string};
type Approval = {id:string;action:"approve"|"reject";reason:string;source_current:boolean;created_at:string};
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

export default function EditableEngineeringReview({projectId,importId,rowId,position}:{
  projectId:string;importId:string;rowId:string;position:Position;
}){
  const [data,setData]=useState<State|null>(null);
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
  const reviewPath="/api/projects/"+encodeURIComponent(projectId)+"/a327/imports/"+
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
        String((info as {detail?:unknown}).detail):"";
      if(res.status===409)throw Error("Kaynak, poz veya önceki kayıt değişmiş. Yenile ve tekrar incele.");
      if(res.status===403)throw Error("Bu işlem için bağımsız doğrulanmış mühendis yetkisi gerekli.");
      throw Error(detail||"İşlem tamamlanamadı (HTTP "+res.status+").");
    }
    return res.json() as Promise<T>;
  }
  async function reload(keepEditing=false){
    const state=await call<State>("/analysis");
    if(state.work_item_id!==rowId||state.candidate_code!==position.code||
      state.read_only_source!==true||state.engineering.cost_allowed!==false)
      throw Error("Poz veya yetki bilgisi uyuşmuyor.");
    setData(state);
    if(!keepEditing){
      const existing=state.latest_revision?.source_current?state.latest_revision.items:
        state.source_inputs;
      setLines(existing.map(x=>({...x,quantity:x.quantity??"",
        unit_price:x.unit_price??""})));
    }
  }
  useEffect(()=>{
    let current=true;
    setBusy(true);setError("");setData(null);
    void call<State>("/analysis").then(result=>{
      if(!current)return;
      if(result.work_item_id!==rowId||result.candidate_code!==position.code||
        result.read_only_source!==true||result.engineering.cost_allowed!==false)
        throw Error("Kaynak ve kayıt uyuşmuyor.");
      setData(result);
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
    if(!data||busy||lines.length<1||editReason.trim().length<10)return;
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
      setNotice("Analiz düzenleme taslağı kaydedildi. Orijinal PDF değiştirilmedi.");
      setEditReason("");
    }catch(e){setError(e instanceof Error?e.message:"Taslak kaydedilemedi.");}
    finally{setBusy(false)}
  }
  async function sendForReview(){
    if(!data||busy||!data.latest_revision?.source_current||!data.engineering.evidence_ready||
      reviewReason.trim().length<10||!ack)return;
    setBusy(true);setError("");setNotice("");
    try{
      const state=await call<{source_fingerprint:string;latest_id:string|null;allowed_actions:string[]}>(
        "/decision-state",undefined,reviewPath);
      if(!state.allowed_actions.includes("submit_for_engineering_review"))
        throw Error("Teknik belge henüz mühendis incelemesine uygun değil.");
      await call("/decisions",{
        action:"submit_for_engineering_review",reason:reviewReason.trim(),
        expected_source_fingerprint:state.source_fingerprint,
        expected_previous_id:state.latest_id,
        request_key:uuid(),confirmation:"I_REVIEWED_SOURCE_EVIDENCE",
      },reviewPath);
      setNotice("Mühendis incelemesine gönderildi. Henüz mühendis onayı verilmedi.");
      setReviewReason("");setAck(false);
    }catch(e){setError(e instanceof Error?e.message:"Mühendis incelemesine iletilemedi.");}
    finally{setBusy(false)}
  }
  async function sign(action:"approve"|"reject"){
    if(!data||busy||!data.engineering.reviewer_eligible||
      !data.latest_revision?.source_current||!ack||reviewReason.trim().length<20)return;
    setBusy(true);setError("");setNotice("");
    try{
      await call("/engineering/signoff",{
        action,reason:reviewReason.trim(),expected_source_fingerprint:data.source_fingerprint,
        expected_analysis_revision_id:data.latest_revision.id,
        expected_previous_signoff_id:data.engineering.review?.id??null,
        request_key:uuid(),attestation:"I_AM_VERIFIED_ENGINEER_AND_REVIEWED_EVIDENCE",
      });
      await reload(true);
      setNotice(action==="approve"?"Yetkili mühendis onayı kaydedildi; kesin maliyet izni ayrıca gerekir.":"Yetkili mühendis ret kararı kaydedildi.");
      setAck(false);setReviewReason("");
    }catch(e){setError(e instanceof Error?e.message:"Mühendis kararı kaydedilemedi.");}
    finally{setBusy(false)}
  }
  return <>
    <details className={styles.projectEvidence} open={editOpen}
      onToggle={e=>setEditOpen(e.currentTarget.open)}>
      <summary>PDF kanıtı ve analiz girdileri · Düzenlenebilir taslak</summary>
      {position.scope_excerpt&&<p><strong>PDF orijinal poz tarifi:</strong> {position.scope_excerpt}</p>}
      <small>Kaynak PDF sayfa {position.source_page??"—"} · Orijinal fiyat: {position.source_price_verified?position.source_price+" TL/"+position.unit:"Doğrulanmadı"} · PDF değiştirilemez.</small>
      {position.analysis_inputs&&<ul>{position.analysis_inputs.map((x,i)=>
        <li key={i}>{x.code} · {x.description}: {x.quantity} {x.unit} × {x.unit_price} TL = {x.amount} TL</li>)}</ul>}
      {position.price_audit&&<p className={styles.priceReconciliation}>
        PDF analiz toplamı: {position.price_audit.inputs_total} TL · Kontrol eki %{position.price_audit.reconciliation_addition_percent}:
        {" "}{position.price_audit.reconciliation_addition} TL · PDF fiyatı: {position.price_audit.pdf_price} TL.
      </p>}
      <div className={styles.a330Edit}>
        <strong>Analiz taslağını düzenle</strong>
        <small>Bu satırlar, PDF'nin üzerine yazılmaz. Eklediğin ve çıkardığın girdiler ayrı, tarihçeli bir teklif/taslak oluşturur.</small>
        {busy&&<p role="status">Kaynaklar yükleniyor…</p>}
        {data?.latest_revision&&<p className={styles.a330Note}>
          Son taslak: v{data.latest_revision.version} · {data.latest_revision.source_current?
            "Kaynak güncel":"Kaynak değişmiş; taslağı tekrar oluştur"}
          {" "}· Deneme tutarı {data.latest_revision.proposed_amount} TL (kontrol formülü %25 ek)
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
        {data&&<label className={styles.a330Label}>Değişiklik gerekçesi
          <textarea rows={2} maxLength={1000} value={editReason} disabled={busy}
            placeholder="Örneğin: Eksik işçilik girdisini ekledim, poz kapsamı kontrol edilecek."
            onChange={e=>setEditReason(e.target.value)} /></label>}
        {data&&<button type="button" disabled={busy||lines.length===0||editReason.trim().length<10}
          onClick={()=>void save()}>Taslak değişikliklerini kaydet</button>}
      </div>
    </details>
    <details className={styles.a330Approval} open={reviewOpen}
      onToggle={e=>setReviewOpen(e.currentTarget.open)}>
      <summary>Mühendis onayı · Kaynaklı teknik inceleme</summary>
      {error&&<p role="alert">{error}</p>}
      {notice&&<p role="status">{notice}</p>}
      {!data&&<p>Mühendis karar bilgisi yüklenemedi veya güncel kayıt bulunmuyor.</p>}
      {data&&<>
        <p><strong>Durum:</strong> {data.engineering.engineering_approved?
          "Yetkili mühendis onayı var":"Mühendis onayı bekliyor"}.
          {" "}Maliyet hesabına aktarma yetkisi bu onaydan bağımsızdır.</p>
        {data.engineering.review&&<p className={styles.a330Note}>Son karar:
          {" "}{data.engineering.review.action==="approve"?"Onay":"Ret"}
          {" "}· {data.engineering.review.source_current?"Güncel kaynak":"Eski kaynak"}
          {" "}· {data.engineering.review.reason}
        </p>}
        {!data.engineering.evidence_ready&&
          <p className={styles.a330Warning}>Şartname–poz teknik ön karşılaştırması tamamlanmadı. Mühendis incelemesine sevk/olumlu onay engellendi.</p>}
        {!data.latest_revision?.source_current&&
          <p className={styles.a330Warning}>Önce yukarıdaki analiz girdilerinin güncel bir taslağını kaydet.</p>}
        <label className={styles.a330Label}>Mühendis inceleme gerekçesi
          <textarea rows={2} maxLength={1000} disabled={busy} value={reviewReason}
            placeholder="Kontrol edilen kapsam, eksikler ve teknik gerekçeyi belirt"
            onChange={e=>setReviewReason(e.target.value)}/></label>
        <label className={styles.a330Label}><input type="checkbox" checked={ack}
          disabled={busy} onChange={e=>setAck(e.target.checked)}/>
          Kaynak PDF'yi, analiz taslağını ve teknik şartnameyi inceledim.
        </label>
        <div className={styles.a330Actions}>
          <button type="button" className="secondary" disabled={busy||!ack||
            !data.engineering.evidence_ready||!data.latest_revision?.source_current||
            reviewReason.trim().length<10} onClick={()=>void sendForReview()}>
            Mühendis incelemesine gönder
          </button>
          <button type="button" disabled={busy||!ack||!data.engineering.reviewer_eligible||
            !data.engineering.evidence_ready||!data.latest_revision?.source_current||
            reviewReason.trim().length<20} onClick={()=>void sign("approve")}>
            Mühendis onayı ver
          </button>
          <button type="button" className="secondary" disabled={busy||!ack||
            !data.engineering.reviewer_eligible||!data.latest_revision?.source_current||
            reviewReason.trim().length<20} onClick={()=>void sign("reject")}>
            Mühendis reddi
          </button>
          <button type="button" className="secondary" disabled={busy}
            onClick={()=>void reload().catch(e=>setError(String(e)))}>Yenile</button>
        </div>
        {!data.engineering.reviewer_eligible&&<small>
          Bu oturumda mühendis onayı verme yetkisi yok. Onay, bağımsız olarak yetkisi doğrulanmış
          mühendis hesabıyla verilmelidir; proje yöneticisi yetkisi yeterli değildir.
        </small>}
      </>}
    </details>
    {(error||notice)&&<p role={error?"alert":"status"} className={error?styles.a330Warning:styles.a330Note}>{error||notice}</p>}
  </>;
}
