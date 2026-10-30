"""Set up and run an isolated local pilot. Never touches arkemx-dev.db."""
from pathlib import Path
import os
import hashlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
import argparse

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "cost-api"
WEB = ROOT / "apps" / "web"
API_PORT, WEB_PORT = 18010, 13010
API_URL, WEB_URL = f"http://127.0.0.1:{API_PORT}", f"http://127.0.0.1:{WEB_PORT}"
ENVIRONMENT = os.environ.copy()
ENVIRONMENT.update(ENVIRONMENT="development", NEXT_PUBLIC_API_URL=API_URL,
                   CORS_ORIGINS=WEB_URL, DATABASE_URL="sqlite:///./arkemx-pilot.db",
                   UPLOAD_DIR="./data/pilot-uploads")


def run(args, cwd):
    subprocess.run(args, cwd=cwd, env=ENVIRONMENT, check=True)


def npm(args):
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not executable:
        raise RuntimeError("Node.js 22 veya daha yenisini kurun; npm bulunamadi.")
    command = [executable, *args]
    if os.name == "nt":
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
    run(command, WEB)


def wait(url, process):
    for _ in range(90):
        if process.poll() is not None:
            raise RuntimeError("Uygulama baslatilamadi. .pilot-logs klasorunu kontrol edin.")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("Uygulama zamaninda yanit vermedi. .pilot-logs klasorunu kontrol edin.")


def main(open_browser=True):
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 veya daha yenisi gerekli.")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 22 veya daha yenisi gerekli.")
    for port in (API_PORT, WEB_PORT):
        with socket.socket() as connection:
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"{port} portu kullanimda. Once acik pilotu kapatin.")
    environment = API / ".venv-pilot"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    stamp = environment / ".pilot-installed"
    if not python.exists():
        print("Ilk kurulum: uygulama ortami hazirlaniyor...", flush=True)
        venv.create(environment, with_pip=True)
    lock = API / "requirements-pilot.lock.txt"
    wanted = lock.read_bytes()
    if not stamp.exists() or stamp.read_bytes() != wanted:
        run([str(python), "-m", "pip", "install", "-r", str(lock)], API)
        run([str(python), "-m", "pip", "install", "-e", ".", "--no-deps"], API)
        stamp.write_bytes(wanted)
    if not (WEB / "node_modules" / ".package-lock.json").exists():
        print("Web paketleri kuruluyor...", flush=True)
        npm(["ci", "--no-audit", "--no-fund"])
    database = API / "arkemx-pilot.db"
    if database.exists():
        # sqlite backup API also handles a WAL database consistently.
        import sqlite3
        backup = API / "data" / "pilot-backups" / f"pilot-{time.time_ns()}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
            source.backup(target)
    run([str(python), "-m", "alembic", "upgrade", "head"], API)
    build_hash = hashlib.sha256(API_URL.encode())
    inputs = sorted((WEB / "app").rglob("*")) + [WEB / "package-lock.json", WEB / "next.config.ts"]
    for path in inputs:
        if path.is_file():
            build_hash.update(str(path.relative_to(WEB)).encode())
            build_hash.update(path.read_bytes())
    build_key = build_hash.hexdigest()
    build_stamp = WEB / ".next" / ".pilot-build"
    if (not (WEB / ".next" / "BUILD_ID").exists() or not build_stamp.exists()
            or build_stamp.read_text() != build_key):
        print("Arayuz ilk kez hazirlaniyor; birkac dakika surebilir...", flush=True)
        npm(["run", "build"])
        build_stamp.write_text(build_key)
    logs = ROOT / ".pilot-logs"
    logs.mkdir(exist_ok=True)
    processes = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with (logs / "api.log").open("a", encoding="utf-8") as api_log, (logs / "web.log").open("a", encoding="utf-8") as web_log:
            api = subprocess.Popen([str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT)],
                cwd=API, env=ENVIRONMENT, stdout=api_log, stderr=subprocess.STDOUT, creationflags=flags)
            processes.append(api)
            wait(API_URL + "/api/health", api)
            web = subprocess.Popen([node, str(WEB / "node_modules" / "next" / "dist" / "bin" / "next"),
                                    "start", "-H", "127.0.0.1", "-p", str(WEB_PORT)],
                cwd=WEB, env=ENVIRONMENT, stdout=web_log, stderr=subprocess.STDOUT, creationflags=flags)
            processes.append(web)
            wait(WEB_URL, web)
            print(f"Pilot hazir: {WEB_URL}\nKapatmak icin bu pencerede Ctrl+C kullanin.", flush=True)
            if open_browser:
                webbrowser.open(WEB_URL)
            while all(process.poll() is None for process in processes):
                time.sleep(1)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="ARKEMX local pilot")
        parser.add_argument("--no-browser", action="store_true", help="Do not open a browser during automated checks")
        main(open_browser=not parser.parse_args().no_browser)
    except KeyboardInterrupt:
        print("Pilot kapatildi.")
    except Exception as exc:
        print(f"Pilot acilamadi: {exc}")
        sys.exit(1)
