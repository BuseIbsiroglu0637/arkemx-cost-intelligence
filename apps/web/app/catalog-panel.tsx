"use client";
import {useEffect,useState} from "react";

type Mapping = Record<"code"|"description"|"unit"|"price",string>;
type Inspection={headers:string[];suggested_mapping:Record<keyof Mapping,string|null>;data_rows:number};
type CatalogRow={code:string;description:string;unit:string;price:string|null};
type Preview={sha256:string;row_count:number;preview:CatalogRow[];status:string};
type Catalog={id:string;version_id:string;institution:string;year:number;period:string;row_count:number;
 sha256:string;filename:string;status:"pending"|"approved"|"rejected";approved:boolean;
 source_url:string|null;reviewed_by:string|null;reviewed_at:string|null};
const BASE=process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000";

async function get<T>(url:string,token:string,method:"GET"|"POST"="GET",body?:FormData|object):Promise<T>{
 const options:RequestInit={method,headers:{Authorization:`Bearer ${token}`},cache:"no-store"};
 if(body instanceof FormData)options.body=body;
 else if(body){options.body=JSON.stringify(body);(options.headers as Record<string,string>)["Content-Type"]="application/json";}
 const res=await fetch(BASE+url,options);
 if(!res.ok){
  const data=await res.json().catch(()=>({detail:`HTTP ${res.status}`}));
  throw new Error(typeof data.detail==="string"?data.detail:`HTTP ${res.status}`);
 }
 return res.json() as Promise<T>;
}
const fields: {field:keyof Mapping;label:string}[]=[
 {field:"code",label:"Poz kodu"},{field:"description",label:"Poz tarifi"},
 {field:"unit",label:"Birim"},{field:"price",label:"Birim fiyat (isteğe bağlı)"},
];
export default function CatalogPanel({token,project,onMatch}:{token:string|null;project:string;onMatch:()=>void}){
 const [file,setFile]=useState<File|null>(null);
 const [institution,setInstitution]=useState("CSB");
 const [year,setYear]=useState(2026);const [period,setPeriod]=useState("2026-YILLIK");
 const [url,setUrl]=useState("");
 const [inspection,setInspection]=useState<Inspection|null>(null);
 const [mapping,setMapping]=useState<Mapping>({code:"",description:"",unit:"",price:""});
 const [preview,setPreview]=useState<Preview|null>(null);
 const [catalogs,setCatalogs]=useState<Catalog[]>([]);
 const [chosen,setChosen]=useState("");
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");const [message,setMessage]=useState("");
 useEffect(()=>{
  if(!token){setCatalogs([]);return;}
  let active=true;
  get<Catalog[]>("/api/m3/imports",token).then(res=>{if(active)setCatalogs(res);}).catch(()=>{});
  return()=>{active=false;};
 },[token]);
 async function act<T>(task:()=>Promise<T>,success:(result:T)=>void|Promise<void>){
  setBusy(true);setError("");setMessage("");
  try{const result=await task();await success(result);}catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{setBusy(false);}
 }
 const form=()=>{
  const f=new FormData();
  if(file)f.append("file",file);
  f.append("columns",JSON.stringify(mapping));
  return f;
 };
 function resetFile(next:File|null){setFile(next);setInspection(null);setPreview(null);}
 async function inspect(){
  if(!file||!token)return;
  const f=new FormData();f.append("file",file);
  await act(()=>get<Inspection>("/api/m3/inspect",token,"POST",f),res=>{
   setInspection(res);setMapping({
    code:res.suggested_mapping.code||"",description:res.suggested_mapping.description||"",
    unit:res.suggested_mapping.unit||"",price:res.suggested_mapping.price||""});
   setMessage("Başlıkları kontrol edip önizleme oluşturun.");
  });
 }
 async function showPreview(){
  if(!token||!file)return;
  await act(()=>get<Preview>("/api/m3/preview",token,"POST",form()),res=>{
   setPreview(res);setMessage(`${res.row_count} poz kontrol edildi; henüz veritabanına kaydedilmedi.`);
  });
 }
 async function persist(){
  if(!token||!file||!preview)return;
  const f=form();f.append("institution",institution);f.append("year",String(year));
  f.append("period",period);if(url.trim())f.append("source_url",url.trim());
  await act(()=>get<Catalog>("/api/m3/imports",token,"POST",f),async res=>{
   const updated=await get<Catalog[]>("/api/m3/imports",token);
   setCatalogs(updated);setChosen(res.version_id);setPreview(null);setInspection(null);setFile(null);
   setMessage("Katalog kaydedildi: BEKLEMEDE. Operatör izin onayı olmadan eşleştirme yapılamaz.");
  });
 }
 async function match(){
  if(!token||!chosen)return;
  await act(()=>get<{candidate_count:number;row_count:number}>(`/api/m3/projects/${project}/run`,
   token,"POST",{version_id:chosen,use_local_ollama:false}),res=>{
    onMatch();setMessage(`${res.row_count} satır, ${res.candidate_count} aday; gerçek katalog kullanımı için izin kaydı mevcut. Teknik eşleşmeler ayrıca mühendis onayı gerektirir.`);
   });
 }
 const validMap=!!(mapping.code&&mapping.description&&mapping.unit&&new Set(
  [mapping.code,mapping.description,mapping.unit,...(mapping.price?[mapping.price]:[])]).size===(mapping.price?4:3));
 return <section className="card stack" aria-label="M3 poz katalog yönetimi">
  <div className="flex between"><div><h2>M3 · Poz katalog ve kaynak yönetimi</h2>
   <p className="hint">CSV/XLSX • kurum • yıl/dönem • SHA-256 • hak sahipliği denetimi</p></div>
   <span className="tag">Kaynak kontrollü</span></div>
  <p className="notice">Resmî katalogları yalnızca geçerli kullanım ve veri işleme hakkın varsa yükle.
   Web hesabı kataloglara ticari izin veremez. Kataloglar önce beklemeye alınır, operatörün
   bağımsız hak incelemesi sonrası eşleştirmeye açılır. Fiyatlar henüz maliyet hesabında kullanılmaz.</p>
  {error&&<div role="alert" className="error">{error}</div>}
  {message&&<div role="status" className="success">{message}</div>}
  <div className="fields">
   <label>Kurum<select value={institution} onChange={e=>setInstitution(e.target.value)}>
    <option value="CSB">ÇŞİDB</option><option value="DSI">DSİ</option>
    <option value="KGM">KGM</option><option value="ILBANK">İLBANK</option>
    <option value="OTHER">Diğer</option>
   </select></label>
   <label>Yıl<input type="number" min={2000} max={2100} value={year} onChange={e=>setYear(Number(e.target.value))}/></label>
   <label>Dönem<input maxLength={40} value={period} onChange={e=>setPeriod(e.target.value)}/></label>
  </div>
  <label>Kaynak adresi (isteğe bağlı HTTPS)<input value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://kaynak.example/..." /></label>
  <label>Katalog dosyası (CSV veya XLSX, en fazla 5 MB)
   <input type="file" accept=".csv,.xlsx" onChange={e=>resetFile(e.target.files?.[0]||null)}/>
  </label>
  <div className="flex"><button disabled={!file||busy} className="secondary" onClick={inspect}>1. Başlıkları incele</button></div>
  {inspection&&<><p className="hint">Dosyada {inspection.data_rows} satır bulundu. Sütun eşleştirmesini doğrula:</p>
   <div className="fields">{fields.map(({field,label})=><label key={field}>{label}
    <select value={mapping[field]} onChange={e=>{setMapping({...mapping,[field]:e.target.value});setPreview(null);}}>
     <option value="">Sütun seçin</option>{inspection.headers.map(h=><option value={h} key={h}>{h}</option>)}
    </select></label>)}</div>
   <button className="secondary" disabled={!validMap||busy} onClick={showPreview}>2. Pozları önizle</button>
  </>}
  {preview&&<><div className="flex"><span className="tag">{preview.row_count} satır</span>
   <span className="hint">SHA-256: {preview.sha256.slice(0,16)}…</span></div>
   <div className="table-scroll"><table><thead><tr><th>Kod</th><th>Tarif</th><th>Birim</th><th>Fiyat (veri)</th></tr></thead><tbody>
    {preview.preview.map(row=><tr key={row.code}><td>{row.code}</td><td>{row.description}</td>
     <td>{row.unit}</td><td>{row.price??"—"}</td></tr>)}
   </tbody></table></div>
   <button disabled={busy||!period.trim()||year<2000||year>2100} onClick={persist}>3. Kataloğu beklemede kaydet</button>
  </>}
  <h2>Yüklenen kataloglar</h2>
  {catalogs.length===0?<div className="empty">Henüz içe aktarılmış katalog yok.</div>:
   <div className="table-scroll"><table><thead><tr><th>Kurum</th><th>Dönem</th><th>Poz</th><th>Hak incelemesi</th><th>Eşleştirme</th></tr></thead>
    <tbody>{catalogs.map(cat=><tr key={cat.id}><td>{cat.institution}</td><td>{cat.year} / {cat.period}</td><td>{cat.row_count}</td>
     <td>{cat.approved?"Operatör onaylı":cat.status==="pending"?"Beklemede":"Reddedildi / İptal edildi"}</td>
     <td><label><input type="radio" name="m3cat" checked={chosen===cat.version_id} onChange={()=>setChosen(cat.version_id)}
       disabled={!cat.approved}/>{cat.approved?"Seç":"Kilitli"}</label></td></tr>)}
    </tbody></table></div>}
  <button disabled={busy||!chosen||!catalogs.find(cat=>cat.version_id===chosen)?.approved||!project} onClick={match}>
   4. Onaylı katalogla poz eşleştir
  </button>
  <p className="hint">Katalog izin belgesi yalnızca sunucu yöneticisi tarafından, yerel operatör komutuyla incelenip kayda alınır. DEMO katalogları M2'de kalır.</p>
 </section>;
