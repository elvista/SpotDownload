import os
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import AppSetting
from config import settings as default_settings

router = APIRouter(tags=["settings"])

DEFAULT_DOWNLOAD_PATH = str(Path.home() / "Music" / "SpotDownload")


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


class UpdateSettingsRequest(BaseModel):
    download_path: str | None = None
    monitor_interval_minutes: int | None = None


class ValidatePathResponse(BaseModel):
    path: str
    exists: bool
    writable: bool
    created: bool


@router.get("/settings", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    download_path = get_setting(db, "download_path", DEFAULT_DOWNLOAD_PATH)
    monitor_interval = get_setting(
        db, "monitor_interval_minutes",
        str(default_settings.MONITOR_INTERVAL_MINUTES),
    )
    return SettingsResponse(
        download_path=download_path,
        monitor_interval_minutes=int(monitor_interval),
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(body: UpdateSettingsRequest, db: Session = Depends(get_db)):
    if body.download_path is not None:
        # Expand ~ and resolve
        resolved = str(Path(body.download_path).expanduser().resolve())
        # Create directory if it doesn't exist
        os.makedirs(resolved, exist_ok=True)
        set_setting(db, "download_path", resolved)

    if body.monitor_interval_minutes is not None:
        set_setting(
            db, "monitor_interval_minutes", str(body.monitor_interval_minutes)
        )

    return get_settings(db)


@router.post("/settings/validate-path", response_model=ValidatePathResponse)
def validate_path(body: UpdateSettingsRequest, db: Session = Depends(get_db)):
    """Check if a path exists and is writable, optionally create it."""
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
