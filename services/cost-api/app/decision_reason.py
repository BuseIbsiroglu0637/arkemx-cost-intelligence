"""Validate rationale text for new human decisions; historical records unchanged."""
import re
import unicodedata
from fastapi import HTTPException

GENERIC = {
    "kendi gerekçem", "kendi gerekcem", "test gerekçesi", "test gerekcesi",
    "deneme gerekçesi", "deneme gerekcesi", "kontrol edildi", "uygun bulundu",
    "onay veriyorum", "gerekçe yazılacak", "gerekce yazilacak",
    "inceledim onaylıyorum", "incelendi onaylandı", "incelendi onaylandi",
}

def valid_decision_reason(reason: str | None) -> bool:
    if not isinstance(reason, str):
        return False
    value = " ".join(reason.split())
    if len(value) < 10 or len(value) > 500 or value.casefold() in GENERIC:
        return False
    words = re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)
    informative = {word.casefold() for word in words if len(word) >= 3}
    letters = sum(unicodedata.category(ch).startswith("L") for ch in value)
    return letters >= 12 and len(informative) >= 3

def require_decision_reason(reason: str | None) -> str:
    if not valid_decision_reason(reason):
        raise HTTPException(422, "Anlamlı teknik karar gerekçesi girin: en az üç farklı "
                            "kelime ve 12 harf. Sadece noktalama veya genel ifade kabul edilmez.")
    return " ".join(reason.split())
