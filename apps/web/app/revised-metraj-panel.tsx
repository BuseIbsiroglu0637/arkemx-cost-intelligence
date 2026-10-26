"use client";
import {useEffect,useState} from "react";

type Estimate = {id:string;title:string;total:string;created_at:string};
type Inspection = {headers:string[];mapping:Record<string,string|null>;sheets:string[];selected_sheet:string;header_row:number};
type Change = {source_row:number;status:string;old_description:string|null;new_description:string|null;
 old_quantity:string|null;new_quantity:string|null;old_unit:string|null;new_unit:string|null;
 indicative_delta:string|null;requires_engineer_review:boolean;issues:string[]};
type Preview = {baseline_import_id:string;baseline_sha256:string;revision_sha256:string;
 baseline_filename:string;latest_import_id:string;baseline_is_current:boolean;active_bulk_job:boolean;apply_allowed:boolean;
 revision_sheet:string;row_count_old:number;row_count_new:number;
 review_count_new:number;baseline_estimate_id:string|null;baseline_estimate_total:string|null;
 changed_rows:number;known_quantity_effect:string;fully_attributable_quantity_effect:string|null;
 unknown_cost_effect:boolean;approvals_transferred:boolean;counts:Record<string,number>;
 items:Change[]};
type History = {id:string;reason:string;created_at:string;baseline_sha256:string;
 revision_sha256:string;changed_rows:number;counts:Record<string,number>};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";
const statusText:Record<string,string>={
 unchanged:"Değişmedi",quantity_changed:"Miktar değişti",
 identity_or_scope_changed:"Tarif / kapsam veya satır kimliği belirsiz",
 duplicate_identity_review:"Tekrarlı imalat — kimlik kontrolü",
 needs_data_review:"Veri kontrolü gerekli",added:"Yeni satır",removed:"Çıkarılan satır"
};
async function api<T>(path:string,token:string,body?:FormData):Promise<T>{
 const r=await fetch(BASE+path,{method:body?"POST":"GET",cache:"no-store",
  headers:{Authorization:"Bearer "+token},body});
 if(!r.ok){const e=await r.json().catch(()=>({detail:"HTTP "+r.status}));
  throw new Error(typeof e.detail==="string"?e.detail:"HTTP "+r.status);}
 return r.json() as Promise<T>;
}
const format=(v:string)=>new Intl.NumberFormat("tr-TR",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(v))+" TL";
export default function RevisedMetrajPanel({token,project,onApplied}:{
 token:string|null;project:string;onApplied:()=>Promise<void> | void
}){
 const [file,setFile]=useState<File|null>(null);
 const [inspection,setInspection]=useState<Inspection|null>(null);
 const [sheet,setSheet]=useState("");
 const [headerRow,setHeaderRow]=useState(1);
 const [columns,setColumns]=useState<Record<string,string>>({description:"",quantity:"",unit:""});
 const [estimates,setEstimates]=useState<Estimate[]>([]);
 const [estimateId,setEstimateId]=useState("");
 const [preview,setPreview]=useState<Preview|null>(null);
 const [history,setHistory]=useState<History[]>([]);
 const [page,setPage]=useState(1);
 const [reason,setReason]=useState("");
 const [accepted,setAccepted]=useState(false);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [notice,setNotice]=useState("");
 const base="/api/projects/"+project+"/m52";
 useEffect(()=>{
  setFile(null);setInspection(null);setPreview(null);setError("");setNotice("");
  setAccepted(false);setEstimateId("");setHistory([]);setEstimates([]);
  if(!token||!project)return;
  let live=true;
  Promise.allSettled([
   api<Estimate[]>("/api/projects/"+project+"/m5/estimates",token),
   api<History[]>(base+"/history",token)
  ]).then(r=>{
   if(!live)return;
   if(r[0].status==="fulfilled")setEstimates(r[0].value);
   if(r[1].status==="fulfilled")setHistory(r[1].value);
  });
  return()=>{live=false;};
 },[token,project,base]);
 const form=()=>{
  const f=new FormData();
  if(file)f.append("file",file);
  if(sheet)f.append("sheet",sheet);
  f.append("header_row",String(headerRow));
  for(const name of ["description","quantity","unit"]){
   if(columns[name])f.append(name+"_column",columns[name]);
  }
  if(estimateId)f.append("estimate_id",estimateId);
  return f;
 };
 async function inspect(selectedSheet?:string,selectedRow?:number){
  if(!token||!file)return;
  setBusy(true);setError("");setPreview(null);setNotice("");setAccepted(false);
  try{
   const f=new FormData();f.append("file",file);
   if(selectedSheet)f.append("sheet",selectedSheet);
   f.append("header_row",String(selectedRow??headerRow));
   const result=await api<Inspection>("/api/imports/inspect",token,f);
   setInspection(result);setSheet(result.selected_sheet);setHeaderRow(result.header_row);
   setColumns({description:result.mapping.description??"",
    quantity:result.mapping.quantity??"",unit:result.mapping.unit??""});
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 async function check(){
  if(!token||!file)return;
  setBusy(true);setError("");setPreview(null);setNotice("");setAccepted(false);
  try{const data=await api<Preview>(base+"/preview",token,form());setPreview(data);setPage(1);}
  catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 async function apply(){
  if(!token||!preview||!file||!accepted||reason.trim().length<10)return;
  setBusy(true);setError("");setNotice("");
  try{
   const f=form();
   f.append("expected_baseline_id",preview.baseline_import_id);
   f.append("expected_revision_sha256",preview.revision_sha256);
   f.append("reason",reason.trim());
   const result=await api<{import_id:string;changed_rows:number}>(base+"/apply",token,f);
   setPreview(null);setFile(null);setInspection(null);setAccepted(false);setReason("");
   setNotice("Yeni metraj "+result.changed_rows+" değişiklikle kaydedildi. M4.3'te yeni teknik analiz ve M4.2'de yeniden insan onayı gerekir.");
   const updated=await api<History[]>(base+"/history",token);setHistory(updated);
   await onApplied();
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 const mapped=Boolean(columns.description&&columns.quantity&&columns.unit&&headerRow>=1&&headerRow<=30);
 const rows=preview?.items.slice((page-1)*20,page*20)??[];
 const pages=Math.ceil((preview?.items.length??0)/20);
 return <details className="card m52-panel">
  <summary>M5.2 · Revize Excel metrajı karşılaştır</summary>
  <div className="m52-body stack">
   <p className="hint">İlk kontrol yalnızca önizlemedir. İmalat kapsamı, satır sırası ve poz kimliği
     belirsizse otomatik eşleştirme yapılmaz. Eski Excel, kaynak SHA-256 kayıtları ve maliyet taslakları korunur.</p>
   {error&&<p role="alert" className="error">{error}</p>}
   {notice&&<p role="status" className="success">{notice}</p>}
   <label>Revize mimari metraj dosyası (.xlsx, en fazla 10 MB)
    <input type="file" accept=".xlsx" onChange={e=>{
     setFile(e.target.files?.[0]??null);setInspection(null);setPreview(null);
     setAccepted(false);setNotice("");setError("");}}/>
   </label>
   <button type="button" className="secondary" disabled={busy||!file} onClick={()=>inspect()}>
    1. Revize dosyanın başlıklarını incele</button>
   {inspection&&<>
    <div className="m52-grid">
     <label>Sayfa<select value={sheet} onChange={e=>inspect(e.target.value)}>
      {inspection.sheets.map(s=><option key={s} value={s}>{s}</option>)}</select></label>
     <label>Başlık satırı
      <input type="number" min={1} max={30} value={headerRow}
       onChange={e=>{setHeaderRow(Number(e.target.value));setPreview(null);}}/></label>
     <button type="button" className="secondary" disabled={busy||headerRow<1||headerRow>30}
      onClick={()=>inspect(sheet,headerRow)}>Başlıkları yenile</button>
    </div>
    <div className="m52-grid">
     {(["description","quantity","unit"] as const).map(field=><label key={field}>
      {({description:"İmalat açıklaması",quantity:"Miktar",unit:"Birim"})[field]}
      <select value={columns[field]} onChange={e=>{
       setColumns(v=>({...v,[field]:e.target.value}));setPreview(null);}}>
       <option value="">Sütun seç</option>
       {inspection.headers.map(h=><option key={h} value={h}>{h}</option>)}
      </select></label>)}
    </div>
    <div className="m52-grid">
     <label>Eski maliyet taslağı (isteğe bağlı)
      <select value={estimateId} onChange={e=>{setEstimateId(e.target.value);setPreview(null);}}>
       <option value="">Fiyat olmadan yalnızca metraj değişimini göster</option>
       {estimates.map(x=><option key={x.id} value={x.id}>{x.title} · {new Date(x.created_at).toLocaleString("tr-TR")}</option>)}
      </select></label>
    </div>
    <button type="button" disabled={!file||!mapped||busy} onClick={check}>
     2. Eski ve yeni Excel'i karşılaştır</button>
   </>}
   {preview&&<section className="stack">
    {!preview.baseline_is_current&&<p className="warning" role="status">
      Tarihî karşılaştırma: kaynak olarak seçilen eski maliyet taslağının
      { " " }<strong>{preview.baseline_filename}</strong> Excel'i kullanıldı.
      Projede başka bir güncel metraj var. Bu önizleme salt okunurdur; yeni
      revizyon kaydı oluşturulamaz. Kaynak metrajlar ve onaylar değişmeyecek.
    </p>}
    {preview.active_bulk_job&&<p className="warning" role="status">
      Projede tamamlanmamış M4.3 işi bulunuyor. Worker'ı başlatmayın;
      bu iş değerlendirilmeden yeni revizyon kaydı oluşturulamaz.
    </p>}
    <div className="m52-summary">
     <div><small>Önceki / yeni metraj</small><strong>{preview.row_count_old} / {preview.row_count_new}</strong></div>
     <div><small>Değişiklik</small><strong>{preview.changed_rows}</strong></div>
     <div><small>Kontrol gerektiren yeni satır</small><strong>{preview.review_count_new}</strong></div>
     <div><small>Bilinen miktar etkisi</small><strong>{format(preview.known_quantity_effect)}</strong></div>
    </div>
    {preview.unknown_cost_effect
     ?<p className="warning" role="status">Toplam maliyet değişimi hesaplanamaz: eklenen, kapsamı belirsiz
      veya fiyatı doğrulanmamış satırlar mevcut. Gösterilen miktar etkisi yalnızca hesaplanabilen kısımdır.</p>
     :<p className="hint">Tarihî manuel fiyatlarla hesaplanan indikatif miktar etkisi:
      {format(preview.known_quantity_effect)}. Nihai maliyet değildir.</p>}
    <p className="hint">Eski Excel SHA-256: <code>{preview.baseline_sha256}</code></p>
    <p className="hint">Revize Excel SHA-256: <code>{preview.revision_sha256}</code></p>
    <div className="table-scroll"><table><thead><tr>
     <th>Satır</th><th>Önceki imalat</th><th>Yeni imalat</th><th>Durum</th><th>Miktar</th><th>Yaklaşık etki</th>
    </tr></thead><tbody>{rows.map(row=><tr key={row.source_row}>
     <td>{row.source_row}</td><td>{row.old_description??"—"}</td>
     <td>{row.new_description??"—"}</td>
     <td><strong>{statusText[row.status]??row.status}</strong>
      {row.issues.length>0&&<div className="warning">{row.issues.join(", ")}</div>}</td>
     <td>{row.old_quantity??"—"} {row.old_unit??""} → {row.new_quantity??"—"} {row.new_unit??""}</td>
     <td>{row.indicative_delta===null?"Belirsiz":format(row.indicative_delta)}</td>
    </tr>)}</tbody></table></div>
    {pages>1&&<div className="flex between">
     <button type="button" className="secondary" disabled={page<=1} onClick={()=>setPage(v=>v-1)}>Önceki</button>
     <span className="hint">Sayfa {page}/{pages}</span>
     <button type="button" className="secondary" disabled={page>=pages} onClick={()=>setPage(v=>v+1)}>Sonraki</button>
    </div>}
    <div className="m52-apply stack">
     <h3>3. Kontrollü yeni metraj kaydı</h3>
     <p className="warning">Bu işlem yeni bir değiştirilemez Excel içe aktarımı oluşturur.
      Önceki teknik onaylar yeni dosyada geçerli olmaz. Tekrar M4.3 ve M4.2 gerekecektir.</p>
     <label>Revizyon gerekçesi (en az 10 karakter)
      <input maxLength={500} value={reason} onChange={e=>setReason(e.target.value)}
       placeholder="Örn. Mimar tarafından gönderilen R02 metraj revizyonu"/></label>
     <label className="m52-check"><input type="checkbox" checked={accepted}
      onChange={e=>setAccepted(e.target.checked)}/>
      Kaynakları ve değişiklikleri inceledim; yeni metrajı projeye kaydetmek istiyorum.</label>
     <button type="button" disabled={!preview.apply_allowed||!accepted||!file||busy||reason.trim().length<10||
       preview.changed_rows===0} onClick={apply}>Yeni revizyonu kaydet ve teknik onayları sıfırdan başlat</button>
     {!preview.apply_allowed&&<p className="hint" role="status">Bu karşılaştırmada kayıt kapalı:
       {preview.baseline_is_current?"bekleyen M4.3 işi var":"seçilen maliyet taslağı tarihî metraja ait"}.
       Önizleme ve tahmini maliyet etkisi incelenebilir.</p>}
    </div>
   </section>}
   {history.length>0&&<div className="m52-history stack">
    <h3>Kaydedilen Excel revizyonları</h3>
    {history.slice(0,10).map(h=><div key={h.id}>
     <strong>{new Date(h.created_at).toLocaleString("tr-TR")} · {h.changed_rows} değişen satır</strong>
     <p className="hint">{h.reason}</p>
     <p className="hint">Yeni dosya SHA-256: <code>{h.revision_sha256}</code></p>
    </div>)}
   </div>}
  </div>
 </details>;
}
