"use client";
import {useEffect, useState, type FormEvent} from "react";

type Row = {
  id: string; source_row: number;
  original: {description: string; quantity: string | null; normalized_quantity: string|null; unit: string|null; normalized_unit:string|null; review_required:boolean};
  effective: {description: string; quantity: string|null; unit:string|null; review_required:boolean};
  revision:number; reason:string|null; edited_at:string|null;
};
type History={item_id:string;source_row:number;original:{description:string;quantity:string|null;unit:string|null};revisions:Array<{id:string;revision:number;description:string;quantity:string;unit:string;reason:string;created_at:string}>};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";

async function req<T>(url:string,token:string,method:"GET"|"POST"="GET",body?:object):Promise<T>{
  const response=await fetch(BASE+url,{
    method,cache:"no-store",
    headers:{Authorization:`Bearer ${token}`,...(body?{"Content-Type":"application/json"}:{})},
    body:body?JSON.stringify(body):undefined,
  });
  if(!response.ok){
    const data=await response.json().catch(()=>({detail:`HTTP ${response.status}`}));
    throw new Error(typeof data.detail==="string"?data.detail:`HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export default function CorrectionPanel({project,token,refreshKey,onChange}:{
  project:string; token:string|null; refreshKey:number;onChange:()=>void
}){
  const [rows,setRows]=useState<Row[]>([]);
  const [editing,setEditing]=useState<string|null>(null);
  const [description,setDescription]=useState("");
  const [quantity,setQuantity]=useState("");
  const [unit,setUnit]=useState("");
  const [reason,setReason]=useState("");
  const [history,setHistory]=useState<History|null>(null);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");

  useEffect(()=>{
    if(!token||!project){setRows([]);return;}
    let alive=true;
    setError("");setMessage("");setHistory(null);setEditing(null);
    req<Row[]>(`/api/projects/${project}/m21/items`,token)
      .then(data=>{if(alive)setRows(data);})
      .catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e));});
    return()=>{alive=false;};
  },[token,project,refreshKey]);

  async function reload(){if(token)setRows(await req<Row[]>(`/api/projects/${project}/m21/items`,token));}
  function edit(row:Row){
    setEditing(row.id);setHistory(null);setError("");setMessage("");
    setDescription(row.effective.description);
    setQuantity(row.effective.quantity??row.original.quantity??"");
    setUnit(row.effective.unit??row.original.unit??"");
    setReason("");
  }
  async function save(e:FormEvent){
    e.preventDefault();if(!token||!editing)return;
    const previous=rows.find(row=>row.id===editing);if(!previous)return;
    setBusy(true);setError("");setMessage("");
    try{
      await req(`/api/projects/${project}/m21/items/${editing}/revisions`,token,"POST",{
        description,quantity,unit,reason,expected_revision:previous.revision
      });
      await reload();setEditing(null);
      setMessage("Yeni metraj revizyonu kaydedildi. Orijinal Excel değişmedi. Şimdi yeniden eşleştirme yapılmalı.");
      onChange();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function showHistory(id:string){
    if(!token)return;setError("");setBusy(true);setEditing(null);
    try{setHistory(await req<History>(`/api/projects/${project}/m21/items/${id}/history`,token));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function rematch(){
    if(!token)return;
    setError("");setBusy(true);setMessage("");
    try{
      const response=await req<{recomputed_item_count:number;copied_item_count:number}>(`/api/projects/${project}/m21/rematch`,token,"POST");
      setMessage(`${response.recomputed_item_count} değişen kalem yeniden hesaplandı; ${response.copied_item_count} değişmeyen kalemin önceki adayları korundu. Eski onaylar tarihçede kaldı, bu yeni çalıştırmada yeniden onay gerekiyor.`);
      onChange();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }

  return <section className="card stack" aria-label="M2.1 Metraj düzeltme ve revizyon">
    <div className="flex between">
      <div><h2>M2.1 · Metraj düzeltme ve revizyon</h2>
        <p className="hint">Kaynak Excel aynen kalır. Değişiklikler uzman gerekçesiyle yeni revizyon olarak saklanır.</p></div>
      <span className="tag">Denetlenebilir revizyon</span>
    </div>
    {error&&<div className="error" role="alert">{error}</div>}
    {message&&<div className="success" role="status">{message}</div>}
    {rows.length===0&&<div className="empty">Önce Excel metrajı kaydedin.</div>}
    {rows.length>0&&<><div className="table-scroll"><table>
      <thead><tr><th>Satır</th><th>Güncel imalat</th><th>Miktar</th><th>Birim</th><th>Sürüm</th><th>İşlem</th></tr></thead>
      <tbody>{rows.map(row=><tr key={row.id}><td>{row.source_row}</td>
        <td>{row.effective.description}</td><td className="number">{row.effective.quantity??"Belirsiz"}</td>
        <td>{row.effective.unit??"Belirsiz"}</td>
        <td>{row.revision===0?"Orijinal":`R${row.revision}`}{row.effective.review_required&&<span className="warning"> · Kontrol</span>}</td>
        <td><div className="flex">
          <button className="secondary" disabled={busy} onClick={()=>edit(row)}>Düzelt</button>
          <button className="ghost" disabled={busy} onClick={()=>showHistory(row.id)}>Geçmiş</button>
        </div></td></tr>)}</tbody>
    </table></div>
    <div className="flex between">
      <p className="hint">Mühendis onayı otomatik verilmez. Belirsiz \`1.234\` değeri açıkça \`1234\` veya \`1,2340\` biçiminde doğrulanmalıdır.</p>
      <button disabled={busy} onClick={rematch}>Değişen kalemleri yeniden eşleştir</button>
    </div></>}
    {editing&&<form className="stack m21-editor" onSubmit={save}>
      <h2>İmalat düzeltmesi</h2>
      <label>İmalat açıklaması<input required minLength={3} maxLength={10000} value={description} onChange={e=>setDescription(e.target.value)}/></label>
      <div className="fields">
        <label>Doğrulanmış miktar<input required value={quantity} onChange={e=>setQuantity(e.target.value)} placeholder="1234"/></label>
        <label>Ölçü birimi<select value={unit} onChange={e=>setUnit(e.target.value)}>
          {!["m²","m³","m","adet","kg","ton","set","takım"].includes(unit)&&<option value={unit}>{unit||"Birim seçin"}</option>}
          {["m²","m³","m","adet","kg","ton","set","takım"].map(u=><option key={u} value={u}>{u}</option>)}
        </select></label>
      </div>
      <label>Düzeltme gerekçesi (en az 8 karakter)
        <input required minLength={8} maxLength={500} value={reason} onChange={e=>setReason(e.target.value)} placeholder="Ölçü çiziminden kontrol edildi"/></label>
      <p className="notice">Bu işlem yeni bir sürüm oluşturur, kaynak satırı silmez. Miktarı veya birimi teknik projeden doğrulamadan değiştirmeyin.</p>
      <div className="flex"><button disabled={busy}>Revizyonu kaydet</button>
      <button className="secondary" type="button" onClick={()=>setEditing(null)}>Vazgeç</button></div>
    </form>}
    {history&&<div className="m21-editor stack">
      <div className="flex between"><h2>Satır #{history.source_row} · Revizyon geçmişi</h2>
        <button className="ghost" onClick={()=>setHistory(null)}>Kapat</button></div>
      <p className="hint">Orijinal: {history.original.description} · {history.original.quantity||"—"} {history.original.unit||"—"}</p>
      {history.revisions.length===0?<p>Henüz düzeltme kaydı yok.</p>:history.revisions.map(r=><div key={r.id} className="match-candidate">
        <strong>R{r.revision} — {r.description}</strong>
        <p className="hint">{r.quantity} {r.unit} · Gerekçe: {r.reason} · {new Date(r.created_at).toLocaleString("tr-TR")}</p>
      </div>)}
    </div>}
  </section>;
}
