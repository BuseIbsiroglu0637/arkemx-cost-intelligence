"use client";
import {useState} from "react";
type Action = "request_information"|"reject_candidate"|"submit_for_engineering_review";
type Event = {id:string;action:Action;reason:string;created_at:string;created_by_id:string;source_current?:boolean;engineering_approved:false;cost_allowed:false;approval_allowed:false};
type Data = {work_item_id:string;source_fingerprint:string;latest_id:string|null;allowed_actions:Action[];events:Event[];engineering_approved:false;cost_allowed:false;approval_allowed:false};
const names:Record<Action,string> = {request_information:"Eksik bilgi iste",reject_candidate:"Poz adayını reddet",submit_for_engineering_review:"Mühendis incelemesine ilet"};
const API=(process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000").replace(/\/$/,"");
export default function HandoffDecisionPanel({projectId,importId,rowId}:{projectId:string;importId:string;rowId:string}){
  const [open,setOpen]=useState(false);
  const [data,setData]=useState<Data|null>(null);
  const [action,setAction]=useState<Action>("request_information");
  const [reason,setReason]=useState("");
  const [ack,setAck]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const path=`/api/projects/${encodeURIComponent(projectId)}/a327/imports/${encodeURIComponent(importId)}/items/${encodeURIComponent(rowId)}`;
  async function api<T>(suffix:string,body?:unknown):Promise<T>{
    const token=sessionStorage.getItem("arkemx_dev_token");
    if(!token)throw Error("Oturum bulunamadı.");
    const res=await fetch(API+path+suffix,{method:body?"POST":"GET",cache:"no-store",headers:{Authorization:`Bearer ${token}`,...(body?{"Content-Type":"application/json"}:{})},...(body?{body:JSON.stringify(body)}:{})});
    if(!res.ok)throw Error(res.status===409?"Kaynak veya karar geçmişi değişti. Kaydı yenileyip yeniden incele.":`İşlem başarısız (HTTP ${res.status}).`);
    return res.json() as Promise<T>;
  }
  async function reload(){
    setBusy(true);setError("");
    try{
      const x=await api<Data>("/decision-state");
      if(x.work_item_id!==rowId||x.approval_allowed!==false||x.engineering_approved!==false||x.cost_allowed!==false||x.events.some(e=>e.approval_allowed!==false||e.engineering_approved!==false||e.cost_allowed!==false))throw Error("Karar güvenlik doğrulaması başarısız.");
      setData(x);setAction("request_information");setReason("");setAck(false);
    }catch(e){setError(e instanceof Error?e.message:"Kayıt okunamadı.");setData(null)}
    finally{setBusy(false)}
  }
  async function save(){
    if(!data||busy||!ack||!data.allowed_actions.includes(action))return;
    setBusy(true);setError("");setNotice("");
    try{
      const x=await api<Event>("/decisions",{action,reason:reason.trim(),expected_source_fingerprint:data.source_fingerprint,expected_previous_id:data.latest_id,request_key:crypto.randomUUID(),confirmation:"I_REVIEWED_SOURCE_EVIDENCE"});
      if(x.engineering_approved!==false||x.cost_allowed!==false||x.approval_allowed!==false)throw Error("Beklenmeyen onay alanı.");
      setNotice("İnceleme notu kaydedildi. Mühendis onayı verilmedi.");
      const refreshed=await api<Data>("/decision-state");
      setData(refreshed);setReason("");setAck(false);setAction("request_information");
    }catch(e){setError(e instanceof Error?e.message:"Kayıt başarısız")}
    finally{setBusy(false)}
  }
  return <div className="a327-decision">
    <button type="button" className="secondary" disabled={busy} onClick={()=>{if(open){setOpen(false);setData(null)}else{setOpen(true);void reload()}}}>{open?"Kapat":"Karar notu / geçmiş"}</button>
    {open&&<div style={{display:"grid",gap:8,padding:"10px 0"}}>
      <strong>Kaynaklı inceleme kararı</strong>
      <small>Karar notu, bilgi isteği veya mühendise sevk kaydedilir; teknik onay ve maliyet kapalıdır.</small>
      {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
      {data&&<>
        <label>İşlem <select value={action} disabled={busy} onChange={e=>setAction(e.target.value as Action)}>{data.allowed_actions.map(x=><option value={x} key={x}>{names[x]}</option>)}</select></label>
        <label>Gerekçe (isteğe bağlı) <textarea rows={2} maxLength={1000} disabled={busy} value={reason} onChange={e=>setReason(e.target.value)} placeholder="Hangi bilgi eksik veya neden inceleme gerekiyor?"/></label>
        <label><input type="checkbox" checked={ack} disabled={busy} onChange={e=>setAck(e.target.checked)}/> Kaynak kanıtını inceledim.</label>
        <button type="button" disabled={busy||!ack||!data.allowed_actions.includes(action)} onClick={()=>void save()}>İnceleme kararını kaydet</button>
        <button type="button" className="secondary" disabled={busy} onClick={()=>void reload()}>Kayıtları yenile</button>
        {data.events.length>0&&<div><strong>Karar geçmişi</strong><ul>{data.events.map(x=><li key={x.id}>{names[x.action]} · {new Date(x.created_at).toLocaleString("tr-TR")} · {x.source_current===false?"Eski kaynak":"Güncel kaynak"} — {x.reason}</li>)}</ul></div>}
      </>}
    </div>}
  </div>;
}
