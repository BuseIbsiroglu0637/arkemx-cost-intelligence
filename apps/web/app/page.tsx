"use client";

import Link from "next/link";
import { clearWorkspace, readWorkspace, rememberImport, rememberProject } from "./workspace-context";
import WorkflowNav, { type WorkflowSection } from "./workflow-nav";
import workflow from "./workflow-nav.module.css";
import metrajStyle from "./metraj-home.module.css";

import {useCallback, useEffect, useRef, useState, type FormEvent} from "react";

import MatchPanel from "./match-panel";
import ReviewWorkspace from "./batch-technical-review/review-workspace";

import CorrectionPanel from "./correction-panel";

import CatalogPanel from "./catalog-panel";

import TechnicalPanel from "./technical-panel";

import EngineerReviewPanel from "./engineer-review-panel";

import BulkPanel from "./bulk-panel";

import CostPanel from "./cost-panel";

import RevisedMetrajPanel from "./revised-metraj-panel";

type Project = {id: string; name: string; created_at: string};

type Tab = "overview"|"metraj"|"technical"|"catalog"|"bulk"|"review"|"cost";

type JobSummary = {status:string;total_rows:number;processed_rows:number;candidate_count:number};

type QueueSummary = {run:null|{row_count:number;candidate_count:number};summary?:{decisions?:Record<string,number>}};

const sectionTitles: Record<WorkflowSection, string> = {
  overview: "Proje özeti", metraj: "Metraj", technical: "Pozları incele",
  cost: "Maliyet", catalog: "Kaynaklar",
};
const validTabs: Tab[] = ["overview", "metraj", "technical", "catalog", "bulk", "review", "cost"];

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
  const [deleteConfirmName, setDeleteConfirmName] = useState("");

  const [inspection,setInspection] = useState<Inspection|null>(null); const [selectedSheet,setSelectedSheet] = useState(""); const [headerRow,setHeaderRow] = useState(1); const [preview,setPreview] = useState<Preview|null>(null);

  const [mapping,setMapping] = useState<Record<string,string>>({description:"",quantity:"",unit:""});

  const [items,setItems] = useState<Row[]>([]); const [message,setMessage] = useState(""); const [error,setError] = useState("");

  const [busy,setBusy] = useState(false);

  const [revisionTick,setRevisionTick] = useState(0);

  const [showLegacy,setShowLegacy] = useState(false);

  const [tab,setTab] = useState<Tab>("metraj");
  const [reviewOpened, setReviewOpened] = useState(false);

  const [showAllItems,setShowAllItems] = useState(false);

  const [showRevisions,setShowRevisions] = useState(false);

  const [summaryRefresh,setSummaryRefresh] = useState(0);

  const [jobSummary,setJobSummary] = useState<JobSummary|null>(null);

  const [queueSummary,setQueueSummary] = useState<QueueSummary|null>(null);

  const [summaryError,setSummaryError] = useState("");
  const projectRequestRef = useRef(0);
  const [activeExcel, setActiveExcel] = useState("");

  const loadProjects = useCallback(async (t:string) => {setProjects(await request<Project[]>("/api/projects",t));},[]);

  useEffect(()=>{const stored = sessionStorage.getItem("arkemx_dev_token"); if(stored){setToken(stored);loadProjects(stored).catch(()=>{sessionStorage.removeItem("arkemx_dev_token");clearWorkspace();setToken(null);});}},[loadProjects]);

  useEffect(() => {
    const readSection = () => {
      const hash = window.location.hash.slice(1) as Tab;
      if (validTabs.includes(hash)) { setTab(hash); if (hash === "technical") setReviewOpened(true); }
    };
    readSection();
    window.addEventListener("hashchange", readSection);
    window.addEventListener("popstate", readSection);
    return () => {
      window.removeEventListener("hashchange", readSection);
      window.removeEventListener("popstate", readSection);
    };
  }, []);
  useEffect(() => {
    if (!token || projects.length === 0 || project) return;
    const saved = readWorkspace(token);
    if (!saved) return;
    if (!projects.some(item => item.id === saved.projectId)) { clearWorkspace(); return; }
    void chooseProject(saved.projectId);
    // Only server-listed projects can be restored. Selection remains explicit otherwise.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, projects]);
  useEffect(() => {
    setActiveExcel("");
    if (!token || !project) return;
    const saved = readWorkspace(token);
    if (saved?.projectId !== project || !saved.importId) return;
    let active = true;
    request<{id:string;filename:string;sheet:string}[]>(`/api/projects/${project}/imports`, token).then(imports => {
      if (!active || sessionStorage.getItem("arkemx_dev_token") !== token) return;
      const selected = imports.find(item => item.id === saved.importId);
      if (selected) setActiveExcel(`${selected.filename} · ${selected.sheet}`);
      else rememberImport(token, project, null);
    }).catch(() => { if (active) setActiveExcel("Excel seçimi doğrulanamadı; teknik incelemede yeniden seç."); });
    return () => { active = false; };
  }, [token, project, revisionTick]);
  const activeSection: WorkflowSection = tab === "bulk" || tab === "review" ? "technical" : tab;

  const handleError = (e:unknown)=>setError(e instanceof Error?e.message:"Beklenmeyen hata");

  const goTo=(next:Tab)=>{

    setTab(next);
    if (next === "technical") setReviewOpened(true);
    window.history.pushState(null, "", `#${next}`);

    document.getElementById("workspace-main")?.scrollIntoView({behavior:"smooth",block:"start"});

  };

  useEffect(()=>{

    if(!token||!project){setJobSummary(null);setQueueSummary(null);setSummaryError("");return;}

    let active=true;

    Promise.allSettled([

      request<JobSummary[]>(`/api/projects/${project}/m43/jobs`,token),

      request<QueueSummary>(`/api/projects/${project}/m42/queue?page=1&page_size=1`,token),

    ]).then(results=>{

      if(!active)return;

      setJobSummary(results[0].status==="fulfilled"?(results[0].value[0]??null):null);

      setQueueSummary(results[1].status==="fulfilled"?results[1].value:null);

      setSummaryError(results.some(r=>r.status==="rejected")?"Durum özetinin bir bölümü yüklenemedi.":"");

    });

    return()=>{active=false;};

  },[token,project,tab,revisionTick,summaryRefresh]);

  async function auth(e:FormEvent) {e.preventDefault();setBusy(true);setError("");try{

    const endpoint = mode === "register"? "/api/auth/register":"/api/auth/login";

    const body = mode === "register" ? {organization_name:org,email,password}:{email,password};

    const result = await request<{access_token:string}>(endpoint,null,"POST",body);

    clearWorkspace(); projectRequestRef.current += 1; setProjects([]); setProject(""); setItems([]);
    sessionStorage.setItem("arkemx_dev_token",result.access_token);setToken(result.access_token);

    await loadProjects(result.access_token);setMessage("Oturum açıldı.");

  }catch(e){handleError(e);}finally{setBusy(false);}}

  function logout(){projectRequestRef.current += 1; clearWorkspace();sessionStorage.removeItem("arkemx_dev_token");setToken(null);setProjects([]);setProject("");setItems([]);setPreview(null);setTab("metraj");}

  async function createProject(e:FormEvent){e.preventDefault();if(!token)return;setBusy(true);setError("");try{

    const p = await request<Project>("/api/projects",token,"POST",{name:projectName});

    await loadProjects(token);await chooseProject(p.id);setProjectName("");setTab("metraj");setShowRevisions(false);setMessage("Proje oluşturuldu.");

  }catch(e){handleError(e);}finally{setBusy(false);}}

  async function deleteSelectedProject(e: FormEvent) {
    e.preventDefault();
    if (!token || !project || busy) return;
    const selected = projects.find(item => item.id === project);
    if (!selected || deleteConfirmName !== selected.name) return;
    setBusy(true); setError("");
    try {
      const result = await request<{deleted_project_id: string; cleanup_pending: boolean}>(
        `/api/projects/${encodeURIComponent(project)}`, token, "DELETE",
        {confirm_project_id: project, confirm_name: deleteConfirmName}
      );
      if (result.deleted_project_id !== project) throw new Error("Silme yanıtı eşleşmiyor.");
      projectRequestRef.current += 1;
      clearWorkspace();
      setProject(""); setItems([]); setPreview(null); setInspection(null);
      setFile(null); setActiveExcel(""); setReviewOpened(false);
      setDeleteConfirmName(""); setShowRevisions(false);
      setProjects(await request<Project[]>("/api/projects", token));
      setTab("metraj");
      setMessage(result.cleanup_pending
        ? "Proje kayıtları silindi; bazı yükleme dosyaları için temizlik gerekiyor."
        : "Proje ve ilişkili verileri silindi.");
    } catch (e) { handleError(e); }
    finally { setBusy(false); }
  }

  async function chooseProject(id:string) {
    const generation = ++projectRequestRef.current;
    if (token) rememberProject(token, id);
    setReviewOpened(false); setDeleteConfirmName("");
    setProject(id); setInspection(null); setPreview(null); setFile(null); setItems([]);
    setShowAllItems(false); setShowRevisions(false); setJobSummary(null); setQueueSummary(null); setError(""); setMessage("");
    if (!token || !id) return;
    try {
      const rows = await request<Row[]>(`/api/projects/${id}/items`, token);
      if (projectRequestRef.current === generation && sessionStorage.getItem("arkemx_dev_token") === token) setItems(rows);
    } catch(e) {
      if (projectRequestRef.current === generation && sessionStorage.getItem("arkemx_dev_token") === token) {
        handleError(e); clearWorkspace(); setProject("");
      }
    }
  }

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

    const result = await request<{id:string;row_count:number;review_count:number}>(`/api/projects/${project}/imports`,token,"POST",uploadForm());

    rememberImport(token, project, result.id);
    setItems(await request<Row[]>(`/api/projects/${project}/items`,token));setPreview(null);setInspection(null);setFile(null);

    setMessage(`${result.row_count} metraj kalemi kaydedildi. ${result.review_count} kalem kontrol gerektiriyor.`);

    setRevisionTick(v=>v+1);

  }catch(e){handleError(e);}finally{setBusy(false);}}

  const hasNewPendingJob=jobSummary?.status==="queued"||jobSummary?.status==="running";

  const hasPriorReview=Boolean(queueSummary?.run&&queueSummary.run.candidate_count>0);

  const jobStatusText=jobSummary?.status==="completed"?"Tamamlandı":

    jobSummary?.status==="queued"?"Kuyrukta":jobSummary?.status==="running"?"İşleniyor":

    jobSummary?.status==="blocked"?"Engellendi":jobSummary?.status==="failed"?"Hata":

    "İş yok";

  return <>

    <header className={tab === "metraj" ? metrajStyle.brandHeader : undefined}>
      <div className={tab === "metraj" ? metrajStyle.brandIdentity : undefined}>
        {tab === "metraj" && <span className={metrajStyle.brandSymbol} aria-hidden="true">A</span>}
        <div><div className="brand">ARKEMX</div><div className="subbrand">COST INTELLIGENCE</div></div>
      </div>
      <div className="flex">
        <span className={tab === "metraj" ? metrajStyle.headerTitle : "tag"}>
          {tab === "metraj" ? "Proje çalışma alanı" : "Cost Intelligence · Yerel Pilot"}
        </span>
        {token && <button type="button" onClick={logout}>Çıkış</button>}
      </div>
    </header>

    {!token ? <main className="page"><div className="auth card stack"><div><h1>Akıllı maliyetin temeli</h1><p>Metraj dosyanızı güvenli biçimde projeye alın, kaynağını ve kontrol gerektiren satırları görün.</p></div>

       <div className="flex"><button className={mode==="register"?"":"secondary"} onClick={()=>setMode("register")}>Hesap oluştur</button><button className={mode==="login"?"":"secondary"} onClick={()=>setMode("login")}>Giriş yap</button></div>

       <form className="stack" onSubmit={auth}>{mode==="register"&&<label>Firma / Ofis adı<input required minLength={2} value={org} onChange={e=>setOrg(e.target.value)} placeholder="Örn. Pilot Mühendislik"/></label>}

       <label>E-posta<input required type="email" value={email} onChange={e=>setEmail(e.target.value)}/></label>

       <label>Şifre (en az 12 karakter)<input required type="password" minLength={mode==="register"?12:1} value={password} onChange={e=>setPassword(e.target.value)}/></label>

       <button disabled={busy}>{busy?"İşleniyor...":mode==="register"?"Pilot hesabı oluştur":"Giriş yap"}</button></form>

       <p className="notice">Bu sürüm yalnızca yerel pilot içindir. Gerçek müşteri dosyalarını internet üzerinden yüklemeyin; ticari dağıtım öncesinde oturum, depolama ve güvenlik kontrolleri tamamlanacaktır.</p>

       {error&&<div role="alert" className="error">{error}</div>}</div></main>:

    <main className="page workspace-page">

      {tab !== "metraj" && <section className="workspace-context card" aria-label="Proje seçimi ve çalışma özeti">

        <div className="workspace-project">

          <div className="workspace-context-heading">
            <h1>Proje çalışma alanı</h1>
            <p className="hint">Metrajı yükleyin, pozları inceleyin ve maliyeti aynı projede hazırlayın.</p>

          </div>

          <label className="workspace-project-select">Aktif proje

            <select aria-label="Aktif proje seç" disabled={busy} value={project} onChange={e=>chooseProject(e.target.value)}>

              <option value="">Proje seçin</option>

              {projects.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}

            </select>

          </label>

          <details className="workspace-create">

            <summary>+ Yeni proje</summary>

            <form className="stack" onSubmit={createProject}>

              <label>Proje adı<input required minLength={2} value={projectName} onChange={e=>setProjectName(e.target.value)} placeholder="Yeni proje adı"/></label>

              <button disabled={busy} type="submit">Proje oluştur</button>

            </form>

          </details>

        </div>

        <details><summary>Proje durum ayrıntıları</summary><div className="workspace-status" aria-label="Proje durum özeti">

          <span>En yeni toplu iş: <strong>{project?jobStatusText:"Proje seçilmedi"}</strong></span>

          <span>Bu işin ilerlemesi: <strong>{jobSummary?`${jobSummary.processed_rows}/${jobSummary.total_rows}`:"—"}</strong></span>

          <span>İnceleme kuyruğu: <strong>{queueSummary?.run?.candidate_count??"—"} aday</strong></span>

          <span>Onay: <strong>{queueSummary?.summary?.decisions?.approved??"—"}</strong></span>

          {project&&<button type="button" className="ghost workspace-refresh" onClick={()=>setSummaryRefresh(v=>v+1)}>Durumu yenile</button>}

        </div></details>

      </section>}

      {message&&<div role="status" className="success">{message}</div>}

      {error&&<div role="alert" className="error">{error}</div>}

      {summaryError&&<p role="status" className="hint">{summaryError}</p>}

      {tab === "metraj" && <>
        <section className={metrajStyle.hero} aria-label="Metraj çalışma alanı">
          <div>
            <span className={metrajStyle.kicker}>ÇALIŞMA ALANI / METRAJ</span>
            <h1>Metraj yönetimi</h1>
            <p>Metrajını yükle, kayıtlarını görüntüle ve teknik incelemeye geç.</p>
          </div>
          <div className={metrajStyle.projectActions}>
            <label className={metrajStyle.projectSelect}>
              <span>Aktif proje</span>
              <select aria-label="Aktif proje seç" value={project} onChange={e => chooseProject(e.target.value)}>
                <option value="">Proje seçin</option>
                {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <details className={metrajStyle.newProject}>
              <summary>+ Yeni proje</summary>
              <form className="stack" onSubmit={createProject}>
                <label>Proje adı<input required minLength={2} value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="Yeni proje adı" /></label>
                <button type="submit" disabled={busy}>Proje oluştur</button>
              </form>
            </details>
            {project && <details className={metrajStyle.deleteProject}>
              <summary>Projeyi sil</summary>
              <form onSubmit={deleteSelectedProject} className="stack">
                <strong>Proje kalıcı olarak silinecek.</strong>
                <p>Bu projeye ait Excel aktarımları, inceleme kayıtları, revizyonlar ve maliyet taslakları da silinir. Diğer projeler ve paylaşılan kataloglar korunur.</p>
                <p>Onaylamak için proje adını aynen yaz:</p>
                <code>{projects.find(item => item.id === project)?.name}</code>
                <label>
                  Proje adını doğrula
                  <input type="text" value={deleteConfirmName} onChange={e => setDeleteConfirmName(e.target.value)} autoComplete="off" />
                </label>
                <button type="submit" disabled={busy || deleteConfirmName !== projects.find(item => item.id === project)?.name}>Projeyi kalıcı sil</button>
              </form>
            </details>}
          </div>
        </section>
        <nav className={metrajStyle.steps} aria-label="Çalışma aşamaları">
          <button type="button" className={metrajStyle.stepActive} aria-current="step">
            <span className={metrajStyle.stepNumber}>1</span>
            <span><strong>Metraj</strong><small>Aktif aşama</small></span>
          </button>
          <button type="button" disabled={!project} onClick={() => goTo("technical")}>
            <span className={metrajStyle.stepNumber}>2</span>
            <span><strong>Poz inceleme</strong><small>Adaylar ve kanıtlar</small></span>
          </button>
          <button type="button" disabled={!project} onClick={() => goTo("cost")}>
            <span className={metrajStyle.stepNumber}>3</span>
            <span><strong>Maliyet</strong><small>Taslak ve farklar</small></span>
          </button>
        </nav>
      </>}
      {tab === "technical" && <>
        <section className={metrajStyle.hero} aria-label="Poz inceleme çalışma alanı">
          <div>
            <span className={metrajStyle.kicker}>ÇALIŞMA ALANI / METRAJ / POZ İNCELEME</span>
            <h1>Poz inceleme</h1>
            <p>Excel metrajın için poz adaylarını otomatik bul, teknik farkları kontrol et.</p>
          </div>
          <div className={metrajStyle.projectActions}>
            <label className={metrajStyle.projectSelect}>
              <span>Aktif proje</span>
              <select aria-label="Aktif proje seç" value={project} onChange={e => chooseProject(e.target.value)}>
                <option value="">Proje seçin</option>
                {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <details className={metrajStyle.newProject}>
              <summary>+ Yeni proje</summary>
              <form className="stack" onSubmit={createProject}>
                <label>Proje adı<input required minLength={2} value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="Yeni proje adı" /></label>
                <button type="submit" disabled={busy}>Proje oluştur</button>
              </form>
            </details>
          </div>
        </section>
        <nav className={metrajStyle.steps} aria-label="Çalışma aşamaları">
          <button type="button" onClick={() => goTo("metraj")}>
            <span className={metrajStyle.stepNumber}>1</span>
            <span><strong>Metraj</strong><small>Excel ve kayıtlar</small></span>
          </button>
          <button type="button" className={metrajStyle.stepActive} aria-current="step">
            <span className={metrajStyle.stepNumber}>2</span>
            <span><strong>Poz inceleme</strong><small>Adaylar ve kanıtlar</small></span>
          </button>
          <button type="button" disabled={!project} onClick={() => goTo("cost")}>
            <span className={metrajStyle.stepNumber}>3</span>
            <span><strong>Maliyet</strong><small>Taslak ve farklar</small></span>
          </button>
        </nav>
      </>}
      {tab !== "metraj" && tab !== "technical" && project && <div className={workflow.context} aria-label="Aktif çalışma kaynağı"><span><strong>Proje:</strong> {projects.find(item => item.id === project)?.name}</span><span><strong>Excel / çalışma sayfası:</strong> {activeExcel || "Metraj yükleyin veya Pozları incele adımından Excel seçin."}</span><span>Satır revizyonu teknik inceleme kanıtında gösterilir.</span></div>}
      {tab !== "metraj" && tab !== "technical" && <WorkflowNav active={activeSection} onSelect={goTo} />}
      {tab !== "metraj" && tab !== "technical" && <details className="card"><summary>Proje özeti ve kaynak yönetimi</summary>
        <div className="flex"><button type="button" className="secondary" onClick={() => goTo("overview")}>Proje özeti</button>
        <button type="button" className="secondary" onClick={() => goTo("catalog")}>Katalog ve PDF kaynakları</button></div>
      </details>}
      {tab !== "metraj" && tab !== "technical" && <div className={workflow.steps}>Metraj → Pozları incele → Maliyet. Teknik farklar ve kaynak kanıtları satırın ayrıntısında gösterilir.</div>}
      <div className="workspace-main" id="workspace-main" aria-label={sectionTitles[activeSection]}>
      {(tab === "bulk" || tab === "review") && <div className="card stack">
        <button type="button" className="secondary" onClick={() => goTo("technical")}>← Teknik inceleme seçeneklerine dön</button>
        <h2>{tab === "bulk" ? "Katalogdan aday bulma" : "Mühendis kararları"}</h2>
        <p>{tab === "bulk" ? "Bu işlem aday üretir. Kanıtlı teknik uygunluk kontrolü veya mühendis onayı yerine geçmez." : "Bu bölüm kayıtlı karar akışıdır. PDF teknik karşılaştırmasının sonuçları burada otomatik onaylanmaz."}</p>
      </div>}

      {project && (reviewOpened || tab === "technical") && <section hidden={tab !== "technical"} style={{display: tab === "technical" ? "block" : "none"}} aria-label="Poz inceleme çalışma alanı">
        <ReviewWorkspace key={`${token}:${project}:${revisionTick}`} projectScope={project}
          onImportSelected={setActiveExcel} onSessionExpired={logout} />
        <details className="card"><summary>Gelişmiş işlemler · Katalogdan aday üretme ve mühendis kararı</summary>
          <p>PDF karşılaştırması onay vermez. Mevcut katalog taraması ve mühendis kararları bu proje altında sürdürülür; teknik engeller aynen uygulanır.</p>
          <BulkPanel token={token} project={project} onCompleted={() => setSummaryRefresh(v => v + 1)} />
          <EngineerReviewPanel token={token} project={project} refreshKey={summaryRefresh} onGoToBulk={() => goTo("bulk")} />
        </details>
        <div className="card flex between"><button type="button" className="secondary" onClick={() => goTo("metraj")}>← Metraja dön</button>
          <button type="button" onClick={() => goTo("cost")}>Maliyete geç →</button></div>
      </section>}

      {!project?<section className="card empty">Yukarıdan bir proje seçin veya yeni proje oluşturun.</section>:

       tab==="overview"?<div className="stack">

        <section className="card stack">

          <div className="flex between"><div><h2>Proje özeti</h2><p className="hint">Kayıtlı aday bulma ve mühendis kararlarının özeti. Salt okunur Excel teknik incelemesinin sonuçları bu sayaçlara dahil değildir.</p></div><span className="tag">Yerel pilot</span></div>

          <div className="workspace-kpis">

            <div className="kpi"><b>{jobSummary?.total_rows??"—"}</b><span>En yeni işin toplam metrajı</span></div>

            <div className="kpi"><b>{queueSummary?.run?.candidate_count??"—"}</b><span>İncelemeye açılmış poz adayı</span></div>

            <div className="kpi"><b>{queueSummary?.summary?.decisions?.approved??"—"}</b><span>Güncel mühendis onayı</span></div>

          </div>

          {hasNewPendingJob&&hasPriorReview&&<p className="hint" role="status">

            Yeni toplu iş {jobSummary?.processed_rows??0}/{jobSummary?.total_rows??0} satırda bekliyor.

            İnceleme bölümündeki {queueSummary?.run?.candidate_count} aday, önceki tamamlanmış çalışmaya aittir;

            bekleyen iş tamamlanmadan incelemeye aktarılmaz.

          </p>}

          <div className="workspace-next"><div><strong>{jobSummary?"En yeni toplu iş: "+jobStatusText:"Henüz toplu iş oluşturulmadı"}</strong>

            <p className="hint">{jobSummary?`${jobSummary.processed_rows}/${jobSummary.total_rows} satır, bu işe ait ${jobSummary.candidate_count} aday kaydedildi.`:"Metraj ve katalog seçerek toplu analizi başlatabilirsiniz."}</p></div>

            <button type="button" onClick={()=>goTo(jobSummary?.status==="completed"?"review":jobSummary?"bulk":"metraj")}>

              {jobSummary?.status==="completed"?"İncelemeye geç":jobSummary?"Toplu analize geç":"Metraja geç"}</button>

          </div>

        </section>

        <section className="legacy-tools">

          <button type="button" className="secondary" aria-expanded={showLegacy} onClick={()=>setShowLegacy(v=>!v)}>

            {showLegacy?"Gelişmiş testleri kapat":"Gelişmiş araçlar · Eşleştirme denemeleri"}</button>

          {showLegacy&&<div className="stack">

            <p className="warning">Bu araçlar yeni test çalışması oluşturabilir. Kayıtlı toplu sonuçları korumak için gereksiz çalıştırmayın.</p>

            <TechnicalPanel token={token} project={project} refreshKey={revisionTick} onMatch={()=>setRevisionTick(v=>v+1)}/>

            <MatchPanel token={token} project={project} refreshKey={revisionTick}/>

          </div>}

        </section>

       </div>:

       tab==="technical"?null:
       tab==="metraj"?<div className={metrajStyle.content}>
         <section className={metrajStyle.panel} aria-labelledby="saved-metraj-heading">
           <div className={metrajStyle.sectionHead}>
             <div>
               <h2 id="saved-metraj-heading">Kaydedilmiş metraj</h2>
               <p>Bu projede daha önce yüklenen, özgün hâli korunan metraj kayıtları.</p>
             </div>
             <span className={items.length ? metrajStyle.savedTag : metrajStyle.neutralTag}>{items.length ? "✓ Kayıt mevcut" : "Henüz kayıt yok"}</span>
           </div>
           {items.length > 0 ? <>
             <div className={metrajStyle.stats}>
               <div><small>Görüntülenen kayıt</small><strong>{items.length}</strong></div>
               <div><small>Girdi incelemesi gerekli</small><strong>{items.filter(row => row.review_required).length}</strong></div>
               <div><small>Kaynak kayıt</small><strong>Korunuyor</strong></div>
             </div>
             {activeExcel && <p className={metrajStyle.sourceNote}>Seçili Excel / çalışma sayfası: <strong>{activeExcel}</strong></p>}
             <div className={metrajStyle.tableFrame}>
               <table>
                 <thead><tr><th>Excel satırı</th><th>İmalat açıklaması</th><th>Miktar / birim</th><th>Durum</th></tr></thead>
                 <tbody>{(showAllItems ? items : items.slice(0, 20)).map((row, index) =>
                   <tr key={row.source_row + "-" + index}>
                     <td>{row.source_row}</td>
                     <td className={metrajStyle.description}>{row.description || "Açıklama yok"}</td>
                     <td>{row.quantity ?? "Eksik"} {row.unit ?? ""}</td>
                     <td><span className={row.review_required ? metrajStyle.reviewTag : metrajStyle.savedTag}>{row.review_required ? "Girdi incelemesi gerekli" : "Kaydedildi"}</span></td>
                   </tr>
                 )}</tbody>
               </table>
             </div>
             {items.length > 20 && <button type="button" className="secondary" onClick={() => setShowAllItems(v => !v)}>{showAllItems ? "İlk 20 satırı göster" : "Tüm görüntülenebilir kayıtları göster"}</button>}
             <div className={metrajStyle.sectionFooter}>
               <span>Kaynak Excel kaydı değiştirilmez. Teknik uygunluk ayrıca değerlendirilir.</span>
               <button type="button" onClick={() => goTo("technical")}>Pozları incele →</button>
             </div>
           </> : <div className={metrajStyle.emptyState}>Bu projede henüz kaydedilmiş metraj bulunmuyor. Aşağıdan Excel yükleyerek başlayabilirsin.</div>}
         </section>

         <section className={metrajStyle.panel} aria-labelledby="upload-heading">
           <div className={metrajStyle.sectionHead}>
             <div><h2 id="upload-heading">Yeni Excel metrajı yükle</h2><p>İmalat açıklaması, miktar ve birim sütunlarını kontrol ederek içe aktar.</p></div>
             <a className={metrajStyle.templateLink} href="/templates/arkemx-metraj-ornek.xlsx" download>Örnek Excel şablonu ↓</a>
           </div>
           <div className={metrajStyle.uploadZone}
             onDragOver={event => event.preventDefault()}
             onDrop={event => {
               event.preventDefault();
               const dropped = event.dataTransfer.files[0];
               if (!dropped) return;
               if (!dropped.name.toLowerCase().endsWith(".xlsx") || dropped.size > 10 * 1024 * 1024) {
                 setError("Yalnızca en fazla 10 MB büyüklüğünde .xlsx dosyası seçilebilir.");
                 return;
               }
               setFile(dropped); setInspection(null); setPreview(null); setError("");
             }}>
             <span className={metrajStyle.uploadIcon} aria-hidden="true">⇧</span>
             <label className={metrajStyle.filePicker}>
               <span>Excel dosyanı buraya sürükle veya dosya seç</span>
               <input type="file" accept=".xlsx" aria-label="Excel metraj dosyası seç"
                 onChange={event => { setFile(event.target.files?.[0] ?? null); setInspection(null); setPreview(null); }} />
             </label>
             <small>.xlsx formatı · En fazla 10 MB</small>
             {file && <strong className={metrajStyle.selectedFile}>Seçilen dosya: {file.name}</strong>}
           </div>
           <div className={metrajStyle.uploadActions}>
             <button type="button" disabled={!file || busy} onClick={() => inspect()}>1. Sütunları incele</button>
             <span>Excel, sütun eşleştirmesi ve önizleme onayından sonra kaydedilir.</span>
           </div>
           {inspection && <div className={metrajStyle.importConfig}>
             <div className="fields">
               <label>Çalışma sayfası<select value={selectedSheet} onChange={e => inspect(e.target.value)}>{inspection.sheets.map(sh => <option key={sh} value={sh}>{sh}</option>)}</select></label>
               <label>Başlık satırı (1–30)<input type="number" min={1} max={30} value={headerRow} onChange={e => setHeaderRow(Number(e.target.value))}/></label>
               <button type="button" className="secondary" disabled={busy || headerRow < 1 || headerRow > 30} onClick={() => inspect(selectedSheet, headerRow)}>Başlıkları yenile</button>
             </div>
             <p className="hint">Excel sütunlarını doğrula; otomatik önerileri gerekiyorsa değiştir.</p>
             <div className="fields">{(["description", "quantity", "unit"] as const).map(field =>
               <label key={field}>{({description:"İmalat açıklaması", quantity:"Miktar", unit:"Birim"})[field]}
                 <select value={mapping[field] || ""} onChange={e => { setMapping({...mapping, [field]:e.target.value}); setPreview(null); }}>
                   <option value="">Sütun seçin</option>{inspection.headers.map(h => <option key={h} value={h}>{h}</option>)}
                 </select>
               </label>)}</div>
             <div className="flex">
               <button type="button" className="secondary" disabled={busy || !mapping.description || !mapping.quantity || !mapping.unit} onClick={previewRows}>2. Satırları önizle</button>
               <button type="button" disabled={busy || !preview} onClick={importRows}>3. Metrajı kaydet</button>
             </div>
           </div>}
         </section>

         {preview && <section className={metrajStyle.panel}>
           <h2>Dosya önizleme</h2>
           <div className="flex"><div className="kpi"><b>{preview.row_count}</b><span>Toplam iş kalemi</span></div><div className="kpi"><b>{preview.review_count}</b><span>İnceleme gerektiren</span></div></div>
           <Rows rows={preview.items}/>
           <p className="hint">İlk 30 satır gösteriliyor. Tüm satırlar kaydetme sırasında yeniden doğrulanır.</p>
         </section>}

         <details className={metrajStyle.advanced}>
           <summary><span>⚙ &nbsp; Gelişmiş işlemler</span><small>Revizyonlar · Düzeltme geçmişi · Katalog ve PDF kaynakları</small></summary>
           <div className={metrajStyle.advancedBody}>
             <div className={metrajStyle.advancedLinks}>
               <button type="button" className="secondary" onClick={() => goTo("overview")}>Proje özeti</button>
               <button type="button" className="secondary" onClick={() => goTo("catalog")}>Katalog ve PDF kaynakları</button>
             </div>
             <RevisedMetrajPanel token={token} project={project}
               onApplied={async () => {
                 if (token) setItems(await request<Row[]>(`/api/projects/${project}/items`, token));
                 setRevisionTick(v => v + 1); setSummaryRefresh(v => v + 1);
               }}/>
             <section className="workspace-collapsible">
               <button type="button" className="secondary" aria-expanded={showRevisions} onClick={() => setShowRevisions(v => !v)}>
                 {showRevisions ? "Düzeltme geçmişini kapat" : "Metraj düzeltme ve revizyon geçmişini aç"}
               </button>
               {showRevisions && <CorrectionPanel token={token} project={project} refreshKey={revisionTick} onChange={() => setRevisionTick(v => v + 1)}/>}
             </section>
             <div className={metrajStyle.jobNote}>
               <span>En yeni toplu iş: <strong>{jobStatusText}</strong></span>
               <span>İşlenen satır: <strong>{jobSummary ? `${jobSummary.processed_rows}/${jobSummary.total_rows}` : "—"}</strong></span>
               <button type="button" className="secondary" onClick={() => setSummaryRefresh(v => v + 1)}>Durumu yenile</button>
             </div>
           </div>
         </details>
       </div>:

       tab==="catalog"?<div className="stack"><section className="card stack"><h2>Kaynaklar</h2><p>Poz adaylarını bulmak için kullanılan katalogları yönet. Katalogda bulunmak, kanıtlı teknik inceleme desteği anlamına gelmez.</p><details><summary>PDF katalog araçları</summary><Link href="/catalog-analysis">PDF kataloğunu incele →</Link></details><p className="hint">Doğrulanmış analiz PDF’sinin belge kimliği ve fiyat tarihi, teknik inceleme sonucundaki kaynak kanıtında gösterilir.</p></section><CatalogPanel token={token} project={project} onMatch={()=>setRevisionTick(v=>v+1)}/></div>:

       tab==="bulk"?<BulkPanel token={token} project={project} onCompleted={()=>setRevisionTick(v=>v+1)}/>:

       tab==="review"?<EngineerReviewPanel token={token} project={project} refreshKey={revisionTick} onGoToBulk={()=>goTo("bulk")}/>:

       <div className="stack"><section className="card stack"><h2>Maliyet</h2><p>Yalnızca güncel mühendis onayı ve gerekli kaynak kontrolleri bulunan satırlar taslağa alınır. Onaysız veya kapsam dışı satırlar otomatik fiyatlandırılmaz.</p>
       <p className="hint">Bu adım mevcut mühendis kararlarının son Excel aktarımını kullanır. Poz incelemesindeki geçmiş bir Excel seçimi maliyet kapsamını değiştirmez. PDF kaynak fiyatı otomatik uygulanmaz; fiyat ve dayanağı aşağıda belirtilir.</p>
       <button type="button" className="secondary" onClick={() => goTo("technical")}>← Poz incelemesine dön</button><details><summary>Gelişmiş araç · Alternatif harç maliyet senaryosu</summary><p>Tek tarif deneme ekranındaki sınırlı senaryodur. Maliyet taslağına otomatik aktarılmaz ve teknik onay vermez.</p><Link href="/technical-review">Tarif ve senaryo ekranını aç →</Link></details></section><CostPanel key={`${token}:${project}`} token={token} project={project}/></div>}

      </div>

      <p className="hint workspace-footer">ARKEMX Cost Intelligence v0.4.3 · Yerel pilot · 500 metraj satırı · İnsan onayı zorunludur.</p>

    </main>}

  </>;

}

function Rows({rows}:{rows:Row[]}) {return <div className="table-scroll"><table><thead><tr><th>Satır</th><th>İmalat açıklaması</th><th>Miktar</th><th>Birim</th><th>Kontrol durumu</th></tr></thead><tbody>{rows.map((row,i)=><tr key={`${row.source_row}-${i}`}><td>{row.source_row}</td><td>{row.description||"—"}</td><td className="number">{row.quantity??"—"}</td><td>{row.unit??"—"}</td><td>{row.review_required?<span className="warning">Kontrol: {row.issues.join(", ")}</span>:<span style={{color:"var(--green)"}}>Hazır</span>}</td></tr>)}</tbody></table></div>}
