"""Portable Windows pilot: frozen API + exported frontend, no Node/Python install.

Mutable data lives outside the one-file extraction directory. The local server
is bound only to loopback and is stopped when the control window closes.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser


def resources():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def configure(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    # A persistent random signing secret keeps sessions local to this copy.
    secret_file = data_dir / "session.key"
    if not secret_file.exists():
        try:
            with secret_file.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
    secret = secret_file.read_text(encoding="utf-8").strip()
    if len(secret) < 32:
        raise RuntimeError("Oturum anahtarı okunamadı. Veri klasörünü koruyarak destek alın.")
    database = data_dir / "arkemx-pilot.db"
    upload_dir = str(data_dir / "uploads")
    if os.name == "nt" and not upload_dir.startswith("\\\\?\\"):
        upload_dir = "\\\\?\\UNC\\" + upload_dir[2:] if upload_dir.startswith("\\\\") else "\\\\?\\" + upload_dir
    os.environ.update(
        ENVIRONMENT="development", JWT_SECRET=secret,
        DATABASE_URL="sqlite:///" + database.as_posix(),
        UPLOAD_DIR=upload_dir, CORS_ORIGINS="",
        ARKEMX_ENABLE_M6_PILOT="0",
    )
    # Do not inherit paths to an unrelated developer's private PDF sources.
    for key in ("ARKEMX_PDF", "ARKEMX_ANALYSIS_PDF", "ARKEMX_AUXILIARY_PDF", "ARKEMX_ALT_PDF"):
        os.environ.pop(key, None)
    log = data_dir / "application.log"
    logging.basicConfig(filename=log, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8", force=True)
    return database


class Pilot:
    def __init__(self, data_dir, port):
        self.data_dir, self.port = data_dir, port
        self.url = f"http://127.0.0.1:{port}"
        self.server = None
        self.thread = None
        self.error = None
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.sock = None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self):
        database = configure(self.data_dir)
        # Lock a listening socket before migrations, rejecting a duplicate launch.
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.bind(("127.0.0.1", self.port))
            self.sock.listen(128)
        except OSError:
            self.sock.close()
            raise RuntimeError(f"{self.port} bağlantısı kullanımda. Açık ARKEMX penceresini kapatıp tekrar deneyin.") from None
        if database.exists():
            backups = self.data_dir / "backups"
            backups.mkdir(exist_ok=True)
            with sqlite3.connect(database) as source, sqlite3.connect(backups / f"pilot-{time.time_ns()}.db") as target:
                source.backup(target)
        root = resources()
        api_root = root / "api" if getattr(sys, "frozen", False) else root / "services" / "cost-api"
        web_root = root / "web" if getattr(sys, "frozen", False) else root / "apps" / "web" / ".next-desktop"
        if not web_root.joinpath("index.html").is_file():
            raise RuntimeError("Paketin arayüz dosyaları bulunamadı.")
        from alembic import command
        from alembic.config import Config
        from app.main import app
        from fastapi.staticfiles import StaticFiles
        from starlette.responses import JSONResponse
        config = Config()
        config.set_main_option("script_location", str(api_root / "alembic"))
        config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"].replace("%", "%%"))
        command.upgrade(config, "head")

        @app.get("/api/desktop/health")
        def desktop_health():
            return {"product": "ARKEMX Desktop Pilot", "ready": True, "version": "1.0.0"}

        # A nonexistent API request must never fall through to HTML.
        @app.api_route("/api/{unmatched:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
        def missing_api(unmatched: str):
            return JSONResponse({"detail": "API route not found"}, status_code=404)

        app.mount("/", StaticFiles(directory=web_root, html=True), name="desktop-frontend")
        import uvicorn
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_config=None,
            access_log=False, loop="asyncio", http="h11", ws="none",
            timeout_graceful_shutdown=5,
        ))

        def serve():
            try:
                self.server.run(sockets=[self.sock])
            except BaseException:
                self.error = traceback.format_exc()
                logging.exception("Local server stopped")

        self.thread = threading.Thread(target=serve, daemon=True, name="arkemx-local-api")
        self.thread.start()
        for _ in range(120):
            if self.stop_event.is_set():
                return
            if not self.thread.is_alive():
                raise RuntimeError("Uygulama başlatılamadı. application.log dosyasını kontrol edin.")
            try:
                with self.http.open(self.url + "/api/desktop/health", timeout=0.5) as response:
                    if json.load(response).get("ready") is True:
                        self.ready.set()
                        return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("Uygulama zamanında yanıt vermedi.")

    def stop(self):
        self.stop_event.set()
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=7)
        if self.sock:
            self.sock.close()


def main():
    parser = argparse.ArgumentParser(description="ARKEMX Desktop Pilot")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=18020)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError("Geçersiz bağlantı numarası")
    default_dir = Path(sys.executable).parent / "ARKEMX-verileri" if getattr(sys, "frozen", False) else resources() / "work" / "desktop-data"
    pilot = Pilot((args.data_dir or default_dir).resolve(), args.port)
    if args.headless:
        try:
            pilot.start()
            while pilot.thread and pilot.thread.is_alive():
                time.sleep(0.25)
        finally:
            pilot.stop()
        return

    import tkinter as tk
    from tkinter import ttk, messagebox
    window = tk.Tk()
    window.title("ARKEMX · Maliyet Pilotu")
    window.geometry("510x310")
    window.minsize(460, 290)
    window.configure(bg="#f1f5fb")
    status = tk.StringVar(value="Uygulama hazırlanıyor…")
    heading = tk.Label(window, text="ARKEMX", bg="#142a4c", fg="white", font=("Segoe UI", 23, "bold"), pady=18)
    heading.pack(fill="x")
    tk.Label(window, text="Kaynaklı maliyet pilotu", bg="#f1f5fb", fg="#142a4c", font=("Segoe UI", 13, "bold"), pady=12).pack()
    tk.Label(window, textvariable=status, bg="#f1f5fb", fg="#334155", wraplength=450, font=("Segoe UI", 10)).pack(pady=5)
    buttons = ttk.Frame(window)
    buttons.pack(pady=17)
    open_button = ttk.Button(buttons, text="Uygulamayı aç", state="disabled", command=lambda: webbrowser.open(pilot.url))
    open_button.pack(side="left", padx=5)
    ttk.Button(buttons, text="Veri klasörü", command=lambda: os.startfile(pilot.data_dir)).pack(side="left", padx=5)

    def close():
        if not outcome.get("ready") and "error" not in outcome:
            outcome["close_requested"] = True
            status.set("Başlatma tamamlandıktan sonra kapatılacak…")
            return
        status.set("Kapatılıyor…")
        open_button.configure(state="disabled")
        window.update_idletasks()
        pilot.stop()
        window.destroy()

    ttk.Button(buttons, text="Kapat", command=close).pack(side="left", padx=5)
    tk.Label(window, text="Veriler bu EXE'nin yanındaki ARKEMX-verileri klasöründe saklanır.", bg="#f1f5fb", fg="#64748b", wraplength=455, font=("Segoe UI", 9)).pack()
    window.protocol("WM_DELETE_WINDOW", close)
    outcome = {}

    def initialize():
        try:
            pilot.start()
            outcome["ready"] = True
        except BaseException:
            outcome["error"] = traceback.format_exc()
            logging.exception("Desktop startup failed")

    threading.Thread(target=initialize, daemon=True).start()

    def check():
        if outcome.get("close_requested") and (outcome.get("ready") or "error" in outcome):
            close()
        elif "error" in outcome:
            status.set("Açılamadı. Veri klasöründeki application.log dosyasını kontrol edin.")
            messagebox.showerror("ARKEMX", outcome["error"].splitlines()[-1], parent=window)
        elif outcome.get("ready"):
            status.set("Hazır. Uygulama tarayıcınızda çalışır.")
            open_button.configure(state="normal")
            if not args.no_browser:
                webbrowser.open(pilot.url)
        else:
            window.after(150, check)
    window.after(150, check)
    window.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        main()
    except Exception:
        logging.exception("ARKEMX failed")
        if "--headless" not in sys.argv:
            from tkinter import messagebox
            messagebox.showerror("ARKEMX", "Uygulama açılamadı. Veri klasöründeki application.log dosyasını kontrol edin.")
        sys.exit(1)
