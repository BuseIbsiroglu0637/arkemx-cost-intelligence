"use client";

import {useCallback, useEffect, useState, type FormEvent} from "react";
import MatchPanel from "./match-panel";
import CorrectionPanel from "./correction-panel";
import CatalogPanel from "./catalog-panel";
import TechnicalPanel from "./technical-panel";
import EngineerReviewPanel from "./engineer-review-panel";
import BulkPanel from "./bulk-panel";

type Project = {id: string; name: string; created_at: string};
type Row = {source_row: number; description: string; quantity: string | null; unit: string | null; issues: string[]; review_required: boolean};
type Inspection = {headers: string[]; mapping: Record<string, string|null>; sheets: string[]; selected_sheet: string; header_row: number};
type Preview = {row_count: number; review_count: number; items: Row[]; mapping: Record<string,string>; sheet: string};
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(endpoint: string, token: string|null, method="GET", body?: object|FormData): Promise<T> {
  const headers: Record<string,string> = {};
  if(token) headers.Authorization = `Bearer ${token}`;
  if (body && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API}${endpoint}`, {method,headers,body:body ? (body instanceof FormData ? body : JSON.stringify(body)) : undefined,cache:"no-store"});
  if(!response.ok) {
    let message = `HTTP ${response.status}`;
    try { const json = await response.json(); message = typeof json.detail === "string" ? json.detail : message; } catch {}
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export default function Home() {
  const [token,setToken] = useState<string|null>(null);
  const [mode,setMode] = useState<"login"|"register">("register");
  const [email,setEmail] = useState(""); const [password,setPassword] = useState(""); const [org,setOrg] = useState("");
  const [projects,setProjects] = useState<Project[]>([]); const [project,setProject] = useState<string>("");
  const [projectName,setProjectName] = useState(""); const [file,setFile] = useState<File|null>(null);
  const [inspection,setInspection] = useState<Inspection|null>(null); const [selectedSheet,setSelectedSheet] = useState(""); const [headerRow,setHeaderRow] = useState(1); const [preview,setPreview] = useState<Preview|null>(null);
  const [mapping,setMapping] = useState<Record<string,string>>({description:"",quantity:"",unit:""});
  const [items,setItems] = useState<Row[]>([]); const [message,setMessage] = useState(""); const [error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const [revisionTick,setRevisionTick] = useState(0);
  const [showLegacy,setShowLegacy] = useState(false);
  const loadProjects = useCallback(async (t:string) => {setProjects(await request<Project[]>("/api/projects",t));},[]);
  useEffect(()=>{const stored = sessionStorage.getItem("arkemx_dev_token"); if(stored){setToken(stored);loadProjects(stored).catch(()=>{sessionStorage.removeItem("arkemx_dev_token");setToken(null);});}},[loadProjects]);
  const handleError = (e:unknown)=>setError(e instanceof Error?e.message:"Beklenmeyen hata");

  async function auth(e:FormEvent) {e.preventDefault();setBusy(true);setError("");try{
    const endpoint = mode === "register"? "/api/auth/register":"/api/auth/login";
    const body = mode === "register" ? {organization_name:org,email,password}:{email,password};
    const result = await request<{access_token:string}>(endpoint,null,"POST",body);
    sessionStorage.setItem("arkemx_dev_token",result.access_token);setToken(result.access_token);
    await loadProjects(result.access_token);setMessage("Oturum açıldı.");
  }catch(e){handleError(e);}finally{setBusy(false);}}
  function logout(){sessionStorage.removeItem("arkemx_dev_token");setToken(null);setProjects([]);setProject("");setItems([]);setPreview(null);}

  async function createProject(e:FormEvent){e.preventDefault();if(!token)return;setBusy(true);setError("");try{
    const p = await request<Project>("/api/projects",token,"POST",{name:projectName});
    await loadProjects(token);setProject(p.id);setProjectName("");setItems([]);setMessage("Proje oluşturuldu.");
  }catch(e){handleError(e);}finally{setBusy(false);}}

  async function chooseProject(id:string){setProject(id);setInspection(null);setPreview(null);setFile(null);setError("");setMessage("");
    if(token){try{setItems(await request<Row[]>(`/api/projects/${id}/items`,token));}catch(e){handleError(e);}}}

  async function inspect(sheet?:string,rowOverride?:number){if(!token||!file)return;setBusy(true);setError("");setPreview(null);try{
    const form = new FormData();form.append("file",file);if(sheet)form.append("sheet",sheet);form.append("header_row",String(rowOverride??headerRow));
    const res = await request<Inspection>("/api/imports/inspect",token,"POST",form);
    setInspection(res);setSelectedSheet(res.selected_sheet);setHeaderRow(res.header_row);setMapping({description:res.mapping.description||"",quantity:res.mapping.quantity||"",unit:res.mapping.unit||""});
    setMessage("Sütunları kontrol edip önizleme oluşturun.");
  }catch(e){handleError(e);}finally{setBusy(false);}}
  function uploadForm(){const form = new FormData();if(file) form.append("file",file);
    if(selectedSheet)form.append("sheet",selectedSheet);form.append("header_row",String(headerRow));form.append("description_column",mapping.description);form.append("quantity_column",mapping.quantity);form.append("unit_column",mapping.unit);return form;}
  async function previewRows(){if(!token||!file)return;setBusy(true);setError("");try{
    const res = await request<Preview>("/api/imports/preview",token,"POST",uploadForm());setPreview(res);setMessage("İlk 30 satır önizleniyor; henüz projeye kaydedilmedi.");
  }catch(e){handleError(e);}finally{setBusy(false);}}
  async function importRows(){if(!token||!file||!project)return;setBusy(true);setError("");try{
    const result = await request<{row_count:number;review_count:number}>(`/api/projects/${project}/imports`,token,"POST",uploadForm());
    setItems(await request<Row[]>(`/api/projects/${project}/items`,token));setPreview(null);setInspection(null);setFile(null);
    setMessage(`${result.row_count} metraj kalemi kaydedildi. ${result.review_count} kalem kontrol gerektiriyor.`);
    setRevisionTick(v=>v+1);
  }catch(e){handleError(e);}finally{setBusy(false);}}

  return <>
    <header><div><div className="brand">ARKEMX</div><div className="subbrand">COST INTELLIGENCE</div></div><div className="flex"><span className="tag">M1 · Metraj Çekirdeği</span>{token&&<button onClick={logout}>Çıkış</button>}</div></header>
    {!token ? <main className="page"><div className="auth card stack"><div><h1>Akıllı maliyetin temeli</h1><p>Metraj dosyanızı güvenli biçimde projeye alın, kaynağını ve kontrol gerektiren satırları görün.</p></div>
       <div className="flex"><button className={mode==="register"?"":"secondary"} onClick={()=>setMode("register")}>Hesap oluştur</button><button className={mode==="login"?"":"secondary"} onClick={()=>setMode("login")}>Giriş yap</button></div>
       <form className="stack" onSubmit={auth}>{mode==="register"&&<label>Firma / Ofis adı<input required minLength={2} value={org} onChange={e=>setOrg(e.target.value)} placeholder="Örn. Pilot Mühendislik"/></label>}
       <label>E-posta<input required type="email" value={email} onChange={e=>setEmail(e.target.value)}/></label>
       <label>Şifre (en az 12 karakter)<input required type="password" minLength={mode==="register"?12:1} value={password} onChange={e=>setPassword(e.target.value)}/></label>
       <button disabled={busy}>{busy?"İşleniyor...":mode==="register"?"Pilot hesabı oluştur":"Giriş yap"}</button></form>
       <p className="notice">Bu sürüm yalnızca yerel pilot içindir. Gerçek müşteri dosyalarını internet üzerinden yüklemeyin; ticari dağıtım öncesinde oturum, depolama ve güvenlik kontrolleri tamamlanacaktır.</p>
       {error&&<div role="alert" className="error">{error}</div>}</div></main>:
    <main className="page"><div className="hero"><div><h1>Proje ve metraj yönetimi</h1><p>İlk kilometre taşı: metrajı içeri al, incele, izlenebilir şekilde kaydet.</p></div><span className="tag">M3 · Poz katalog yönetimi</span></div>
      {message&&<div role="status" className="success">{message}</div>}{error&&<div role="alert" className="error">{error}</div>}
      <div className="grid"><aside className="stack"><section className="card"><h2>Projelerim</h2>{projects.length===0?<p>Henüz proje bulunmuyor.</p>:projects.map(p=><button key={p.id} className={`project ${project===p.id?"selected":""}`} onClick={()=>chooseProject(p.id)}>{p.name}</button>)}<form className="stack" onSubmit={createProject}><label>Yeni proje<input required minLength={2} value={projectName} onChange={e=>setProjectName(e.target.value)} placeholder="Proje adı"/></label><button disabled={busy}>Proje oluştur</button></form></section><section className="card"><h2>Veri güvenliği</h2><p className="hint">Dosyanın SHA-256 özeti, kaynak sayfası ve satır numarası kaydedilir. Poz katalogları lisans onayı bekler. Her proje firma sınırında izole edilir.</p></section></aside>
      <div className="stack">{!project?<section className="card empty">Soldan bir proje seçin veya yeni proje oluşturun.</section>:<>
        <section className="card stack"><div className="flex between"><h2>Excel metraj yükle</h2><span className="tag">.xlsx · en fazla 10 MB</span></div>
          <label>Metraj dosyası<input type="file" accept=".xlsx" onChange={e=>{setFile(e.target.files?.[0]||null);setInspection(null);setPreview(null);}}/></label>
          <button disabled={!file||busy} className="secondary" onClick={()=>inspect()}>1. Sütunları incele</button>
          {inspection&&<><div className="fields"><label>Çalışma sayfası<select value={selectedSheet} onChange={e=>inspect(e.target.value)}>{inspection.sheets.map(sh=><option key={sh} value={sh}>{sh}</option>)}</select></label><label>Başlık satırı (1-30)<input type="number" min={1} max={30} value={headerRow} onChange={e=>setHeaderRow(Number(e.target.value))}/></label><button className="secondary" disabled={busy||headerRow<1||headerRow>30} onClick={()=>inspect(selectedSheet,headerRow)}>Başlıkları yenile</button></div><p className="hint">Sütun önerilerini kontrol edebilir, değiştirebilirsiniz.</p><div className="fields">{(["description","quantity","unit"] as const).map(field=><label key={field}>{({description:"İmalat açıklaması",quantity:"Miktar",unit:"Birim"})[field]}<select value={mapping[field]||""} onChange={e=>{setMapping({...mapping,[field]:e.target.value});setPreview(null);}}><option value="">Sütun seçin</option>{inspection.headers.map(h=><option key={h} value={h}>{h}</option>)}</select></label>)}</div><div className="flex"><button className="secondary" disabled={busy||!mapping.description||!mapping.quantity||!mapping.unit} onClick={previewRows}>2. Satırları önizle</button><button disabled={busy||!preview} onClick={importRows}>3. Metrajı kaydet</button></div></>}
        </section>
        {preview&&<section className="card stack"><h2>Dosya önizleme</h2><div className="flex"><div className="kpi"><b>{preview.row_count}</b><span>Toplam iş kalemi</span></div><div className="kpi"><b>{preview.review_count}</b><span>İnceleme gerektiren</span></div></div><Rows rows={preview.items}/><p className="hint">İlk 30 satır gösteriliyor. Tüm satırlar kaydetme sırasında yeniden doğrulanır.</p></section>}
        <section className="card stack"><div className="flex between"><h2>Orijinal metraj kaydı (değiştirilemez)</h2><span className="tag">{items.length} görüntülenen</span></div>{items.length?<Rows rows={items}/>:<div className="empty">Henüz kaydedilmiş metraj yok.</div>}</section>
        <CorrectionPanel token={token} project={project} refreshKey={revisionTick} onChange={()=>setRevisionTick(v=>v+1)}/>
        <CatalogPanel token={token} project={project} onMatch={()=>setRevisionTick(v=>v+1)}/>
        <BulkPanel token={token} project={project} onCompleted={()=>setRevisionTick(v=>v+1)}/>
        <EngineerReviewPanel token={token} project={project} refreshKey={revisionTick} onMatch={()=>setRevisionTick(v=>v+1)}/>
        <section className="legacy-tools">
          <button className="secondary" type="button" aria-expanded={showLegacy}
            onClick={()=>setShowLegacy(value=>!value)}>
            {showLegacy?"Eski M4/M2 test ekranlarını kapat":"Eski M4/M2 test ekranlarını aç"}
          </button>
          {showLegacy&&<div className="stack">
            <TechnicalPanel token={token} project={project} refreshKey={revisionTick} onMatch={()=>setRevisionTick(v=>v+1)}/>
            <MatchPanel token={token} project={project} refreshKey={revisionTick}/>
          </div>}
        </section>
      </>}</div></div><p className="hint" style={{marginTop:30}}>ARKEMX Cost Intelligence v0.4.3 · 500 metraj satırına kadar yerel toplu işlem · Uzman incelemesi zorunludur.</p></main>}
  </>;
}

function Rows({rows}:{rows:Row[]}) {return <div className="table-scroll"><table><thead><tr><th>Satır</th><th>İmalat açıklaması</th><th>Miktar</th><th>Birim</th><th>Kontrol durumu</th></tr></thead><tbody>{rows.map((row,i)=><tr key={`${row.source_row}-${i}`}><td>{row.source_row}</td><td>{row.description||"—"}</td><td className="number">{row.quantity??"—"}</td><td>{row.unit??"—"}</td><td>{row.review_required?<span className="warning">Kontrol: {row.issues.join(", ")}</span>:<span style={{color:"var(--green)"}}>Hazır</span>}</td></tr>)}</tbody></table></div>}
