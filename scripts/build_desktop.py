"""Build the distributable on Windows using the existing locked API environment."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import importlib.metadata as metadata
import argparse

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parents[0] / "desktop-build"
OUTPUT = ROOT.parents[1] / "outputs"
API = ROOT / "services" / "cost-api"
WEB = ROOT / "apps" / "web"


def main():
    if os.name != "nt":
        raise RuntimeError("Build this Windows executable on Windows.")
    WORK.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    env = {**os.environ, "ARKEMX_DESKTOP_BUILD": "1", "NEXT_PUBLIC_API_URL": ""}
    node = shutil.which("node")
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-web", action="store_true", help="Reuse an already verified desktop static export")
    if not parser.parse_args().skip_web:
        subprocess.run([node, str(WEB / "node_modules/next/dist/bin/next"), "build"], cwd=WEB, env=env, check=True)
    exported = WEB / ".next-desktop"
    if not exported.joinpath("index.html").is_file():
        raise RuntimeError("Desktop static export is missing")
    if any("http://127.0.0.1:8000" in p.read_text(encoding="utf-8") for p in exported.rglob("*.js")):
        raise RuntimeError("Desktop export still points to the developer API")
    notices = WORK / "THIRD_PARTY_NOTICES.txt"
    records = ["ARKEMX Desktop Pilot — bundled runtime components and license notices\n",
               "Python: https://www.python.org/psf/license/\n",
               "Next.js/React: MIT; source package license texts follow.\n"]
    for name in ("fastapi", "starlette", "sqlalchemy", "alembic", "pymupdf", "uvicorn", "openpyxl", "pyjwt", "argon2-cffi", "pydantic", "pyinstaller"):
        dist = metadata.distribution(name)
        records.append(f"\n{name} {dist.version}: {dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'see package license'}\n")
        for item in dist.files or []:
            if any(part.lower() in ("licenses", "license", "copying", "license.txt", "license.md") for part in item.parts):
                path = dist.locate_file(item)
                if path.is_file() and path.stat().st_size < 200_000:
                    records.append(path.read_text(encoding="utf-8", errors="replace"))
    for name in ("next", "react", "react-dom"):
        path = WEB / "node_modules" / name / "LICENSE"
        if path.exists():
            records.extend([f"\n{name}\n", path.read_text(encoding="utf-8")])
    notices.write_text("\n".join(records), encoding="utf-8")
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
            "--name", "ARKEMX-Pilot", "--distpath", str(OUTPUT),
            "--manifest", str(ROOT / "scripts/desktop.manifest"),
            "--workpath", str(WORK / "pyinstaller"), "--specpath", str(WORK),
            "--paths", str(API), "--collect-submodules", "app",
            "--collect-all", "pymupdf", "--collect-submodules", "uvicorn",
            "--hidden-import", "sqlalchemy.dialects.sqlite",
            "--hidden-import", "sqlalchemy.dialects.sqlite.pysqlite",
            "--copy-metadata", "pymupdf", "--copy-metadata", "alembic",
            "--add-data", f"{exported};web",
            "--add-data", f"{notices};.",
            "--exclude-module", "pytest", "--exclude-module", "psycopg",
            "--exclude-module", "IPython"]
    for path in (API / "alembic").rglob("*.py"):
        if "__pycache__" not in path.parts:
            destination = "api/" + str(path.parent.relative_to(API)).replace("\\", "/")
            args.extend(["--add-data", f"{path};{destination}"])
    args.append(str(ROOT / "scripts/desktop_pilot.py"))
    subprocess.run(args, cwd=ROOT, check=True)
    shutil.copy2(notices, OUTPUT / "EXE_THIRD_PARTY_NOTICES.txt")


if __name__ == "__main__":
    main()
