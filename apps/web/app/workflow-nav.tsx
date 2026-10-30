"use client";

import Link from "next/link";
import styles from "./workflow-nav.module.css";

export type WorkflowSection = "overview" | "metraj" | "technical" | "cost" | "catalog";

const sections: { id: WorkflowSection; title: string; hint: string }[] = [
  { id: "metraj", title: "1. Metraj", hint: "Excel ve düzeltmeler" },
  { id: "technical", title: "2. Pozları incele", hint: "Adaylar, farklar ve kanıtlar" },
  { id: "cost", title: "3. Maliyet", hint: "Taslak ve karşılaştırmalar" },
];

export default function WorkflowNav({ active, onSelect }: {
  active: WorkflowSection;
  onSelect?: (section: WorkflowSection) => void;
}) {
  return <nav className={styles.nav} aria-label="Proje çalışma adımları">
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
