import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings as app_config
from database import SessionLocal, init_db
from routers import auth, downloads, export_import, monitor, playlists
from routers import settings as settings_router
from services.monitor import MonitorService

logger = logging.getLogger("spotdownload")


def _exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Centralized handler: preserve HTTPException, log and return 500 for rest."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail if isinstance(exc.detail, str) else str(exc.detail)},
        )
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."},
    )

scheduler = BackgroundScheduler()
monitor_service = MonitorService()


def scheduled_check():
    """Background job that checks all monitored playlists for changes."""
    logger.info("Running scheduled playlist check...")
    db = SessionLocal()
    try:
        results = monitor_service.check_all(db)
        for r in results:
            if r.get("added", 0) > 0:
                logger.info(f"Playlist '{r.get('playlist_name')}': {r['added']} new tracks found!")
    except Exception as e:
        logger.error(f"Scheduled check failed: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(
        scheduled_check,
        "interval",
        minutes=app_config.MONITOR_INTERVAL_MINUTES,
        id="playlist_monitor",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Background monitor started (every {app_config.MONITOR_INTERVAL_MINUTES} min)")
    yield
    scheduler.shutdown()


app = FastAPI(title="SpotDownload", version="1.0.0", lifespan=lifespan)

app.add_exception_handler(Exception, _exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(playlists.router, prefix="/api")
app.include_router(downloads.router, prefix="/api")
app.include_router(monitor.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(export_import.router, prefix="/api")
app.include_router(auth.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "monitor_running": scheduler.running}
