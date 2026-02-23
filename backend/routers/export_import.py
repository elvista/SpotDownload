"""Export and import playlists + tracks as JSON backup."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from database import get_db
from models import Playlist, Track

router = APIRouter(tags=["export-import"])


class TrackExport(BaseModel):
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


class PlaylistExport(BaseModel):
    spotify_id: str
    name: str
    description: str
    owner: str
    image_url: str
    track_count: int
    spotify_url: str
    is_monitoring: bool
    tracks: list[TrackExport] = []


class ExportPayload(BaseModel):
    playlists: list[PlaylistExport]
    exported_at: str


class ImportPayload(BaseModel):
    playlists: list[PlaylistExport]


@router.get("/export", response_class=JSONResponse)
def export_data(db: Session = Depends(get_db)) -> dict:
    """Export all playlists and their tracks as JSON."""
    playlists = (
        db.query(Playlist)
        .options(selectinload(Playlist.tracks))
        .order_by(Playlist.id)
        .all()
    )
    out = []
    for pl in playlists:
        out.append(
            PlaylistExport(
                spotify_id=pl.spotify_id,
                name=pl.name,
                description=pl.description or "",
                owner=pl.owner or "",
                image_url=pl.image_url or "",
                track_count=pl.track_count,
                spotify_url=pl.spotify_url or "",
                is_monitoring=pl.is_monitoring,
                tracks=[
                    TrackExport(
                        spotify_id=t.spotify_id,
                        name=t.name,
                        artist=t.artist,
                        album=t.album or "",
                        genre=getattr(t, "genre", "") or "",
                        duration_ms=t.duration_ms,
                        image_url=t.image_url or "",
                        spotify_url=t.spotify_url or "",
                        is_new=t.is_new,
                        is_downloaded=t.is_downloaded,
                    )
                    for t in pl.tracks
                ],
            )
        )
    return {
        "playlists": [p.model_dump() for p in out],
        "exported_at": datetime.now(UTC).isoformat(),
    }


@router.post("/import")
def import_data(
    body: ImportPayload,
    db: Session = Depends(get_db),
) -> dict:
    """Import playlists and tracks from a previous export. Skips playlists that already exist (by spotify_id)."""
    created = 0
    skipped = 0
    for pl_data in body.playlists:
        existing = db.query(Playlist).filter(Playlist.spotify_id == pl_data.spotify_id).first()
        if existing:
            skipped += 1
            continue
        playlist = Playlist(
            spotify_id=pl_data.spotify_id,
            name=pl_data.name,
            description=pl_data.description,
            owner=pl_data.owner,
            image_url=pl_data.image_url,
            track_count=len(pl_data.tracks),
            spotify_url=pl_data.spotify_url,
            is_monitoring=pl_data.is_monitoring,
        )
        db.add(playlist)
        db.flush()
        for t in pl_data.tracks:
            track = Track(
                playlist_id=playlist.id,
                spotify_id=t.spotify_id,
                name=t.name,
                artist=t.artist,
                album=t.album,
                genre=t.genre,
                duration_ms=t.duration_ms,
                image_url=t.image_url,
                spotify_url=t.spotify_url,
                is_new=t.is_new,
                is_downloaded=t.is_downloaded,
            )
            db.add(track)
        created += 1
    db.commit()
    return {
        "detail": "Import complete",
        "playlists_created": created,
        "playlists_skipped": skipped,
    }
