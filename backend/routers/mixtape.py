"""Mixtape ID REST and SSE: upload, URL processing, fingerprint stream, Spotify playlist OAuth."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from config import settings as app_settings
from database import SessionLocal
from models import AppSetting
from security import encrypt_token
from services import audio_processor
from services.fingerprinter import fingerprinter
from services.mixtape_processor import process_audio_file_streaming

logger = logging.getLogger("cratedigger.mixtape")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = BACKEND_ROOT / "cache"
LAST_FILE_PATH = CACHE_DIR / "last-file.json"
URL_CACHE_PATH = CACHE_DIR / "url-cache.json"

router = APIRouter(prefix="/mixtape", tags=["mixtape"])

MIXTAPE_REFRESH_KEY = "mixtape_spotify_refresh_token"

# --- Session broadcast (SSE): one queue per connected client -----------------

_last_processed_file: dict[str, Any] | None = None
_url_cache: dict[str, dict[str, Any]] = {}
_spotify_oauth_states: dict[str, float] = {}


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


def _ensure_cache_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    audio_processor.ensure_dirs()


def _load_disk_state() -> None:
    global _last_processed_file, _url_cache
    _ensure_cache_dirs()
    try:
        if LAST_FILE_PATH.exists():
            data = json.loads(LAST_FILE_PATH.read_text(encoding="utf-8"))
            fp = data.get("filePath")
            if fp and os.path.isfile(fp):
                _last_processed_file = data
                logger.info("Restored last mixtape file: %s", data.get("name"))
    except Exception as e:
        logger.warning("Could not load last-file.json: %s", e)

    try:
        if URL_CACHE_PATH.exists():
            raw = json.loads(URL_CACHE_PATH.read_text(encoding="utf-8"))
            for url, entry in raw.items():
                p = entry.get("filePath")
                if p and os.path.isfile(p):
                    _url_cache[url] = entry
            logger.info("URL cache: %s entries", len(_url_cache))
    except Exception as e:
        logger.warning("Could not load url-cache.json: %s", e)


_load_disk_state()


def _save_last_file_info() -> None:
    if not _last_processed_file:
        return
    _ensure_cache_dirs()
    try:
        LAST_FILE_PATH.write_text(json.dumps(_last_processed_file, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("save last-file: %s", e)


def _save_url_cache() -> None:
    _ensure_cache_dirs()
    try:
        URL_CACHE_PATH.write_text(json.dumps(_url_cache, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("save url-cache: %s", e)


def _commit_last_file(file_path: str, mixtape_name: str) -> None:
    """Keep source file for rescan; remove previous stored file if different."""
    global _last_processed_file
    if not os.path.isfile(file_path):
        return
    if _last_processed_file and _last_processed_file.get("filePath") not in (None, file_path):
        old = _last_processed_file.get("filePath")
        if old and os.path.isfile(old) and old != file_path:
            try:
                os.remove(old)
            except OSError:
                pass
    st = os.stat(file_path)
    _last_processed_file = {
        "filePath": file_path,
        "name": mixtape_name,
        "date": datetime.now(UTC).isoformat(),
        "size": st.st_size,
    }
    _save_last_file_info()


def _set_mixtape_refresh_token(refresh: str) -> None:
    enc = encrypt_token(refresh, getattr(app_settings, "ENCRYPTION_KEY", None) or "")
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == MIXTAPE_REFRESH_KEY).first()
        if row:
            row.value = enc
        else:
            db.add(AppSetting(key=MIXTAPE_REFRESH_KEY, value=enc))
        db.commit()
    finally:
        db.close()
    # Legacy file compatibility
    try:
        p = fingerprinter.spotify_user_token_path()
        p.write_text(
            json.dumps(
                {"refresh_token": refresh, "savedAt": datetime.now(UTC).isoformat()}, indent=2
            ),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Could not write spotify-user-token.json: %s", e)
    fingerprinter.spotify_user_token = None
    fingerprinter.spotify_user_token_expires_at = 0


def get_spotify_redirect_uri() -> str:
    env = (os.environ.get("SPOTIFY_REDIRECT_URI_MIXID") or "").strip()
    if env:
        return env
    return "http://127.0.0.1:8000/api/mixtape/spotify/callback"


def spotify_client_configured() -> bool:
    cid = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    secret = (os.environ.get("SPOTIFY_CLIENT_SECRET") or "").strip()
    return bool(
        cid
        and secret
        and cid != "your_spotify_client_id"
        and secret != "your_spotify_client_secret"
    )


def extract_spotify_track_id(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    trimmed = url.strip()
    m = re.match(r"^spotify:track:([a-zA-Z0-9]+)", trimmed)
    if m:
        return m.group(1)
    m2 = re.search(r"/track/([a-zA-Z0-9]+)", trimmed)
    return m2.group(1) if m2 else None


async def resolve_spotify_track_ids_from_tracks(tracks: list[dict[str, Any]]) -> list[str]:
    from services.spotify_service import search_spotify_track

    token = await fingerprinter.get_spotify_token()
    ordered: list[str] = []
    seen: set[str] = set()
    for t in tracks:
        if not t or not isinstance(t, dict):
            continue
        artist = (t.get("artist") or "").strip()
        title = (t.get("title") or "").strip()
        if (not artist or not title) and " - " in title:
            i = title.index(" - ")
            artist = title[:i].strip()
            title = title[i + 3 :].strip()
        if not artist or not title:
            continue
        link_raw = t.get("spotifyLink") or t.get("spotify_link")
        tid = extract_spotify_track_id(link_raw)
        if not tid and token:
            result = await search_spotify_track(artist, title, token)
            if result:
                tid = extract_spotify_track_id(result.get("spotifyUrl"))
                if not tid:
                    uri = result.get("uri", "")
                    if uri.startswith("spotify:track:"):
                        tid = uri.split(":")[-1]
        if tid and tid not in seen:
            seen.add(tid)
            ordered.append(tid)
    return ordered


async def wait_for_subscriber(session_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if hub.subscriber_count(session_id) > 0:
            return
        await asyncio.sleep(0.1)


# --- Routes -------------------------------------------------------------------


@router.post("/upload")
async def upload_audio(audio: UploadFile = File(...)):
    _ensure_cache_dirs()
    if not audio.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    ext = Path(audio.filename).suffix.lower()
    if ext not in (".mp3", ".wav", ".m4a"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {ext or 'unknown'}. Please upload MP3, WAV, or M4A files only.",
        )
    session_id = str(int(time.time() * 1000))
    mixtape_name = Path(audio.filename).stem
    dest = audio_processor.UPLOADS_DIR / f"{session_id}-{Path(audio.filename).name}"
    content = await audio.read()
    if len(content) > 500 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 500MB)")
    dest.write_bytes(content)
    file_path = str(dest)

    async def run() -> None:
        async def send_event(data: dict[str, Any]) -> None:
            await hub.broadcast(session_id, data)

        try:
            ok = await process_audio_file_streaming(file_path, session_id, mixtape_name, send_event)
            if ok or os.path.isfile(file_path):
                _commit_last_file(file_path, mixtape_name)
        finally:
            await asyncio.sleep(1.0)
            await hub.end_session(session_id)

    asyncio.create_task(run())
    return {"success": True, "sessionId": session_id, "filePath": file_path}


class ProcessLinkBody(BaseModel):
    url: str
    type: str = Field(..., description="youtube | soundcloud | mixcloud")


@router.post("/process-link")
async def process_link(body: ProcessLinkBody):
    url = (body.url or "").strip()
    t = (body.type or "").strip().lower()
    if not url or t not in ("youtube", "soundcloud", "mixcloud"):
        raise HTTPException(status_code=400, detail="URL and valid type are required")

    session_id = str(int(time.time() * 1000))

    async def run() -> None:
        mixtape_name = "Mixtape"
        file_path: str | None = None
        try:
            cached = _url_cache.get(url)
            if cached and cached.get("filePath") and os.path.isfile(cached["filePath"]):
                file_path = cached["filePath"]
                mixtape_name = cached.get("name") or mixtape_name
                fingerprinter.clear_cache()
                await wait_for_subscriber(session_id)

                async def send_event(data: dict[str, Any]) -> None:
                    await hub.broadcast(session_id, data)

                ok = await process_audio_file_streaming(
                    file_path, session_id, mixtape_name, send_event
                )
                if ok or (file_path and os.path.isfile(file_path)):
                    _commit_last_file(file_path, mixtape_name)
                await asyncio.sleep(1.0)
                await hub.end_session(session_id)
                return

            # Download
            async def send_event(data: dict[str, Any]) -> None:
                await hub.broadcast(session_id, data)

            await send_event(
                {"type": "download", "percent": None, "totalSize": None, "speed": None, "eta": None}
            )
            fp, title = await audio_processor.download_from_url(url)
            file_path = fp
            mixtape_name = title or mixtape_name
            _url_cache[url] = {
                "filePath": file_path,
                "name": mixtape_name,
                "date": datetime.now(UTC).isoformat(),
            }
            _save_url_cache()

            ok = await process_audio_file_streaming(file_path, session_id, mixtape_name, send_event)
            if ok or (file_path and os.path.isfile(file_path)):
                _commit_last_file(file_path, mixtape_name)
        except Exception as e:
            logger.exception("process-link: %s", e)
            msg = str(e)
            if "yt-dlp" in msg.lower() or "youtube-dl" in msg.lower():
                msg += " Please ensure yt-dlp is installed and updated: brew install yt-dlp"
            elif "ffmpeg" in msg.lower() or "ffprobe" in msg.lower():
                msg += " Please ensure FFmpeg is installed: brew install ffmpeg"
            await hub.broadcast(
                session_id,
                {
                    "type": "error",
                    "error": msg,
                    "details": {
                        "source": t,
                        "url": url,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                },
            )
            if file_path and os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        finally:
            await asyncio.sleep(1.0)
            await hub.end_session(session_id)

    asyncio.create_task(run())
    return {"success": True, "sessionId": session_id}


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


@router.get("/last-file")
def last_file():
    if _last_processed_file and os.path.isfile(_last_processed_file.get("filePath", "")):
        return {
            "available": True,
            "name": _last_processed_file.get("name"),
            "date": _last_processed_file.get("date"),
            "size": _last_processed_file.get("size"),
        }
    return {"available": False}


@router.post("/rescan")
async def rescan():
    if not _last_processed_file or not os.path.isfile(_last_processed_file.get("filePath", "")):
        raise HTTPException(status_code=404, detail="No previous file available to rescan")
    session_id = str(int(time.time() * 1000))
    mixtape_name = str(_last_processed_file.get("name") or "Mixtape")
    fp = str(_last_processed_file["filePath"])

    async def run() -> None:
        fingerprinter.clear_cache()
        await wait_for_subscriber(session_id)

        async def send_event(data: dict[str, Any]) -> None:
            await hub.broadcast(session_id, data)

        try:
            ok = await process_audio_file_streaming(fp, session_id, mixtape_name, send_event)
            if ok or os.path.isfile(fp):
                _commit_last_file(fp, mixtape_name)
        finally:
            await asyncio.sleep(1.0)
            await hub.end_session(session_id)

    asyncio.create_task(run())
    return {"success": True, "sessionId": session_id, "name": mixtape_name}


@router.get("/fingerprint-status")
def fingerprint_status():
    """Whether ACRCloud / AudD env is set (no secrets returned)."""
    return fingerprinter.fingerprint_env_status()


@router.get("/spotify/status")
def spotify_status():
    has_refresh = bool(fingerprinter.get_spotify_refresh_token())
    return {"clientConfigured": spotify_client_configured(), "hasRefreshToken": has_refresh}


@router.get("/spotify/login")
def spotify_login():
    if not spotify_client_configured():
        raise HTTPException(
            status_code=400,
            detail="Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env first.",
        )
    now = time.time() * 1000
    for s, t in list(_spotify_oauth_states.items()):
        if now - t > 600_000:
            del _spotify_oauth_states[s]
    state = secrets.token_hex(16)
    _spotify_oauth_states[state] = now
    redirect_uri = get_spotify_redirect_uri()
    params = urlencode(
        {
            "response_type": "code",
            "client_id": os.environ.get("SPOTIFY_CLIENT_ID", ""),
            "scope": "playlist-modify-private",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return RedirectResponse(url=f"https://accounts.spotify.com/authorize?{params}")


@router.get("/spotify/callback")
async def spotify_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    if error:
        return HTMLResponse(
            content=(
                f"<html><body><p>Spotify authorization failed: {error}</p>"
                '<p><a href="http://localhost:5173/mixtape">Back to Mixtape ID</a></p></body></html>'
            ),
            status_code=400,
        )
    if not code or not state or state not in _spotify_oauth_states:
        return HTMLResponse(
            content=(
                "<html><body><p>Invalid or expired login. Close this tab and click Spotify Playlist again "
                "on Mixtape ID.</p></body></html>"
            ),
            status_code=400,
        )
    _spotify_oauth_states.pop(state, None)
    if not spotify_client_configured():
        return HTMLResponse(content="Spotify app credentials missing on server.", status_code=500)

    redirect_uri = get_spotify_redirect_uri()
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "")
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    import base64

    creds = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        if r.status_code != 200:
            logger.error("Spotify token exchange: %s", r.text)
            return HTMLResponse(
                content=(
                    "<html><body><p>Could not complete Spotify login. Check Redirect URI in your Spotify app "
                    "matches this server (see SPOTIFY_REDIRECT_URI_MIXID or default /api/mixtape/spotify/callback).</p></body></html>"
                ),
                status_code=500,
            )
        data = r.json()
        refresh = data.get("refresh_token")
        if not refresh:
            return HTMLResponse(
                content=(
                    "<html><body><p>No refresh token from Spotify. Revoke access in Spotify account settings "
                    "and try connecting again.</p></body></html>"
                ),
                status_code=500,
            )
        _set_mixtape_refresh_token(refresh)
    except Exception as e:
        logger.exception("Spotify callback: %s", e)
        return HTMLResponse(content=f"<html><body><p>Error: {e}</p></body></html>", status_code=500)

    return HTMLResponse(
        content="""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Spotify connected</title></head>
<body style="font-family:system-ui;padding:2rem;">
<p><strong>Spotify connected.</strong> You can close this tab and return to CrateDigger, then click
<strong>Spotify Playlist</strong> again.</p>
<script>setTimeout(function(){ window.close(); }, 800);</script>
</body></html>"""
    )


class CreatePlaylistBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    track_ids: list[str] | None = Field(None, alias="trackIds")
    tracks: list[dict[str, Any]] | None = None
    playlist_name: str = Field("Mixtape", alias="playlistName")
    filter: str = "all"


@router.post("/create-spotify-playlist")
async def create_spotify_playlist(body: CreatePlaylistBody):
    track_ids: list[str] = []
    if body.tracks:
        track_ids = await resolve_spotify_track_ids_from_tracks(body.tracks)
    elif body.track_ids:
        seen: set[str] = set()
        for raw in body.track_ids:
            tid = str(raw).strip() if raw is not None else ""
            if tid and re.match(r"^[a-zA-Z0-9]+$", tid) and tid not in seen:
                seen.add(tid)
                track_ids.append(tid)

    if not track_ids:
        raise HTTPException(
            status_code=400,
            detail="No Spotify tracks could be resolved. Ensure results include artist and title, "
            "and configure SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET for track lookup.",
        )
    if not spotify_client_configured():
        raise HTTPException(
            status_code=400,
            detail="Spotify API credentials not configured. Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env.",
        )
    if not fingerprinter.get_spotify_refresh_token():
        return JSONResponse(
            status_code=400,
            content={
                "error": "Connect Spotify once: open Spotify ID (home), click the gear (Settings), and connect "
                "your account. That same login is used to create Mixtape playlists — no separate Mixtape OAuth "
                "required. Or set SPOTIFY_REFRESH_TOKEN in .env.",
                "needsSpotifyAuth": True,
                "spotifyLoginPath": "/api/mixtape/spotify/login",
            },
        )

    token = await fingerprinter.get_spotify_user_access_token()
    if not token:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Could not refresh your Spotify session. Re-connect in Settings (Spotify ID), or use "
                "Mixtape-only login below.",
                "needsSpotifyAuth": True,
                "spotifyLoginPath": "/api/mixtape/spotify/login",
            },
        )

    from services.spotify_service import create_or_update_spotify_playlist

    desc = f"Created by Mixtape ID ({body.filter} filter) — {datetime.now().strftime('%Y-%m-%d')}"
    uris = [f"spotify:track:{tid}" for tid in track_ids]
    try:
        result = await create_or_update_spotify_playlist(
            body.playlist_name, uris, token,
            description=desc, update_existing=True,
        )
        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])
        return {
            "success": True,
            "playlistId": result["playlistId"],
            "playlistUrl": result["playlistUrl"],
            "addedTracks": result["added"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("create playlist: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
