"use client";

import {useEffect,useState} from "react";
import styles from "./review.module.css";

type SourceRecord = {page:number;quote:string;value:string|number};
type Field = {
  key:"layer"|"thickness_mm"|"cement_dosage_kg"|"coverage";
  excel:string|number|null;position:string|number|null;
  project:string|null;status:"source_only"|"missing_project"|"conflict"|"evidence_found"|"scope_review";
  evidence:SourceRecord[];other_evidence_count:number;
};
type Comparison = {
  position_code:string;metraj_revision_id:string|null;
  analysis_pdf_sha256:string;position_pdf_page:number|null;
  document_sha256:string|null;document_state:string;
  source_checks:Field[];candidate_blocked:boolean;
  old_selection_stale_code:string|null;engineering_approved:false;cost_allowed:false;
};
type Props = {
  projectId:string;importId:string;rowId:string;
  candidateCode:string;pdfSha:string;
  revisionId:string|null;specSha:string|null;
};

const API=(process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000").replace(/\/$/,"");
const titles:Record<Field["key"],string>={
  layer:"Sıva katmanı",thickness_mm:"Kalınlık",cement_dosage_kg:"Çimento dozajı",
  coverage:"Kaba/ince kapsamı",
};
function display(key:Field["key"],value:string|number|null|undefined){
  if(value===null||value===undefined||value==="")return "Belirtilmemiş";
  if(key==="thickness_mm")return String(value)+" mm";
  if(key==="cement_dosage_kg")return String(value)+" kg";
  return String(value);
}

export default function PlasterEvidenceComparison({
  projectId,importId,rowId,candidateCode,pdfSha,revisionId,specSha,
}:Props){
  const [data,setData]=useState<Comparison|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    let active=true;
    setData(null);setError("");
    const token=sessionStorage.getItem("arkemx_dev_token");
    if(!token){setError("Oturum gerekli.");return;}
    const url=API+"/api/projects/"+encodeURIComponent(projectId)+"/a338/imports/"+
      encodeURIComponent(importId)+"/items/"+encodeURIComponent(rowId)+
      "/comparison?position_code="+encodeURIComponent(candidateCode);
    void fetch(url,{headers:{Authorization:"Bearer "+token},cache:"no-store"})
      .then(async response=>{
        if(!response.ok)throw Error("Belge karşılaştırması alınamadı (HTTP "+response.status+").");
        return response.json() as Promise<Comparison>;
      }).then(result=>{
        if(!active)return;
        if(result.position_code!==candidateCode||result.analysis_pdf_sha256!==pdfSha||
          result.metraj_revision_id!==revisionId ||
          result.engineering_approved!==false||result.cost_allowed!==false||
          (specSha!==null && result.document_sha256!==specSha))
          throw Error("Belge, poz veya metraj güncellendi. Sayfayı yenile.");
        setData(result);
      }).catch(e=>{if(active)setError(e instanceof Error?e.message:"Belge okunamadı.")});
    return ()=>{active=false};
  },[projectId,importId,rowId,candidateCode,pdfSha,revisionId,specSha]);
  if(error)return <p role="alert" className={styles.a338Warning}>{error}</p>;
  if(!data)return <p role="status" className={styles.a338Hint}>Excel, poz PDF ve şartname karşılaştırılıyor…</p>;
  return <div className={styles.a338Comparison} aria-label="Kaynaklı teknik bilgiler">
    <strong>Kaynaklı teknik bilgiler</strong>
    {data.old_selection_stale_code&&
      <p className={styles.a338Warning}>
        Önceki poz kaydı {data.old_selection_stale_code} artık güncel değil.
        Kayıt geçmişi korundu; yeni poz kaydı ve analizi ayrıca kontrol edilmeli.
      </p>}
    <table className={styles.a338Table}>
      <thead><tr><th>Bilgi</th><th>Excel</th><th>Poz PDF</th><th>Proje şartnamesi</th></tr></thead>
      <tbody>{data.source_checks.map(item=><tr key={item.key}>
        <th>{titles[item.key]}</th>
        <td>{display(item.key,item.excel)}</td>
        <td>{display(item.key,item.position)}</td>
        <td>{display(item.key,item.project)}
          {item.evidence.length>0&&<>
            <small> · PDF s. {item.evidence.map(e=>e.page).filter((v,i,a)=>a.indexOf(v)===i).join(", ")}</small>
            <details><summary>Kaynak cümlesi</summary>
              {item.evidence.map((e,i)=><p key={i}>Sayfa {e.page}: {e.quote}</p>)}
              {item.other_evidence_count>0&&<small>Diğer {item.other_evidence_count} ilgili ifade ayrıca incelenmeli.</small>}
            </details>
          </>}
          {item.status==="conflict"&&<small className={styles.a338Conflict}> · Çelişki var</small>}
          {item.status==="missing_project"&&<small> · Projeden doğrulanmadı</small>}
        </td>
      </tr>)}</tbody>
    </table>
    {data.document_state!=="available"&&<p className={styles.a338Warning}>
      Teknik şartname okunamadı veya mevcut değil. Eksik bilgiler tahmin edilmedi.
    </p>}
    {data.candidate_blocked&&<p className={styles.a338Warning}>Bu pozun teknik çelişkisi var; kaydedilemez.</p>}
    <small>Excel'deki 20 mm ile şartnamenin uyumu, pozun bütün koşullarının doğrulandığı anlamına gelmez.
      Çimento dozajı ve uygulama kapsamı projede açık değilse inceleme bekler.
      Bu ekran mühendis onayı veya maliyet yetkisi vermez.</small>
  </div>;
}
