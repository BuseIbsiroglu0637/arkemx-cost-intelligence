"use client";

import Link from "next/link";
import styles from "./workflow-nav.module.css";

export type WorkflowSection = "overview" | "metraj" | "technical" | "cost" | "catalog";

const sections: { id: WorkflowSection; title: string; hint: string }[] = [
  { id: "overview", title: "Proje özeti", hint: "Nerede kaldım?" },
  { id: "metraj", title: "Metraj", hint: "Excel ve düzeltmeler" },
  { id: "technical", title: "Teknik inceleme", hint: "Adaylar, farklar ve kanıtlar" },
  { id: "cost", title: "Maliyet", hint: "Taslak ve karşılaştırmalar" },
  { id: "catalog", title: "Kaynaklar", hint: "Katalog ve PDF belgeleri" },
];

export default function WorkflowNav({ active, onSelect }: {
  active: WorkflowSection;
  onSelect?: (section: WorkflowSection) => void;
}) {
  return <nav className={styles.nav} aria-label="ARKEMX çalışma alanları">
    {sections.map(section => onSelect ?
      <button key={section.id} type="button" className={styles.item}
        aria-current={active === section.id ? "page" : undefined}
        onClick={() => onSelect(section.id)}>
        <span>{section.title}</span><small>{section.hint}</small>
      </button> :
      <Link key={section.id} href={`/#${section.id}`} className={styles.item}
        aria-current={active === section.id ? "page" : undefined}>
        <span>{section.title}</span><small>{section.hint}</small>
      </Link>)}
  </nav>;
}
