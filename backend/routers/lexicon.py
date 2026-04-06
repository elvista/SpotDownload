"""Lexicon ID REST and SSE: read Lexicon DJ library, import playlists to Spotify."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import get_db
from services.fingerprinter import fingerprinter
from services.lexicon_service import (
    DEFAULT_DB_PATH,
    get_playlist_name,
    get_playlist_tracks,
    get_playlists,
    import_playlist_to_spotify,
    validate_db_path,
)

logger = logging.getLogger("cratedigger.lexicon")

router = APIRouter(prefix="/lexicon", tags=["lexicon"])


# --- SSE session hub (same pattern as mixtape.py) ---


class _SessionHub:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}

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


# --- Helpers ---


def _get_setting(db: Session, key: str, default: str = "") -> str:
    from routers.settings import get_setting

    return get_setting(db, key, default)


def _set_setting(db: Session, key: str, value: str) -> None:
    from routers.settings import set_setting

    set_setting(db, key, value)


def _spotify_client_configured() -> bool:
    cid = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    secret = (os.environ.get("SPOTIFY_CLIENT_SECRET") or "").strip()
    return bool(
        cid
        and secret
        and cid != "your_spotify_client_id"
        and secret != "your_spotify_client_secret"
    )


# --- Endpoints ---


@router.get("/db-status")
def db_status(db: Session = Depends(get_db)):
    raw = _get_setting(db, "lexicon_db_path", DEFAULT_DB_PATH)
    result = validate_db_path(raw)
    return {"configured": raw != DEFAULT_DB_PATH, **result}


class DbPathBody(BaseModel):
    path: str


@router.put("/db-path")
def set_db_path(body: DbPathBody, db: Session = Depends(get_db)):
    result = validate_db_path(body.path)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["error"])
    _set_setting(db, "lexicon_db_path", body.path)
    return {"configured": True, **result}


@router.get("/playlists")
def list_playlists(db: Session = Depends(get_db)):
    raw = _get_setting(db, "lexicon_db_path", DEFAULT_DB_PATH)
    result = validate_db_path(raw)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["error"])
    playlists = get_playlists(raw)
    return {"playlists": playlists}


@router.get("/playlists/{playlist_id}/tracks")
def playlist_tracks(playlist_id: int, db: Session = Depends(get_db)):
    raw = _get_setting(db, "lexicon_db_path", DEFAULT_DB_PATH)
    result = validate_db_path(raw)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["error"])
    name = get_playlist_name(raw, playlist_id)
    tracks = get_playlist_tracks(raw, playlist_id)
    return {"playlistName": name, "tracks": tracks}


@router.get("/spotify-status")
def spotify_status():
    has_refresh = bool(fingerprinter.get_spotify_refresh_token())
    return {
        "hasRefreshToken": has_refresh,
        "clientConfigured": _spotify_client_configured(),
    }


class ImportBody(BaseModel):
    playlistId: int
    playlistName: str | None = None


@router.post("/import-to-spotify")
async def start_import(body: ImportBody, db: Session = Depends(get_db)):
    if not _spotify_client_configured():
        raise HTTPException(
            status_code=400,
            detail="Spotify API credentials not configured. Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env.",
        )
    if not fingerprinter.get_spotify_refresh_token():
        raise HTTPException(
            status_code=400,
            detail="Connect Spotify first: open Spotify ID (home), click the gear (Settings), and connect your account.",
        )

    raw = _get_setting(db, "lexicon_db_path", DEFAULT_DB_PATH)
    result = validate_db_path(raw)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["error"])

    playlist_name = body.playlistName or get_playlist_name(raw, body.playlistId) or "Lexicon Playlist"
    tracks = get_playlist_tracks(raw, body.playlistId)
    if not tracks:
        raise HTTPException(status_code=400, detail="Playlist has no tracks.")

    token = await fingerprinter.get_spotify_user_access_token()
    if not token:
        raise HTTPException(
            status_code=500,
            detail="Could not refresh Spotify session. Re-connect in Settings.",
        )

    session_id = secrets.token_urlsafe(12)

    async def run():
        try:
            async def send_event(data):
                await hub.broadcast(session_id, data)

            await import_playlist_to_spotify(playlist_name, tracks, token, send_event)
        except Exception as exc:
            logger.exception("Lexicon import failed: %s", exc)
            await hub.broadcast(session_id, {"type": "error", "error": str(exc)})
        finally:
            await asyncio.sleep(1.0)
            await hub.end_session(session_id)

    asyncio.create_task(run())
    return {"sessionId": session_id}


@router.get("/import-stream/{session_id}")
async def import_stream(session_id: str):
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
