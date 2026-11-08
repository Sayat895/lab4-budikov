import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from controllers import auth, branches, dashboard, employees, reports, shifts
from desktop_api import DesktopApi
from db import Database
from tls_config import certificate_directory


FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
load_dotenv(Path(__file__).parent.parent / ".env")
os.environ.setdefault("DB_PORT", "5433")
TLS_DIR = certificate_directory()
TLS_CERTIFICATE = TLS_DIR / "server.crt"
TLS_PRIVATE_KEY = TLS_DIR / "server-key.pem"


def create_app(database=None, initialize_database=True, frontend_dist=FRONTEND_DIST):
    database = database or Database()

    @asynccontextmanager
    async def lifespan(_app):
        if initialize_database:
            database.initialize_when_ready()
        yield

    application = FastAPI(
        title="Управление филиалом",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.sessions = {}
    for controller in (
        auth.router,
        dashboard.router,
        branches.router,
        employees.router,
        shifts.router,
        reports.router,
    ):
        application.include_router(controller)

    application.get("/api/health", tags=["system"])(lambda: {"status": "ok"})
    assets = frontend_dist / "assets"
    if assets.is_dir():
        from fastapi.staticfiles import StaticFiles

        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/", include_in_schema=False)
    def frontend():
        index_file = frontend_dist / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=503, detail="React UI is not built.")
        return FileResponse(index_file)

    return application


app = create_app()


def main():
    if not (FRONTEND_DIST / "index.html").is_file():
        raise FileNotFoundError(
            "React UI is not built. Run `npm --prefix frontend install` and "
            "`npm --prefix frontend run build` first."
        )
    if not TLS_CERTIFICATE.is_file() or not TLS_PRIVATE_KEY.is_file():
        raise FileNotFoundError(
            "Local HTTPS certificate is missing. Run `python app\\setup_https.py` first."
        )

    host = "127.0.0.1"
    port = int(os.getenv("APP_API_PORT", "8000"))
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=os.getenv("APP_LOG_LEVEL", "info").lower(),
            access_log=False,
            ssl_certfile=str(TLS_CERTIFICATE),
            ssl_keyfile=str(TLS_PRIVATE_KEY),
        )
    )
    server_thread = threading.Thread(target=server.run, name="rest-api", daemon=True)
    server_thread.start()
    deadline = time.monotonic() + 130
    while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.1)
    if not server.started:
        server.should_exit = True
        server_thread.join(timeout=5)
        raise RuntimeError("REST API did not start. Check the database and application logs.")

    import webview

    try:
        desktop_api = DesktopApi()
        window = webview.create_window(
            "Управление филиалом",
            f"https://{host}:{port}/?desktop=1",
            js_api=desktop_api,
            width=1280,
            height=800,
            min_size=(960, 640),
            background_color="#f5f5f2",
        )
        desktop_api._window = window
        webview.start()
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)


if __name__ == "__main__":
    main()
