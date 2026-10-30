"use client";

import {useEffect,useMemo,useState} from "react";
import {readWorkspace} from "./workspace-context";

const API=(process.env.NEXT_PUBLIC_API_URL??"http://127.0.0.1:8000").replace(/\/$/,"");

type WorkRow={work_item_id:string;source_row:number;effective_description:string;
  revision_id:string|null;quantity:string|null;unit:string|null;input_review_required:boolean};
type ItemPage={schema:string;read_only:boolean;approval_allowed:false;rows:WorkRow[];next_offset:number|null};
type Choice={code:string;unit:string;technical_status:string;source_price:string|null;
  source_price_verified:boolean;pdf_edition_date:string;source_version_id:string};
type Suggestion={work_item_id:string;source_row:number;revision_id:string|null;
  suggestions:Choice[];saved_selection?:{code:string|null;current:boolean;stale:boolean;
  pdf_sha256:string|null;revision_id:string|null}|null};
type SuggestionPage={read_only:boolean;approval_allowed:false;cost_allowed:false;
  catalog:{sha256:string;synthetic:boolean};rows:Suggestion[];page_offset:number};
type PilotRow={work_item_id:string;source_row:number;saved_candidate:string|null;
  pilot_status:"none"|"confirmed"|"reopened"|"stale";pilot_confirmed:boolean};
type PilotPage={schema:string;read_only:true;approval_allowed:false;
  engineering_approved:false;cost_allowed:false;rows:PilotRow[];next_offset:number|null};
type EstimateRow={row:WorkRow;code:string|null;sourcePrice:string|null;
  amountCents:bigint|null;reason:string;sourceDate:string|null};

function fixed(value:string,scale:number):bigint|null{
  if(!/^\d{1,10}(?:\.\d{1,6})?$/.test(value))return null;
  const [whole,decimal=""]=value.split(".");
  if(decimal.length>scale && /[1-9]/.test(decimal.slice(scale)))return null;
  return BigInt(whole)*BigInt(10)**BigInt(scale)+BigInt(decimal.slice(0,scale).padEnd(scale,"0")||"0");
}
function amount(quantity:string,price:string):bigint|null{
  const q=fixed(quantity,4),p=fixed(price,4);
  return q===null||p===null||q<=BigInt(0)||p<=BigInt(0)?null:(q*p+BigInt(500000))/BigInt(1000000);
}
function money(cents:bigint):string{
  const integer=new Intl.NumberFormat("tr-TR").format(cents/BigInt(100));
  return integer+","+String(cents%BigInt(100)).padStart(2,"0")+" TL";
}
async function get<T>(path:string,token:string):Promise<T>{
  const response=await fetch(API+path,{cache:"no-store",headers:{Authorization:"Bearer "+token}});
  if(!response.ok)throw Error("Kaynak kontrolü başarısız (HTTP "+response.status+").");
  return response.json() as Promise<T>;
}
async function collect(
  project:string,importId:string,token:string,
):Promise<{rows:WorkRow[];suggestions:Suggestion[];pilots:PilotRow[];sha:string;partial:boolean}>{
  const rows:WorkRow[]=[],suggestions:Suggestion[]=[],pilots:PilotRow[]=[];
  let offset=0,sha:string|null=null,partial=false;
  // Current local pilot has a 500-row cap; never silently label a partial
  // subset as the whole project or the final cost.
  for(let page=0;page<25;page++){
    const prefix="/api/projects/"+encodeURIComponent(project);
    const source="/a3/imports/"+encodeURIComponent(importId);
    const [items,positions,pilot]=await Promise.all([
      get<ItemPage>(prefix+source+"/items?offset="+offset+"&limit=20",token),
      get<SuggestionPage>(prefix+"/a318/imports/"+encodeURIComponent(importId)+
        "/suggestions?offset="+offset,token),
      get<PilotPage>(prefix+"/a327/imports/"+encodeURIComponent(importId)+
        "/readiness?offset="+offset+"&limit=20",token),
    ]);
    if(items.schema!=="arkemx.batch_review_selection.v1"||
      items.read_only!==true||items.approval_allowed!==false||
      positions.read_only!==true||positions.approval_allowed!==false||
      positions.cost_allowed!==false||positions.catalog.synthetic!==false||
      !positions.catalog.sha256||positions.page_offset!==offset||
      pilot.schema!=="arkemx.a327.readiness.v1"||
      pilot.read_only!==true||pilot.approval_allowed!==false||
      pilot.engineering_approved!==false||pilot.cost_allowed!==false||
      items.rows.length!==positions.rows.length||items.rows.length!==pilot.rows.length||
      items.rows.some((row,i)=>row.work_item_id!==positions.rows[i].work_item_id||
        row.source_row!==positions.rows[i].source_row||
        row.work_item_id!==pilot.rows[i].work_item_id||
        row.source_row!==pilot.rows[i].source_row)){
      throw Error("Metraj ve poz kaynakları eşleşmiyor. Poz incelemesinde yenile.");
    }
    if(sha&&sha!==positions.catalog.sha256)throw Error("Poz PDF değişti. Yeniden kontrol et.");
    sha=positions.catalog.sha256;
    rows.push(...items.rows);suggestions.push(...positions.rows);pilots.push(...pilot.rows);
    if(items.next_offset!==pilot.next_offset)throw Error("Pilot durumları eksik; hesap yapılmadı.");
    if(items.next_offset===null)return {rows,suggestions,pilots,sha,partial};
    if(items.next_offset<=offset)throw Error("Metraj sayfalaması doğrulanamadı.");
    offset=items.next_offset;
  }
  partial=true;
  return {rows,suggestions,pilots,sha:sha??"",partial};
}
function preview(row:WorkRow,candidate:Suggestion|undefined,pilot:PilotRow|undefined,sha:string):EstimateRow{
  const result:EstimateRow={row,code:null,sourcePrice:null,sourceDate:null,amountCents:null,
    reason:"Poz seçimi bekliyor"};
  const selected=candidate?.saved_selection;
  if(selected?.stale){result.reason="Eski poz yeniden kontrol edilmeli";return result;}
  if(!selected?.current||!selected.code)return result;
  result.code=selected.code;
  if(selected.pdf_sha256!==sha||selected.revision_id!==row.revision_id){
    result.reason="Kaynak değişmiş";return result;
  }
  const option=candidate?.suggestions.find(item=>item.code===selected.code);
  if(!option||option.source_version_id!==sha||option.technical_status==="blocked"){
    result.reason="Poz kapsamı tekrar incelenmeli";return result;
  }
  if(row.input_review_required||!row.quantity||!row.unit){
    result.reason="Metraj bilgisi eksik";return result;
  }
  if(option.unit!==row.unit){result.reason="Ölçü birimleri farklı";return result;}
  if(!option.source_price_verified||!option.source_price){
    result.reason="PDF fiyatı doğrulanamadı";return result;
  }
  // Display known source price even for pending pilot rows, but NEVER
  // compute their amount or include them in the DEMO subtotal.
  result.sourcePrice=option.source_price;
  result.sourceDate=option.pdf_edition_date;
  if(!pilot?.pilot_confirmed||pilot.pilot_status!=="confirmed"||
    pilot.saved_candidate!==selected.code){
    result.reason=pilot?.pilot_status==="stale"?"Pilot kontrol güncelliğini kaybetti":"Pilot kontrol bekliyor";
    return result;
  }
  const cents=amount(row.quantity,option.source_price);
  if(cents===null){result.reason="Miktar veya fiyat okunamadı";return result;}
  result.amountCents=cents;result.sourcePrice=option.source_price;
  result.sourceDate=option.pdf_edition_date;
  result.reason="Pilot tamam · DEMO fiyatlı";
  return result;
}
export default function CostDemoPreview({token,project,onReview}:{
  token:string|null;project:string;onReview:()=>void;
}){
  const [rows,setRows]=useState<EstimateRow[]>([]);
  const [partial,setPartial]=useState(false);
  const [importId,setImportId]=useState("");
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const [refresh,setRefresh]=useState(0);

  useEffect(()=>{
    let active=true;setRows([]);setError("");setPartial(false);
    if(!token||!project)return;
    const workspace=readWorkspace(token);
    if(!workspace||workspace.projectId!==project||!workspace.importId){
      setImportId("");setError("Önce Pozları incele sayfasında kullanılacak Excel'i seç.");
      return;
    }
    setImportId(workspace.importId);setLoading(true);
    collect(project,workspace.importId,token).then(data=>{
      if(!active)return;
      setRows(data.rows.map((row,index)=>preview(row,data.suggestions[index],data.pilots[index],data.sha)));
      setPartial(data.partial);
    }).catch(e=>{if(active){setRows([]);setError(e instanceof Error?e.message:"Kaynak okunamadı.");}})
      .finally(()=>{if(active)setLoading(false)});
    return()=>{active=false};
  },[token,project,refresh]);

  const counted=useMemo(()=>rows.filter(r=>r.amountCents!==null),[rows]);
  const total=useMemo(()=>counted.reduce((sum,r)=>sum+(r.amountCents??BigInt(0)),BigInt(0)),[counted]);

  return <section className="card cost-demo" aria-label="DEMO ön maliyet">
    <div className="flex between cost-demo-head">
      <div><h2>DEMO ön maliyet</h2>
        <p className="hint">Güncel pilot kontrolü tamamlanmış, kaynak fiyatlı pozların deneme hesabı</p></div>
      <button type="button" className="secondary" disabled={loading}
        onClick={()=>setRefresh(n=>n+1)}>Yenile</button>
    </div>
    <p className="cost-demo-disclaimer">Yalnızca örnek hesap. Pilot kontrol resmî mühendis onayı değildir; bu tutar güncel resmî fiyat veya nihai teklif değildir.
      Kaynak fiyatları yüklü 2026/01 PDF dönemine aittir.</p>
    {loading&&<p role="status">Metraj ve poz fiyatları kontrol ediliyor…</p>}
    {error&&<div role="alert" className="cost-demo-warning">{error}
      <button type="button" className="secondary" onClick={onReview}>Pozları incele</button></div>}
    {!error&&!loading&&importId&&<>
      <div className="cost-demo-kpis">
        <div><small>Görüntülenen imalat</small><strong>{rows.length}</strong></div>
        <div><small>DEMO fiyatlı</small><strong>{counted.length}</strong></div>
        <div><small>Hesap dışı / eksik</small><strong>{rows.length-counted.length}</strong></div>
        <div><small>DEMO ara toplam</small><strong>{counted.length?money(total):"Henüz yok"}</strong></div>
      </div>
      {partial&&<p role="alert" className="cost-demo-warning">
        İlk 500 satır görüntüleniyor. Bu bir tam proje toplamı değildir.
      </p>}
      {rows.length===0?<p className="hint">Bu Excel'de gösterilecek imalat yok.</p>:
      <div className="table-scroll"><table className="cost-demo-table">
        <thead><tr><th>İmalat / poz</th><th>Miktar</th><th>PDF birim fiyatı (bilgi)</th>
          <th>DEMO tutar</th><th>Durum</th></tr></thead>
        <tbody>{rows.map(item=><tr key={item.row.work_item_id}>
          <td><strong>{item.row.effective_description}</strong>
            <small>Satır {item.row.source_row} · {item.code??"Poz bekliyor"}</small></td>
          <td>{item.row.quantity??"Eksik"} {item.row.unit??""}</td>
          <td>{item.sourcePrice?item.sourcePrice+" TL": "—"}
            {item.sourceDate&&<small>PDF tarihi: {item.sourceDate}</small>}</td>
          <td><strong>{item.amountCents===null?"—":money(item.amountCents)}</strong></td>
          <td>{item.reason}</td>
        </tr>)}</tbody>
      </table></div>}
      <p className="hint">“—” işaretli imalatlar sıfır TL değildir; pilot kontrol veya kaynak kontrolü tamamlanmadığı için DEMO ara toplamın dışındadır.
        Poz ve fiyat kaynağı değişirse bu ön hesap yeniden yapılmalıdır.</p>
      <div className="cost-demo-actions"><button type="button" onClick={onReview}>
        Eksik pozları incele</button><span className="hint">
          Resmî maliyet taslakları aşağıdaki gelişmiş işlemlerdedir.</span></div>
    </>}
  </section>;
}
