"use client";

import styles from "./review.module.css";

export type SourceCompletion = {
  schema: "arkemx.a347.completion.v1";
  read_only: true; engineering_approved: false; cost_allowed: false;
  project_id: string; import_id: string; import_sha256: string;
  work_item_id: string; source_row: number; revision_id: string|null;
  spec_sha256: string|null; pdf_sha256: string|null;
  candidate_code: string|null; candidate_found_in_pdf: boolean;
  document_state: string;
  status: "conflicting"|"no_document"|"unreadable"|"not_found"|
    "facts_found"|"partially_supported"|"documented_for_review";
  message: string;
  fields: {
    key: string;label:string;excel_value:string|number|null;pdf_value:string|number|null;
    candidate_value:string|number|null;status:"conflict"|"missing"|"supported"|"candidate_unverified";
    suggested_from_spec:string|number|null;page:number|null;quote:string|null;
    conflicting_values:string[];
  }[];
  missing_fields:string[];technical_blockers:string[];
  scope_conflict:string|null;
  possible_special_analysis:boolean;next_step:string;
};

function value(input: string|number|null) {
  return input===null?"Belirtilmedi":String(input);
}

export default function SourceFactCard({data}:{data:SourceCompletion}){
  const hasConflict=data.status==="conflicting";
  const supported=data.fields.filter(x=>x.status==="supported").length;
  const proposed=data.fields.filter(x=>x.suggested_from_spec!==null).length;
  return <section className={styles.a347Facts} aria-label="Şartnameden otomatik teknik bilgi tamamlama">
    <div className={styles.a347FactHeading}>
      <div>
        <strong>Şartnameden teknik kontrol</strong>
        <small>{data.spec_sha256?
          `Proje PDF · SHA ${data.spec_sha256.slice(0,12)}…`:
          "Şartname henüz bağlı değil"}</small>
      </div>
      <span className={hasConflict?styles.a347ConflictLabel:styles.a347ReviewLabel}>
        {hasConflict?"Çelişki var":data.status==="documented_for_review"?
          "Belgeyle destekli":data.status==="no_document"?
          "Belge gerekli":data.status==="not_found"?"Bilgi bulunamadı":"İnceleme gerekli"}
      </span>
    </div>
    <p>{data.message}</p>
    {data.fields.length>0 && <div className={styles.a347FieldList}>
      {data.fields.map(field=><div key={field.key} className={styles.a347Field}>
        <strong>{field.label}</strong>
        <span>{field.status==="conflict"?"Çelişkili bilgiler":
          field.status==="supported"?"Kaynakla destekli":
          field.status==="candidate_unverified"?"Poz tarifi eksik":"Şartnamede bulunamadı"}</span>
        <small>Excel: {value(field.excel_value)} · Poz: {value(field.candidate_value)}</small>
        {field.pdf_value!==null&&<small>
          Şartname: <b>{value(field.pdf_value)}</b>
          {field.page!==null?` · PDF sayfa ${field.page}`:""}
          {field.suggested_from_spec!==null?" · Excel'de eksik, belge önerisi":""}
        </small>}
        {field.conflicting_values.length>0&&<small>
          Çelişen değerler: {field.conflicting_values.join(", ")}
        </small>}
      </div>)}
    </div>}
    <div className={styles.a347Summary}>
      {hasConflict?
        "Teknik çelişki çözülmeden bu pozla ilerleme.":
        `${supported} alan belgeyle destekli; ${proposed} eksik Excel alanına kanıt önerildi. Mühendis kontrolü gerekli.`}
    </div>
    {data.possible_special_analysis&&<p className={styles.a347Special}>
      Bu PDF'de seçili doğrulanmış poz yok. Önce diğer resmî katalogları kontrol et;
      uygun poz bulunmazsa kaynağı ve rayiçleri belgeli özel analiz hazırlamak gerekebilir.
      Bu ekran özel poz üretmez veya fiyat atamaz.
    </p>}
    <details>
      <summary>Teknik PDF alıntılarını göster</summary>
      {data.fields.filter(x=>x.quote&&x.page).map(field=><blockquote key={field.key}>
        <small>PDF sayfa {field.page} · {field.label}</small>
        <p>{field.quote}</p>
      </blockquote>)}
      {!data.fields.some(x=>x.quote)&&<p>Bu kalem için kaynak alıntısı bulunamadı.</p>}
    </details>
    <small className={styles.a347Disclaimer}>
      Kaynaklı öneri teknik onay değildir; M5 maliyet kaydı oluşturmaz.
    </small>
  </section>;
}
