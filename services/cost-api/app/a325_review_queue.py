"""A3.25: one fail-closed technical work queue for PDF-derived poz candidates.

"prechecked" means *rule checks only*. It is not an engineer's approval and
never authorizes price calculations. Persisted selections are candidate picks.
"""
from __future__ import annotations

from .matching import family

EXPLICIT_MISSING = {
    "GAZBETON_STRENGTH_N_MM2_UNVERIFIED": "Gazbeton dayanımı (N/mm²)",
    "GAZBETON_DENSITY_KG_M3_UNVERIFIED": "Gazbeton yoğunluğu (kg/m³)",
    "CONCRETE_CLASS_UNVERIFIED": "Beton sınıfı",
    "PAINT_BASE_UNVERIFIED": "Boya türü",
    "METRAJ_INPUT_REVIEW_REQUIRED": "Metraj miktarı veya girilen bilgi",
    "THICKNESS_MM_UNVERIFIED": "Ürün kalınlığı",
    "JOINT_WIDTH_MM_UNVERIFIED": "Derz aralığı",
    "PLASTER_LAYER_UNVERIFIED": "Sıva katmanı (kaba/ince)",
    "PLASTER_BINDER_UNVERIFIED": "Sıva harcı türü",
    "PLASTER_CEMENT_DOSAGE_UNVERIFIED": "Çimento dozajı",
    "PLASTER_CEMENT_DOSAGE_AMBIGUOUS": "Çimento dozajı (belirsiz)",
}


def classify_row(
    *,
    description: str,
    candidates: list[dict],
    saved_selection: dict | None,
    clarification: dict | None,
    related_excel_rows: list[int],
    quantity_known: bool,
    unit_known: bool,
    input_review_required: bool,
) -> dict:
    """Classify an existing match, without making any automatic decisions."""
    saved_code = (
        saved_selection.get("code")
        if saved_selection and saved_selection.get("current") is True else None
    )
    selected = next((candidate for candidate in candidates
                     if candidate.get("code") == saved_code), None)
    top = selected or (candidates[0] if candidates else None)

    missing: list[str] = []
    if not quantity_known or input_review_required:
        missing.append("Metraj miktarı veya giriş bilgisi")
    if not unit_known:
        missing.append("Ölçü birimi")
    if clarification and family(description) == "seramik":
        missing.append("Seramik türü (mimari şartname)")
    if top:
        for flag in top.get("review_flags", []):
            field = EXPLICIT_MISSING.get(flag)
            if field and field not in missing:
                missing.append(field)
    if missing:
        return {
            "group": "needs_info", "reason": " · ".join(missing[:3]),
            "missing_fields": missing,
            "engineering_approved": False, "cost_allowed": False,
        }
    if related_excel_rows:
        return {
            "group": "needs_review",
            "reason": "Birleşik sıva pozunun kapsamı kontrol edilmeli",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    if not candidates:
        return {
            "group": "needs_review", "reason": "Uygun poz bulunamadı",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    if saved_selection and saved_selection.get("stale"):
        return {
            "group": "needs_review", "reason": "Önceki poz seçimi geçersiz; yeniden incele",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    if not saved_code:
        return {
            "group": "needs_review", "reason": "Poz henüz inceleme için kaydedilmedi",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    if selected is None:
        return {
            "group": "needs_review", "reason": "Kaydedilmiş poz güncel adaylarda doğrulanamadı",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    if selected.get("technical_status") != "compatible" or selected.get("blockers") or (
        selected.get("review_flags") or selected.get("possible_shared_scope")
    ):
        return {
            "group": "needs_review", "reason": "Pozun teknik kapsamı ayrıca kontrol edilmeli",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    if any(candidate.get("code") != saved_code and
           candidate.get("technical_status") != "blocked" for candidate in candidates):
        return {
            "group": "needs_review", "reason": "Alternatif pozlar arasında teknik seçim kontrol edilmeli",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    if not selected.get("source_price_verified"):
        return {
            "group": "needs_review", "reason": "Kaynak fiyat doğrulaması eksik",
            "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
        }
    return {
        "group": "prechecked", "reason": "Kontrol edilen özellikler eşleşiyor",
        "missing_fields": [], "engineering_approved": False, "cost_allowed": False,
    }
