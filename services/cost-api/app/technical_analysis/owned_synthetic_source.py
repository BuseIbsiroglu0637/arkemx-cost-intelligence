"""ARKEMX-authored fixture. Not an official position, licence grant or price."""
import hashlib
import json

CODE = "DEMO-ARKEMX-SIVA-01"
VERSION = "ARKEMX-A315-SYNTHETIC-v1"
TEXT = (
    "240 kg cimento dozlu 12 mm kaba siva uzerine "
    "320 kg cimento dozlu 4 mm ince siva"
)
UNIT = "m²"
YEAR = 2026


def fixture_identity() -> dict:
    return {"kind": "synthetic_owned", "source_id": VERSION, "position_code": CODE,
            "description": TEXT, "unit": UNIT, "price": None, "official": False}


def fixture_sha256() -> str:
    payload = json.dumps(fixture_identity(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def read_fixture() -> dict:
    return {"position_code": CODE, "unit": UNIT, "read_only": True, "approval_allowed": False,
            "technical_description": {"quote": TEXT}, "totals": {"total": None, "currency": None},
            "source": {"kind": "synthetic_owned", "source_id": VERSION, "sha256": fixture_sha256(),
                       "official": False, "price_date": None}}
