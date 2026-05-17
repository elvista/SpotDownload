"""Upscale section — REST + SSE for the library scanner (step 2).

Later PRs in this slice add pool scrapers, the A/B preview stream, the swap
engine, and the post-session Rekordbox prompt. This file only exposes the
scan + candidates surface today.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from config import settings as app_config
from database import get_db
from models import AppSetting, LibraryFile, ScanRun
from services import library_scanner

logger = logging.getLogger("cratedigger.upscale")

router = APIRouter(prefix="/upscale", tags=["upscale"])


# --- AppSetting keys ---------------------------------------------------------

SETTING_THRESHOLD = "upscale_bitrate_threshold_kbps"
SETTING_LIBRARY_ROOT = "upscale_library_root"

DEFAULT_THRESHOLD_KBPS = 192


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row and row.value else default


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def _resolved_library_root(db: Session) -> str:
    stored = _get_setting(db, SETTING_LIBRARY_ROOT, "")
    if stored:
        return stored
    return _get_setting(db, "download_path", app_config.DOWNLOAD_PATH)


def _resolved_threshold(db: Session) -> int:
    raw = _get_setting(db, SETTING_THRESHOLD, str(DEFAULT_THRESHOLD_KBPS))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD_KBPS


# --- SSE hub: one queue per scan_id ------------------------------------------


class _ScanHub:
    """Tiny pub/sub keyed by scan_id. Mirrors ``mixtape._SessionHub``."""

    def __init__(self) -> None:
        self._queues: dict[int, list[asyncio.Queue]] = {}

    def register(self, scan_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(scan_id, []).append(q)
        return q

    def unregister(self, scan_id: int, q: asyncio.Queue) -> None:
        lst = self._queues.get(scan_id)
        if not lst:
            return
        if q in lst:
            lst.remove(q)
        if not lst:
            del self._queues[scan_id]

    async def broadcast(self, scan_id: int, data: dict[str, Any]) -> None:
        for q in list(self._queues.get(scan_id, [])):
            await q.put(data)

    async def end(self, scan_id: int) -> None:
        for q in list(self._queues.get(scan_id, [])):
            await q.put(None)
        self._queues.pop(scan_id, None)


hub = _ScanHub()


# --- Pydantic models ---------------------------------------------------------


class ScanRequest(BaseModel):
    root: str | None = Field(
        default=None,
        description="Override the configured library root for this scan. Defaults to the stored setting.",
    )
    threshold_kbps: int | None = Field(
        default=None,
        ge=32,
        le=2048,
        description="Override the bitrate threshold for this scan. Defaults to the stored setting.",
    )


class ScanResponse(BaseModel):
    scan_id: int
    root: str
    threshold_kbps: int


class ScanRunResponse(BaseModel):
    id: int
    root_path: str
    started_at: str | None
    finished_at: str | None
    files_seen: int
    candidates: int
    error: str


class CandidateResponse(BaseModel):
    id: int
    abs_path: str
    bitrate_kbps: int
    size_bytes: int
    duration_s: float | None
    tag_title: str
    tag_artist: str
    tag_album: str
    last_scanned: str | None


class CandidatesPage(BaseModel):
    items: list[CandidateResponse]
    total: int
    limit: int
    offset: int
    threshold_kbps: int


class UpscaleSettings(BaseModel):
    library_root: str
    threshold_kbps: int


# --- Routes ------------------------------------------------------------------


@router.get("/settings", response_model=UpscaleSettings)
def get_upscale_settings(db: Session = Depends(get_db)) -> UpscaleSettings:
    return UpscaleSettings(
        library_root=_resolved_library_root(db),
        threshold_kbps=_resolved_threshold(db),
    )


@router.put("/settings", response_model=UpscaleSettings)
def update_upscale_settings(
    body: UpscaleSettings, db: Session = Depends(get_db)
) -> UpscaleSettings:
    root = body.library_root.strip()
    if not root:
        raise HTTPException(status_code=400, detail="library_root cannot be empty")
    if ".." in root:
        raise HTTPException(status_code=400, detail="library_root must not contain '..'")
    resolved = str(Path(root).expanduser().resolve())
    _set_setting(db, SETTING_LIBRARY_ROOT, resolved)
    _set_setting(db, SETTING_THRESHOLD, str(int(body.threshold_kbps)))
    db.commit()
    return UpscaleSettings(library_root=resolved, threshold_kbps=int(body.threshold_kbps))


@router.post("/scan", response_model=ScanResponse)
async def start_scan(
    body: ScanRequest | None = None, db: Session = Depends(get_db)
) -> ScanResponse:
    """Create a scan_runs row and kick off a background scan task."""
    body = body or ScanRequest()
    root = (body.root or _resolved_library_root(db)).strip()
    threshold = body.threshold_kbps if body.threshold_kbps is not None else _resolved_threshold(db)

    if not root:
        raise HTTPException(
            status_code=400,
            detail="No library root configured. Set one via PUT /api/upscale/settings.",
        )
    resolved_root = str(Path(root).expanduser().resolve())
    root_path = Path(resolved_root)
    if not root_path.exists() or not root_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Library root does not exist or is not a directory: {resolved_root}",
        )

    run = library_scanner.start_scan_run(db, resolved_root)
    scan_id = int(run.id)

    async def runner() -> None:
        async def send_event(data: dict[str, Any]) -> None:
            await hub.broadcast(scan_id, data)

        try:
            await library_scanner.scan_root(
                scan_id=scan_id,
                root_path=resolved_root,
                threshold_kbps=int(threshold),
                send_event=send_event,
            )
        except Exception as e:  # noqa: BLE001 — last-resort guard so we always close the SSE
            logger.exception("scan task crashed")
            await hub.broadcast(scan_id, {"type": "error", "error": f"scan crashed: {e}"})
        finally:
            await asyncio.sleep(0.5)
            await hub.end(scan_id)

    asyncio.create_task(runner())
    return ScanResponse(scan_id=scan_id, root=resolved_root, threshold_kbps=int(threshold))


@router.get("/scan/{scan_id}/stream")
async def stream_scan(scan_id: int) -> EventSourceResponse:
    async def gen() -> AsyncGenerator[dict[str, str], None]:
        q = hub.register(scan_id)
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield {"data": json.dumps(item)}
        finally:
            hub.unregister(scan_id, q)

    return EventSourceResponse(gen())


@router.get("/scan/{scan_id}", response_model=ScanRunResponse)
def get_scan_run(scan_id: int, db: Session = Depends(get_db)) -> ScanRunResponse:
    run = db.query(ScanRun).filter(ScanRun.id == scan_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="scan run not found")
    return _scan_run_to_response(run)


@router.get("/scans", response_model=list[ScanRunResponse])
def list_scan_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ScanRunResponse]:
    rows = db.query(ScanRun).order_by(ScanRun.id.desc()).limit(limit).all()
    return [_scan_run_to_response(r) for r in rows]


@router.get("/candidates", response_model=CandidatesPage)
def list_candidates(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    threshold_kbps: int | None = Query(default=None, ge=32, le=2048),
    db: Session = Depends(get_db),
) -> CandidatesPage:
    """Paginated list of library files at or below the bitrate threshold."""
    effective_threshold = threshold_kbps if threshold_kbps is not None else _resolved_threshold(db)
    base_q = db.query(LibraryFile).filter(LibraryFile.bitrate_kbps <= effective_threshold)
    total = base_q.count()
    rows = (
        base_q.order_by(LibraryFile.bitrate_kbps.asc(), LibraryFile.abs_path.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        CandidateResponse(
            id=r.id,
            abs_path=r.abs_path,
            bitrate_kbps=r.bitrate_kbps,
            size_bytes=r.size_bytes,
            duration_s=r.duration_s,
            tag_title=r.tag_title or "",
            tag_artist=r.tag_artist or "",
            tag_album=r.tag_album or "",
            last_scanned=r.last_scanned.isoformat() if r.last_scanned else None,
        )
        for r in rows
    ]
    return CandidatesPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        threshold_kbps=effective_threshold,
    )


def _scan_run_to_response(run: ScanRun) -> ScanRunResponse:
    return ScanRunResponse(
        id=run.id,
        root_path=run.root_path,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        files_seen=run.files_seen or 0,
        candidates=run.candidates or 0,
        error=run.error or "",
    )
