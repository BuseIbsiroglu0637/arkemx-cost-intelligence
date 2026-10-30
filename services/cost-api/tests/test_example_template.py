"""The downloadable Excel example must be accepted by the real metraj parser."""
from pathlib import Path

from app.excel import read_metraj


def test_published_example_xlsx_is_valid_and_importable():
    repository = Path(__file__).resolve().parents[3]
    example = repository / "apps/web/public/templates/arkemx-metraj-ornek.xlsx"
    assert example.is_file(), "The downloadable Excel template is missing"

    parsed = read_metraj(example.read_bytes())
    assert parsed["sheet"] == "Metraj"
    assert parsed["headers"] == ["İmalat Açıklaması", "Miktar", "Birim"]
    assert parsed["row_count"] == 6
    assert parsed["review_count"] == 0
    assert parsed["mapping"] == {
        "description": "İmalat Açıklaması",
        "quantity": "Miktar",
        "unit": "Birim",
    }
