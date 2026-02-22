from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel
from database import get_db
from services.spotify import get_spotify_service
from services.sync_ops import refresh_playlist_tracks
from models import Playlist, Track
from datetime import datetime, timezone

router = APIRouter(tags=["playlists"])


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

    class Config:
        from_attributes = True


@router.post("/playlists", response_model=PlaylistResponse)
async def add_playlist(body: PlaylistCreate, db: Session = Depends(get_db)):
    spotify = get_spotify_service()
    playlist_id = spotify.extract_playlist_id(body.url)
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Invalid Spotify playlist URL")

    existing = db.query(Playlist).filter(Playlist.spotify_id == playlist_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Playlist already added")

    # Non-blocking Spotify call
    data = await spotify.get_playlist(playlist_id)
    if not data:
        raise HTTPException(status_code=404, detail="Playlist not found on Spotify")

    playlist = Playlist(
        spotify_id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        owner=data["owner"],
        image_url=data.get("image_url", ""),
        track_count=len(data["tracks"]),
        spotify_url=data.get("spotify_url", ""),
        last_checked=datetime.now(timezone.utc),
    )
    db.add(playlist)
    db.flush()

    for t in data["tracks"]:
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
def list_playlists(db: Session = Depends(get_db)):
    return db.query(Playlist).options(selectinload(Playlist.tracks)).all()


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
