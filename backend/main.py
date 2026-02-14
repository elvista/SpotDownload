import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from database import init_db, SessionLocal
from config import settings as app_config
from routers import playlists, downloads, monitor
from routers import settings as settings_router
from services.monitor import MonitorService

logger = logging.getLogger("spotdownload")

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
                logger.info(
                    f"Playlist '{r.get('playlist_name')}': {r['added']} new tracks found!"
                )
    except Exception as e:
        logger.error(f"Scheduled check failed: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    scheduler.add_job(
        scheduled_check,
        "interval",
        minutes=app_config.MONITOR_INTERVAL_MINUTES,
        id="playlist_monitor",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Background monitor started (every {app_config.MONITOR_INTERVAL_MINUTES} min)"
    )
    yield
    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="SpotDownload", version="1.0.0", lifespan=lifespan)

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


@app.get("/api/health")
def health():
    return {"status": "ok", "monitor_running": scheduler.running}
