"""Upscale section — REST + SSE for scans, candidates, and pool integrations.

Step 2 added the scan + candidates surface. Step 3 (this file) adds pool
status, interactive login, and session-clear endpoints for the DJCity
scraper; zipDJ + BPM Supreme arrive in step 4 with no router-side churn
because both implement the same :class:`pool_base.PoolScraper` protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from config import settings as app_config
from database import get_db
from models import AppSetting, LibraryFile, PoolCredential, ScanRun, UpscaleMatch

# Import concrete scrapers so they register themselves on module load. The
# orchestrator imports them too, but listing them here is cheap insurance
# that ``GET /pools`` shows every pool regardless of import order.
from services import (
    library_scanner,
    pool_base,
    pool_bpmsupreme,  # noqa: F401
    pool_djcity,  # noqa: F401
    pool_orchestrator,
    pool_zipdj,  # noqa: F401
)

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


# --- Pool endpoints (step 3) -------------------------------------------------


class PoolStatusResponse(BaseModel):
    slug: str
    display_name: str
    connected: bool
    last_login: str | None
    last_error: str
    enabled: bool  # Feature-flag state, repeated per row for FE convenience.


class PoolLoginAcceptedResponse(BaseModel):
    slug: str
    status: str = "started"
    message: str


@router.get("/pools", response_model=list[PoolStatusResponse])
def list_pools(db: Session = Depends(get_db)) -> list[PoolStatusResponse]:
    """Status row per registered pool scraper.

    ``connected`` reflects whether a stored session blob exists in the DB
    (the on-disk cache may have been wiped — we re-hydrate it on first
    scrape from the encrypted blob).
    """
    enabled = pool_base.pools_enabled()
    out: list[PoolStatusResponse] = []
    for scraper in pool_base.all_scrapers():
        row = db.query(PoolCredential).filter(PoolCredential.pool_slug == scraper.slug).first()
        out.append(
            PoolStatusResponse(
                slug=scraper.slug,
                display_name=scraper.display_name,
                connected=bool(row and row.state_blob),
                last_login=row.last_login.isoformat() if row and row.last_login else None,
                last_error=(row.last_error or "") if row else "",
                enabled=enabled,
            )
        )
    return out


@router.post("/pools/{slug}/login", response_model=PoolLoginAcceptedResponse)
async def start_pool_login(slug: str, db: Session = Depends(get_db)) -> PoolLoginAcceptedResponse:
    """Kick off the interactive login flow for ``slug`` in the background.

    The actual Playwright window opens on whatever machine runs the
    backend — for the founder's always-on install that is their own Mac.
    We return immediately so the FE can show a "complete login in the
    browser window that opened" prompt without blocking.
    """
    scraper = pool_base.get_scraper(slug)
    if scraper is None:
        raise HTTPException(status_code=404, detail=f"unknown pool: {slug}")
    if not pool_base.pools_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Pool scraping is disabled. Set UPSCALE_POOLS_ENABLED=1 in your "
                ".env and restart the backend, then try again."
            ),
        )

    async def runner() -> None:
        # Use a fresh session — we don't want to hold the request session for
        # the duration of the interactive login (which can be minutes).
        from database import SessionLocal

        local_db = SessionLocal()
        try:
            await scraper.login_interactive()
            # Mirror the freshly-written storage_state.json to the encrypted
            # DB row so the session survives moves between machines.
            state_path = pool_base.pool_state_file(scraper.slug)
            if state_path.exists():
                pool_base.write_pool_state(
                    local_db, scraper.slug, state_path.read_text(encoding="utf-8")
                )
            else:
                pool_base.record_pool_error(
                    local_db, scraper.slug, "login completed but no storage state was written"
                )
        except Exception as e:  # noqa: BLE001 — log + mark, don't crash the worker
            logger.exception("pool login failed: %s/%s", scraper.slug, e)
            # Ensure a row exists so the FE can surface the error message.
            row = (
                local_db.query(PoolCredential)
                .filter(PoolCredential.pool_slug == scraper.slug)
                .first()
            )
            if row is None:
                local_db.add(
                    PoolCredential(
                        pool_slug=scraper.slug,
                        state_blob="",
                        last_login=datetime.now(UTC),
                        last_error=str(e)[:500],
                    )
                )
            else:
                row.last_error = str(e)[:500]
            local_db.commit()
        finally:
            local_db.close()

    asyncio.create_task(runner())
    return PoolLoginAcceptedResponse(
        slug=slug,
        status="started",
        message=(
            "A login window will open on the server host. Complete the login there; "
            "this endpoint returned immediately. Poll GET /api/upscale/pools to see "
            "when the session is captured."
        ),
    )


@router.delete("/pools/{slug}", status_code=204)
async def clear_pool_session(slug: str, db: Session = Depends(get_db)) -> None:
    """Wipe the stored session for ``slug`` (disk cache + DB row)."""
    scraper = pool_base.get_scraper(slug)
    if scraper is None:
        raise HTTPException(status_code=404, detail=f"unknown pool: {slug}")
    pool_base.clear_pool_state(db, slug)
    # Also let the scraper drop any in-process state (no-op today, future-proofed).
    await scraper.clear_session()


# --- Search via orchestrator (step 4) ----------------------------------------


class SearchRequest(BaseModel):
    library_file_id: int = Field(
        ..., description="ID of a row in library_files to find replacements for."
    )
    limit: int = Field(default=25, ge=1, le=100)
    query_override: str | None = Field(
        default=None,
        description="Optional explicit search string. Defaults to '{artist} {title}' from the library file's tags.",
    )


class TriedPoolResponse(BaseModel):
    slug: str
    hits_count: int
    error: str


class PoolHitResponse(BaseModel):
    pool_slug: str
    hit_id: str
    title: str
    artist: str
    bitrate_kbps: int
    format: str
    duration_s: float | None
    preview_url: str | None
    upscale_match_id: int


class SearchResponse(BaseModel):
    """Shape consumed by the FE fallback chevron.

    ``tried`` lists every pool the orchestrator queried, in priority order.
    ``served_by`` is the slug of the pool whose hits are returned (empty
    string when every pool failed or returned zero hits)."""

    tried: list[TriedPoolResponse]
    served_by: str
    hits: list[PoolHitResponse]


def _query_for_library_file(lf: LibraryFile, override: str | None) -> str:
    if override and override.strip():
        return override.strip()
    parts = [lf.tag_artist or "", lf.tag_title or ""]
    q = " ".join(p.strip() for p in parts if p and p.strip())
    if q:
        return q
    # Fall back to filename stem if tags are empty — better than no query at all.
    from pathlib import Path as _Path  # local import to keep top-of-file tidy

    return _Path(lf.abs_path).stem


@router.post("/search", response_model=SearchResponse)
async def search_upscale(body: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    """Run the pool fallback chain for a library file and persist hits.

    Each returned hit is upserted as an ``upscale_matches`` row with
    ``status='candidate'``. The router returns the row id alongside the
    pool payload so the FE can directly call
    ``/upscale/match/{id}/confirm`` (step 5) without a second lookup.
    """
    lf = db.query(LibraryFile).filter(LibraryFile.id == body.library_file_id).first()
    if lf is None:
        raise HTTPException(
            status_code=404, detail=f"library_file_id {body.library_file_id} not found"
        )

    query = _query_for_library_file(lf, body.query_override)
    if not query:
        raise HTTPException(
            status_code=400,
            detail="library file has no tag_artist/tag_title and an empty filename; pass query_override",
        )

    result = await pool_orchestrator.search(db, query, limit=body.limit)

    # Persist hits as candidate upscale_matches. Conflict on the unique
    # (library_file_id, pool_slug, pool_hit_id) constraint is harmless —
    # we want the existing row's id for the response.
    hit_responses: list[PoolHitResponse] = []
    if result.served_by and result.hits:
        for hit in result.hits:
            existing = (
                db.query(UpscaleMatch)
                .filter(
                    UpscaleMatch.library_file_id == lf.id,
                    UpscaleMatch.pool_slug == result.served_by,
                    UpscaleMatch.pool_hit_id == hit.hit_id,
                )
                .first()
            )
            if existing is None:
                row = UpscaleMatch(
                    library_file_id=lf.id,
                    pool_slug=result.served_by,
                    pool_hit_id=hit.hit_id,
                    pool_title=hit.title,
                    pool_artist=hit.artist,
                    pool_bitrate_kbps=hit.bitrate_kbps,
                    pool_format=hit.format,
                )
                db.add(row)
                db.flush()
                match_id = row.id
            else:
                # Refresh fields in case the pool's metadata has changed since
                # last query — but keep the row's status as-is so a previous
                # confirm/reject doesn't get clobbered.
                existing.pool_title = hit.title
                existing.pool_artist = hit.artist
                existing.pool_bitrate_kbps = hit.bitrate_kbps
                existing.pool_format = hit.format
                match_id = existing.id

            hit_responses.append(
                PoolHitResponse(
                    pool_slug=result.served_by,
                    hit_id=hit.hit_id,
                    title=hit.title,
                    artist=hit.artist,
                    bitrate_kbps=hit.bitrate_kbps,
                    format=hit.format,
                    duration_s=hit.duration_s,
                    preview_url=hit.preview_url,
                    upscale_match_id=match_id,
                )
            )
        db.commit()

    return SearchResponse(
        tried=[
            TriedPoolResponse(slug=t.slug, hits_count=t.hits_count, error=t.error)
            for t in result.tried
        ],
        served_by=result.served_by,
        hits=hit_responses,
    )
