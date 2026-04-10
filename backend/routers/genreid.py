"""Genre ID REST and SSE: scan Lexicon for empty genres, classify via Claude, stage and export."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal
from models import StagedGenre
from services.genreid_service import (
    export_genres_to_lexicon,
    fetch_all_library_tracks,
    fetch_all_tracks,
    fetch_empty_genre_tracks,
    get_lexicon_db_path,
    lookup_genre_lastfm,
    set_lexicon_db_path,
    validate_lexicon_db,
)

logger = logging.getLogger("cratedigger.genreid")

router = APIRouter(prefix="/genreid", tags=["genreid"])


# --- Session broadcast (SSE) --------------------------------------------------


class _SessionHub:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}

    def subscriber_count(self, session_id: str) -> int:
        return len(self._queues.get(session_id, []))

    def register(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(session_id, []).append(q)
        return q

    def unregister(self, session_id: str, q: asyncio.Queue) -> None:
        lst = self._queues.get(session_id)
        if not lst:
            return
        if q in lst:
            lst.remove(q)
        if not lst:
            del self._queues[session_id]

    async def broadcast(self, session_id: str, data: dict[str, Any]) -> None:
        for q in list(self._queues.get(session_id, [])):
            await q.put(data)

    async def end_session(self, session_id: str) -> None:
        for q in list(self._queues.get(session_id, [])):
            await q.put(None)
        self._queues.pop(session_id, None)


hub = _SessionHub()


# --- Routes -------------------------------------------------------------------


@router.get("/db-status")
def db_status():
    path = get_lexicon_db_path()
    return validate_lexicon_db(path)


@router.put("/db-path")
def update_db_path(body: dict):
    path = (body.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Path is required")
    result = validate_lexicon_db(path)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["error"])
    set_lexicon_db_path(path)
    return result


@router.get("/tracks")
def get_tracks(search: str = "", page: int = 1, page_size: int = 50, filter: str = "all"):
    path = get_lexicon_db_path()
    status = validate_lexicon_db(path)
    if not status["valid"]:
        raise HTTPException(status_code=400, detail=status["error"])
    return fetch_all_tracks(path, search=search, page=page, page_size=page_size, filter_type=filter)


@router.post("/scan")
async def scan_genres(body: dict | None = None):
    """Scan Lexicon DB for genres, classify via Last.fm, stream progress."""
    rescan = (body or {}).get("rescan", False)
    path = get_lexicon_db_path()
    status = validate_lexicon_db(path)
    if not status["valid"]:
        raise HTTPException(status_code=400, detail=status["error"])

    tracks = fetch_all_library_tracks(path) if rescan else fetch_empty_genre_tracks(path)
    if not tracks:
        return {"sessionId": None, "totalTracks": 0, "message": "No tracks to scan"}

    session_id = str(int(time.time() * 1000))

    async def run() -> None:
        # Wait for SSE subscriber
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if hub.subscriber_count(session_id) > 0:
                break
            await asyncio.sleep(0.1)

        total = len(tracks)
        processed = 0

        try:
            for track in tracks:
                # Broadcast "looking up" so the UI shows which track is being processed
                await hub.broadcast(
                    session_id,
                    {
                        "type": "lookup",
                        "track": {
                            "id": track["id"],
                            "title": track.get("title", ""),
                            "artist": track.get("artist", ""),
                        },
                        "current": processed + 1,
                        "total": total,
                    },
                )

                genre = await asyncio.to_thread(
                    lookup_genre_lastfm,
                    track.get("artist", ""),
                    track.get("title", ""),
                )
                processed += 1
                await hub.broadcast(
                    session_id,
                    {
                        "type": "progress",
                        "track": {
                            "id": track["id"],
                            "title": track.get("title", ""),
                            "artist": track.get("artist", ""),
                            "remixer": track.get("remixer", ""),
                            "key": track.get("key", ""),
                        },
                        "suggestedGenre": genre or "",
                        "current": processed,
                        "total": total,
                    },
                )

            await hub.broadcast(
                session_id,
                {"type": "complete", "totalProcessed": processed},
            )
        except Exception as e:
            logger.exception("Scan error: %s", e)
            await hub.broadcast(session_id, {"type": "error", "error": str(e)})
        finally:
            await asyncio.sleep(0.5)
            await hub.end_session(session_id)

    asyncio.create_task(run())
    return {"sessionId": session_id, "totalTracks": len(tracks)}


@router.get("/stream/{session_id}")
async def stream_session(session_id: str):
    async def gen():
        q = hub.register(session_id)
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                yield {"data": json.dumps(item)}
        finally:
            hub.unregister(session_id, q)

    return EventSourceResponse(gen())


class ApproveBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    tracks: list[dict[str, Any]] = Field(
        ..., description="List of {trackId, title, artist, genre}"
    )


@router.post("/approve")
def approve_genres(body: ApproveBody):
    """Save approved genres to the staging table."""
    db = SessionLocal()
    try:
        saved = 0
        for t in body.tracks:
            track_id = t.get("trackId") or t.get("id")
            genre = (t.get("genre") or "").strip()
            if not track_id or not genre:
                continue
            existing = (
                db.query(StagedGenre)
                .filter(StagedGenre.lexicon_track_id == track_id)
                .first()
            )
            if existing:
                existing.suggested_genre = genre
                existing.title = t.get("title", existing.title)
                existing.artist = t.get("artist", existing.artist)
                existing.approved = True
            else:
                db.add(
                    StagedGenre(
                        lexicon_track_id=track_id,
                        title=t.get("title", ""),
                        artist=t.get("artist", ""),
                        suggested_genre=genre,
                        approved=True,
                    )
                )
            saved += 1
        db.commit()
        return {"saved": saved}
    finally:
        db.close()


@router.get("/staged")
def get_staged():
    """Return all staged genres pending export."""
    db = SessionLocal()
    try:
        rows = db.query(StagedGenre).filter(StagedGenre.approved).all()
        return [
            {
                "id": r.id,
                "trackId": r.lexicon_track_id,
                "title": r.title,
                "artist": r.artist,
                "genre": r.suggested_genre,
            }
            for r in rows
        ]
    finally:
        db.close()


@router.post("/export")
async def export_to_lexicon():
    """Write staged genres to Lexicon DB and clear staging table."""
    path = get_lexicon_db_path()
    status = validate_lexicon_db(path)
    if not status["valid"]:
        raise HTTPException(status_code=400, detail=status["error"])

    db = SessionLocal()
    try:
        rows = db.query(StagedGenre).filter(StagedGenre.approved).all()
        if not rows:
            raise HTTPException(status_code=400, detail="No approved genres to export")

        staged = [
            {"lexicon_track_id": r.lexicon_track_id, "suggested_genre": r.suggested_genre}
            for r in rows
        ]

        updated = export_genres_to_lexicon(staged, path)

        # Clear exported rows
        for r in rows:
            db.delete(r)
        db.commit()

        return {"exported": updated, "cleared": len(rows)}
    finally:
        db.close()


@router.delete("/staged")
def clear_staged():
    """Clear all staged genres."""
    db = SessionLocal()
    try:
        count = db.query(StagedGenre).delete()
        db.commit()
        return {"cleared": count}
    finally:
        db.close()
