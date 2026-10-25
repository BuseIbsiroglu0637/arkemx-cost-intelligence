"""Generate entirely synthetic quantity-takeoff test data. No official price codes."""
from pathlib import Path
from openpyxl import Workbook

out = Path(__file__).resolve().parents[1] / "example-data" / "demo-metraj.xlsx"
book = Workbook()
sheet = book.active
sheet.title = "Mimari Metraj"
sheet.append(["İmalat Açıklaması", "Miktar", "Birim"])
sheet.append(["Porselen seramik kaplama 60x60", "245,50", "m2"])
sheet.append(["Gazbeton duvar 10 cm", "1.234", "m2"])
sheet.append(["Hazır beton dökümü, sentetik örnek", "1.245,50", "m3"])
sheet.append(["Kapı montajı", 16, "adet"])
sheet.append(["Boya işleri, örnek", 120, "kutu"])
out.parent.mkdir(exist_ok=True)
book.save(out)
print(out)
