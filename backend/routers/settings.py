import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import DEFAULT_DOWNLOAD_PATH
from config import settings as app_config
from database import get_db
from models import AppSetting

router = APIRouter(tags=["settings"])


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def set_setting(db: Session, key: str, value: str):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


class SettingsResponse(BaseModel):
    download_path: str
    monitor_interval_minutes: int
    archive_playlist_name: str


class UpdateSettingsRequest(BaseModel):
    download_path: str | None = None
    monitor_interval_minutes: int | None = None
    archive_playlist_name: str | None = None


class ValidatePathResponse(BaseModel):
    path: str
    exists: bool
    writable: bool
    created: bool


@router.get("/settings", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    download_path = get_setting(db, "download_path", DEFAULT_DOWNLOAD_PATH)
    monitor_interval = get_setting(
        db,
        "monitor_interval_minutes",
        str(app_config.MONITOR_INTERVAL_MINUTES),
    )
    archive_playlist_name = get_setting(db, "archive_playlist_name", "DJ Archive")
    return SettingsResponse(
        download_path=download_path,
        monitor_interval_minutes=int(monitor_interval),
        archive_playlist_name=archive_playlist_name,
    )


def _validate_download_path(raw: str) -> str:
    """Resolve path and ensure it is under user home (no path traversal)."""
    if ".." in raw:
        raise ValueError("Download path must not contain '..'")
    resolved = Path(raw).expanduser().resolve()
    try:
        resolved_str = str(resolved)
        home = str(Path.home().resolve())
        if not resolved_str.startswith(home):
            raise ValueError("Download path must be under your home directory")
    except (ValueError, OSError) as e:
        raise ValueError(f"Invalid download path: {e}") from e
    return resolved_str


@router.put("/settings", response_model=SettingsResponse)
def update_settings(body: UpdateSettingsRequest, db: Session = Depends(get_db)):
    if body.download_path is not None:
        try:
            resolved = _validate_download_path(body.download_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        os.makedirs(resolved, exist_ok=True)
        set_setting(db, "download_path", resolved)

    if body.monitor_interval_minutes is not None:
        set_setting(db, "monitor_interval_minutes", str(body.monitor_interval_minutes))

    if body.archive_playlist_name is not None:
        # Trim whitespace
        archive_name = body.archive_playlist_name.strip()
        if archive_name:
            set_setting(db, "archive_playlist_name", archive_name)

    return get_settings(db)


@router.post("/settings/validate-path", response_model=ValidatePathResponse)
def validate_path(body: UpdateSettingsRequest, db: Session = Depends(get_db)):
    raw_path = body.download_path or DEFAULT_DOWNLOAD_PATH
    resolved = str(Path(raw_path).expanduser().resolve())

    exists = os.path.isdir(resolved)
    created = False

    if not exists:
        try:
            os.makedirs(resolved, exist_ok=True)
            created = True
            exists = True
        except OSError:
            pass

    writable = os.access(resolved, os.W_OK) if exists else False

    return ValidatePathResponse(
        path=resolved,
        exists=exists,
        writable=writable,
        created=created,
    )
