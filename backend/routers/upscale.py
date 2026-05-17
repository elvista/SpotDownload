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
from models import AppSetting, LibraryFile, PoolCredential, ReplaceLog, ScanRun, UpscaleMatch

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
    swap_engine,
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
                    pool_preview_url=hit.preview_url or "",
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
                existing.pool_preview_url = hit.preview_url or existing.pool_preview_url or ""
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


# --- Match confirm/reject + A/B preview streaming (step 5) -------------------


_VALID_STATUSES = {"candidate", "confirmed", "rejected", "replaced"}

# Final statuses after a swap has landed — block re-confirming or flipping back.
_TERMINAL_STATUSES = {"replaced"}


class MatchResponse(BaseModel):
    id: int
    library_file_id: int
    pool_slug: str
    pool_hit_id: str
    pool_title: str
    pool_artist: str
    pool_bitrate_kbps: int
    pool_format: str
    pool_preview_url: str
    confidence: float | None
    status: str
    created_at: str | None


def _match_to_response(m: UpscaleMatch) -> MatchResponse:
    return MatchResponse(
        id=m.id,
        library_file_id=m.library_file_id,
        pool_slug=m.pool_slug,
        pool_hit_id=m.pool_hit_id,
        pool_title=m.pool_title,
        pool_artist=m.pool_artist,
        pool_bitrate_kbps=m.pool_bitrate_kbps,
        pool_format=m.pool_format,
        pool_preview_url=m.pool_preview_url or "",
        confidence=m.confidence,
        status=m.status or "candidate",
        created_at=m.created_at.isoformat() if m.created_at else None,
    )


def _load_match_or_404(db: Session, match_id: int) -> UpscaleMatch:
    m = db.query(UpscaleMatch).filter(UpscaleMatch.id == match_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"upscale_match {match_id} not found")
    return m


def _guard_not_terminal(m: UpscaleMatch) -> None:
    if (m.status or "") in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"match {m.id} is already in terminal status '{m.status}' and cannot be changed",
        )


@router.get("/match/{match_id}", response_model=MatchResponse)
def get_match(match_id: int, db: Session = Depends(get_db)) -> MatchResponse:
    return _match_to_response(_load_match_or_404(db, match_id))


@router.post("/match/{match_id}/confirm", response_model=MatchResponse)
def confirm_match(match_id: int, db: Session = Depends(get_db)) -> MatchResponse:
    """Mark a candidate hit as confirmed by the founder.

    Any *other* candidate matches on the same library file are auto-rejected so
    only one match is in `confirmed` state per library file at a time. That
    keeps the swap engine (step 6) unambiguous about which hit to replace with.
    """
    m = _load_match_or_404(db, match_id)
    _guard_not_terminal(m)
    db.query(UpscaleMatch).filter(
        UpscaleMatch.library_file_id == m.library_file_id,
        UpscaleMatch.id != m.id,
        UpscaleMatch.status == "confirmed",
    ).update({UpscaleMatch.status: "rejected"}, synchronize_session=False)
    m.status = "confirmed"
    db.commit()
    db.refresh(m)
    return _match_to_response(m)


@router.post("/match/{match_id}/reject", response_model=MatchResponse)
def reject_match(match_id: int, db: Session = Depends(get_db)) -> MatchResponse:
    m = _load_match_or_404(db, match_id)
    _guard_not_terminal(m)
    m.status = "rejected"
    db.commit()
    db.refresh(m)
    return _match_to_response(m)


@router.get("/match/{match_id}/preview")
async def stream_match_preview(match_id: int, db: Session = Depends(get_db)):
    """Proxy-stream the pool's preview audio so the FE A/B player can play
    it inline without dealing with CORS or pool auth cookies.

    Streams chunked from the pool host; ``Content-Type`` is forwarded. If the
    pool needs cookies, those would have to be threaded through here later
    (out of scope for step 5 — current pools allow unauthenticated previews).
    """
    m = _load_match_or_404(db, match_id)
    if not m.pool_preview_url:
        raise HTTPException(status_code=404, detail="no preview_url stored for this match")

    # Lazy import so the test suite doesn't need httpx running unless this
    # endpoint is exercised.
    import httpx
    from fastapi.responses import StreamingResponse

    client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    try:
        response = await client.send(client.build_request("GET", m.pool_preview_url), stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"pool preview fetch failed: {e}") from e

    if response.status_code >= 400:
        status = response.status_code
        await response.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"pool preview returned HTTP {status}",
        )

    media_type = response.headers.get("content-type", "audio/mpeg")

    async def stream_bytes():
        try:
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(stream_bytes(), media_type=media_type)


@router.get("/match/{match_id}/preview-original")
def stream_match_original(match_id: int, db: Session = Depends(get_db)):
    """Stream the local low-bitrate library file so the FE can A/B against the
    pool preview. Pairs with /preview above.
    """
    from fastapi.responses import FileResponse

    m = _load_match_or_404(db, match_id)
    lf = db.query(LibraryFile).filter(LibraryFile.id == m.library_file_id).first()
    if lf is None:
        raise HTTPException(
            status_code=410,
            detail=f"library_file {m.library_file_id} for match {match_id} has been purged",
        )
    p = Path(lf.abs_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(
            status_code=410, detail=f"library file no longer present on disk: {lf.abs_path}"
        )
    media_type = "audio/mpeg" if p.suffix.lower() == ".mp3" else "application/octet-stream"
    return FileResponse(str(p), media_type=media_type, filename=p.name)


# --- Step 6: atomic swap + Replace Log ---------------------------------------


class ReplaceResponse(BaseModel):
    status: str  # 'replaced'
    replace_log_id: int
    abs_path: str
    archive_path: str
    file_size_before: int
    file_size_after: int
    replaced_at: str
    id3_copy_status: str


class ReplaceLogResponse(BaseModel):
    id: int
    library_file_id: int | None
    upscale_match_id: int | None
    abs_path: str
    archive_path: str
    old_bitrate_kbps: int
    new_bitrate_kbps: int
    pool_slug: str
    pool_source_url: str
    file_size_before: int
    file_size_after: int
    id3_copy_status: str
    replaced_at: str | None


class ReplaceLogPage(BaseModel):
    items: list[ReplaceLogResponse]
    total: int
    limit: int
    offset: int


def _row_to_log_response(r: ReplaceLog) -> ReplaceLogResponse:
    return ReplaceLogResponse(
        id=r.id,
        library_file_id=r.library_file_id,
        upscale_match_id=r.upscale_match_id,
        abs_path=r.abs_path,
        archive_path=r.archive_path,
        old_bitrate_kbps=r.old_bitrate_kbps or 0,
        new_bitrate_kbps=r.new_bitrate_kbps or 0,
        pool_slug=r.pool_slug or "",
        pool_source_url=r.pool_source_url or "",
        file_size_before=r.file_size_before or 0,
        file_size_after=r.file_size_after or 0,
        id3_copy_status=r.id3_copy_status or "",
        replaced_at=r.replaced_at.isoformat() if r.replaced_at else None,
    )


def _httpx_download_factory(source_url: str):
    """Return a sync ``(dest_path) -> bytes_written`` callable.

    Used by the swap engine to fetch the pool file. Sync because the swap
    engine runs the downloader via ``asyncio.to_thread``; using requests via
    httpx's sync API keeps the code readable and avoids nested event loops.
    """
    import httpx

    def download(dest_path):
        with httpx.Client(follow_redirects=True, timeout=120.0) as client:
            with client.stream("GET", source_url) as r:
                if r.status_code >= 400:
                    raise RuntimeError(f"pool returned HTTP {r.status_code}")
                written = 0
                with open(dest_path, "wb") as fh:
                    for chunk in r.iter_bytes(chunk_size=64 * 1024):
                        fh.write(chunk)
                        written += len(chunk)
        return written

    return download


@router.post("/match/{match_id}/replace", response_model=ReplaceResponse)
async def replace_match(match_id: int, db: Session = Depends(get_db)) -> ReplaceResponse:
    """Atomically swap the library file with the confirmed pool hit.

    Requires the match to be in ``confirmed`` state — anything else returns
    409. The path on disk is preserved, so Rekordbox-side state (cue points,
    beatgrids, loops) survives by virtue of how Rekordbox keys library
    entries.
    """
    m = _load_match_or_404(db, match_id)
    if (m.status or "") == "replaced":
        raise HTTPException(status_code=409, detail=f"match {match_id} is already replaced")
    if (m.status or "") != "confirmed":
        raise HTTPException(
            status_code=409,
            detail=f"match {match_id} is '{m.status}', must be 'confirmed' before /replace",
        )
    if not m.pool_preview_url:
        # In Phase 1/2 we use the preview URL as the download source. Full-
        # quality download URLs require the per-pool authenticated download
        # path, which the scrapers stub today. The FE can pre-populate this
        # via a fresh search if needed.
        raise HTTPException(
            status_code=409,
            detail="match has no pool URL stored; re-run /search to refresh",
        )

    download = _httpx_download_factory(m.pool_preview_url)

    try:
        result = await swap_engine.replace(db, m, download_to_temp=download)
    except swap_engine.MatchNotConfirmedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except swap_engine.FileLockedError as e:
        raise HTTPException(
            status_code=409,
            detail=(
                f"target file is locked — close it in any other app (Rekordbox, "
                f"iTunes, players) and retry. Details: {e}"
            ),
        ) from e
    except swap_engine.DownloadFailedError as e:
        raise HTTPException(status_code=502, detail=f"pool download failed: {e}") from e
    except swap_engine.SwapFailedError as e:
        logger.exception("swap_engine: unexpected failure on match %s", match_id)
        raise HTTPException(status_code=500, detail=f"swap failed: {e}") from e

    return ReplaceResponse(
        status="replaced",
        replace_log_id=result.replace_log_id,
        abs_path=result.abs_path,
        archive_path=result.archive_path,
        file_size_before=result.file_size_before,
        file_size_after=result.file_size_after,
        replaced_at=result.replaced_at.isoformat(),
        id3_copy_status=result.id3_copy_status,
    )


@router.get("/replace-log", response_model=ReplaceLogPage)
def list_replace_log(
    library_file_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ReplaceLogPage:
    """Paginated Replace Log, newest first. Optional ``library_file_id`` filter."""
    q = db.query(ReplaceLog)
    if library_file_id is not None:
        q = q.filter(ReplaceLog.library_file_id == library_file_id)
    total = q.count()
    rows = (
        q.order_by(ReplaceLog.replaced_at.desc(), ReplaceLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ReplaceLogPage(
        items=[_row_to_log_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- Steps 7 + 8: session status + session-complete SSE ----------------------
#
# A "session" here is the current in-flight set of replacements: every
# upscale_match that's been pulled out of `candidate` is part of it. The
# session is "complete" when no `confirmed` rows remain (everything has
# either been replaced or rejected) AND at least one replace landed —
# that's the trigger the FE turns into the Rekordbox-rescan toast.
#
# Implementation note: we deliberately don't introduce a new `sessions`
# table. Replace volume in Phase 2 is low (founder is hand-confirming one
# track at a time) and the count queries are cheap. If batch flows arrive
# in Phase 3 we can promote this to a real session row without changing
# the contract.


class SessionStatusResponse(BaseModel):
    candidates: int  # upscale_matches with status='candidate'
    confirmed: int  # status='confirmed' — pending replace
    replaced: int  # status='replaced' — done
    rejected: int  # status='rejected' — user said no
    errors: int  # replace_logs rows with id3_copy_status in {'failed','partial'}
    session_started_at: str | None  # earliest non-candidate transition
    session_completed_at: str | None  # latest replaced_at, if a session has ended


def _compute_session_status(db: Session) -> SessionStatusResponse:
    from sqlalchemy import func

    by_status = dict(
        db.query(UpscaleMatch.status, func.count(UpscaleMatch.id))
        .group_by(UpscaleMatch.status)
        .all()
    )
    errors = (
        db.query(func.count(ReplaceLog.id))
        .filter(ReplaceLog.id3_copy_status.in_(["partial", "failed"]))
        .scalar()
        or 0
    )
    # Session timing: started_at is the earliest created_at of any row that
    # has moved past `candidate`; completed_at is the latest replaced_at on
    # the replace_logs side. Both null when no swap has happened.
    started_at = (
        db.query(func.min(UpscaleMatch.created_at))
        .filter(UpscaleMatch.status != "candidate")
        .scalar()
    )
    completed_at = db.query(func.max(ReplaceLog.replaced_at)).scalar()
    confirmed = int(by_status.get("confirmed", 0))
    replaced = int(by_status.get("replaced", 0))
    # A "complete" session = no confirmed remaining AND at least one replace.
    session_ended = confirmed == 0 and replaced > 0
    return SessionStatusResponse(
        candidates=int(by_status.get("candidate", 0)),
        confirmed=confirmed,
        replaced=replaced,
        rejected=int(by_status.get("rejected", 0)),
        errors=int(errors),
        session_started_at=started_at.isoformat() if started_at else None,
        session_completed_at=completed_at.isoformat() if session_ended and completed_at else None,
    )


@router.get("/session-status", response_model=SessionStatusResponse)
def get_session_status(db: Session = Depends(get_db)) -> SessionStatusResponse:
    """Cheap polling endpoint the FE hits to drive the section's progress bar.

    See ``GET /session-complete`` for the push variant; this endpoint is the
    fallback path when SSE isn't viable (e.g. dev tools, debugging).
    """
    return _compute_session_status(db)


@router.get("/session-complete")
async def stream_session_complete(
    poll_interval_s: float = Query(default=2.0, ge=0.25, le=10.0),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """SSE that fires exactly one ``session_complete`` event the moment the
    current session ends (no ``confirmed`` rows remain AND ``replaced > 0``),
    then closes the stream.

    The FE opens this once after the founder starts confirming matches; the
    event triggers the Rekordbox-rescan toast.

    Implementation: poll the same counts as ``/session-status`` every
    ``poll_interval_s`` seconds. Cheap (a couple of integer GROUP-BY counts
    against a small table) and avoids threading a separate event bus into
    the swap engine.
    """
    # Capture the state we treat as the session's starting point: any
    # replace landed before this stream opened is "previous session" and
    # mustn't re-fire the toast. We watch for `replaced` *strictly
    # increasing* past this baseline.
    baseline = _compute_session_status(db)
    baseline_replaced = baseline.replaced

    async def gen() -> AsyncGenerator[dict[str, str], None]:
        # Use a fresh SessionLocal per poll so we don't pin the dependency-
        # injected request session for the lifetime of the stream.
        from database import SessionLocal as _SessionLocal

        while True:
            await asyncio.sleep(poll_interval_s)
            poll_db = _SessionLocal()
            try:
                status = _compute_session_status(poll_db)
            finally:
                poll_db.close()

            if (
                status.confirmed == 0
                and status.replaced > baseline_replaced
                and status.session_completed_at
            ):
                payload = {
                    "type": "session_complete",
                    "replaced": status.replaced - baseline_replaced,
                    "session_started_at": status.session_started_at,
                    "session_completed_at": status.session_completed_at,
                }
                yield {"event": "session_complete", "data": json.dumps(payload)}
                break

    return EventSourceResponse(gen())
