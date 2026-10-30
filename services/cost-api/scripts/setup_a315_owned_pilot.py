"""Local operator helper for an isolated, fixed owned synthetic fixture."""
import argparse
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.chdir(BASE)

from sqlalchemy import select  # noqa: E402

from app.a3_owned_pilot import setup_owned_pilot  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402,F401 - register all model tables
from app.models import User  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Create isolated ARKEMX-owned plaster fixture")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email))
        if user is None:
            raise SystemExit("Yerel hesap bulunamadi. Islem yapilmadi.")
        result = setup_owned_pilot(db, user)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("SENTETIK PILOT HAZIR. Gercek katalog izinleri ve mevcut projeler degistirilmedi.")


if __name__ == "__main__":
    main()
