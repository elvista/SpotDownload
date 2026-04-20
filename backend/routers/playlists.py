import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session, selectinload

from database import get_db
from models import Playlist, Track
from routers.auth import get_setting, set_setting
from services.spotify import SpotifyAuthError, get_spotify_service
from services.sync_ops import dedupe_spotify_tracks, refresh_playlist_tracks

router = APIRouter(tags=["playlists"])
logger = logging.getLogger("cratedigger.playlists")

# Spotify playlist URL patterns (must match before calling API; query string e.g. ?si=... allowed)
SPOTIFY_PLAYLIST_URL_RE = re.compile(
    r"^https?://(open\.)?spotify\.com/playlist/[a-zA-Z0-9_-]+(\?[^#]*)?$|^spotify:playlist:[a-zA-Z0-9_-]+$",
    re.IGNORECASE,
)


class PlaylistCreate(BaseModel):
    url: str


class TrackResponse(BaseModel):
    id: int
    spotify_id: str
    name: str
    artist: str
    album: str
    genre: str = ""
    duration_ms: int
    image_url: str
    spotify_url: str
    is_new: bool
    is_downloaded: bool

    @field_validator("genre", "image_url", "spotify_url", mode="before")
    @classmethod
    def empty_str_none(cls, v):
        return v if v is not None else ""

    class Config:
        from_attributes = True


class PlaylistResponse(BaseModel):
    id: int
    spotify_id: str
    name: str
    description: str
    owner: str
    image_url: str
    track_count: int
    spotify_url: str
    is_monitoring: bool
    last_checked: datetime | None
    tracks: list[TrackResponse] = []

    @field_validator("description", "owner", "image_url", "spotify_url", mode="before")
    @classmethod
    def empty_str_none(cls, v):
        return v if v is not None else ""

    class Config:
        from_attributes = True


@router.post("/playlists", response_model=PlaylistResponse)
async def add_playlist(body: PlaylistCreate, db: Session = Depends(get_db)):
    url = (body.url or "").strip()
    if not url or not SPOTIFY_PLAYLIST_URL_RE.match(url):
        raise HTTPException(status_code=400, detail="Invalid Spotify playlist URL")
    spotify = get_spotify_service()
    playlist_id = spotify.extract_playlist_id(url)
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Invalid Spotify playlist URL")

    existing = (
        db.query(Playlist)
        .options(selectinload(Playlist.tracks))
        .filter(Playlist.spotify_id == playlist_id)
        .first()
    )
    if existing:
        payload = {
            "detail": "Playlist already added",
            "playlist": PlaylistResponse.model_validate(existing).model_dump(mode="json"),
        }
        return JSONResponse(status_code=409, content=payload)

    # Prefer user token when connected (fixes "not found" for some editorial playlists)
    data = None
    access_token = get_setting(db, "spotify_access_token", "")
    refresh_token = get_setting(db, "spotify_refresh_token", "")
    expires_at_str = get_setting(db, "spotify_token_expires_at", "0")
    if access_token and refresh_token:
        try:
            sp_user, updated_token_info = spotify.get_user_client(
                access_token, refresh_token, int(expires_at_str or 0)
            )
            if updated_token_info["access_token"] != access_token:
                set_setting(db, "spotify_access_token", updated_token_info["access_token"])
                set_setting(db, "spotify_token_expires_at", str(updated_token_info["expires_at"]))
            data = await spotify.get_playlist(playlist_id, sp_client=sp_user)
        except SpotifyAuthError:
            pass  # Token invalid, fall back to client credentials
        except Exception as e:
            logger.warning("User-token playlist fetch failed for %s: %s", playlist_id, e)

    if data is None:
        try:
            data = await spotify.get_playlist(playlist_id)
        except Exception as e:
            logger.exception("Client-credentials playlist fetch failed for %s", playlist_id)
            raise HTTPException(
                status_code=502, detail=f"Failed to fetch playlist from Spotify: {e}"
            ) from e
    if not data:
        raise HTTPException(status_code=404, detail="Playlist not found on Spotify")

    track_rows = dedupe_spotify_tracks(data["tracks"])
    playlist = Playlist(
        spotify_id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        owner=data["owner"],
        image_url=data.get("image_url", ""),
        track_count=len(track_rows),
        spotify_url=data.get("spotify_url", ""),
        last_checked=datetime.now(UTC),
    )
    db.add(playlist)
    db.flush()

    for t in track_rows:
        track = Track(
            playlist_id=playlist.id,
            spotify_id=t["id"],
            name=t["name"],
            artist=t["artist"],
            album=t["album"],
            genre=t.get("genre", ""),
            duration_ms=t["duration_ms"],
            image_url=t.get("image_url", ""),
            spotify_url=t.get("spotify_url", ""),
            is_new=False,
        )
        db.add(track)

    db.commit()
    db.refresh(playlist)
    return playlist


@router.get("/playlists", response_model=list[PlaylistResponse])
def list_playlists(
    db: Session = Depends(get_db),
    limit: int | None = None,
    offset: int = 0,
):
    """List playlists with optional pagination (limit, offset)."""
    q = db.query(Playlist).options(selectinload(Playlist.tracks)).order_by(Playlist.id)
    if offset:
        q = q.offset(offset)
    if limit is not None and limit > 0:
        q = q.limit(limit)
    return q.all()


@router.get("/playlists/{playlist_id}", response_model=PlaylistResponse)
def get_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = (
        db.query(Playlist)
        .options(selectinload(Playlist.tracks))
        .filter(Playlist.id == playlist_id)
        .first()
    )
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist


@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    db.delete(playlist)
    db.commit()
    return {"detail": "Playlist deleted"}


@router.post("/playlists/{playlist_id}/refresh", response_model=PlaylistResponse)
async def refresh_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = (
        db.query(Playlist)
        .options(selectinload(Playlist.tracks))
        .filter(Playlist.id == playlist_id)
        .first()
    )
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    spotify = get_spotify_service()
    # Non-blocking Spotify call
    data = await spotify.get_playlist(playlist.spotify_id)
    if not data:
        raise HTTPException(status_code=502, detail="Could not fetch playlist from Spotify")

    refresh_playlist_tracks(playlist, data, db)
    db.refresh(playlist)
    return playlist
