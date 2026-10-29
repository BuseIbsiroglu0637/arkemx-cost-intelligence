"""Back up a local SQLite database before the additive assessment-history migration."""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.chdir(BASE)

from alembic.config import Config  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from app.database import engine  # noqa: E402


def main():
    config = Config(str(BASE / "alembic.ini"))
    if ScriptDirectory.from_config(config).get_current_head() != "0012_a3_review_assessments":
        raise SystemExit("Beklenmeyen migration zinciri. Islem yapilmadi.")
    with engine.connect() as connection:
        heads = MigrationContext.configure(connection).get_current_heads()
        if heads not in (("0011_a3_review_records",), ("0012_a3_review_assessments",)):
            raise SystemExit("Veritabani beklenen 0011/0012 surumunde degil. Islem yapilmadi.")
        if heads == ("0012_a3_review_assessments",):
            print("A3.13 veritabani zaten hazir.")
            return
        if engine.dialect.name == "sqlite":
            directory = Path(tempfile.mkdtemp(prefix="arkemx-a313-db-backup-"))
            destination = directory / "arkemx-before-a313.sqlite"
            with sqlite3.connect(destination) as backup:
                connection.connection.driver_connection.backup(backup)
            print(f"SQLite yedegi: {destination}")
        else:
            print("SQLite disi veritabani: bu betik yedek olusturmaz; yalnizca yeni degerlendirme tablosu eklenir.")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BASE, check=True)
    print("A3.13 VERITABANI HAZIR. API sunucusunu yeniden baslatabilirsin.")


if __name__ == "__main__":
    main()
