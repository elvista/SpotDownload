#!/usr/bin/env python3
"""
Export SpotDownload playlists and tracks to a JSON file.
Run from backend directory: python scripts/backup.py [output.json]
"""
import json
import os
import sys
from pathlib import Path

# Add backend to path so we can import config and models
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from sqlalchemy.orm import selectinload  # noqa: E402

from database import SessionLocal, init_db  # noqa: E402
from models import Playlist  # noqa: E402

init_db()
db = SessionLocal()
try:
    playlists = (
        db.query(Playlist)
        .options(selectinload(Playlist.tracks))
        .order_by(Playlist.id)
        .all()
    )
    out = {
        "playlists": [
            {
                "spotify_id": pl.spotify_id,
                "name": pl.name,
                "description": pl.description or "",
                "owner": pl.owner or "",
                "image_url": pl.image_url or "",
                "track_count": pl.track_count,
                "spotify_url": pl.spotify_url or "",
                "is_monitoring": pl.is_monitoring,
                "tracks": [
                    {
                        "spotify_id": t.spotify_id,
                        "name": t.name,
                        "artist": t.artist,
                        "album": t.album or "",
                        "genre": getattr(t, "genre", "") or "",
                        "duration_ms": t.duration_ms,
                        "image_url": t.image_url or "",
                        "spotify_url": t.spotify_url or "",
                        "is_new": t.is_new,
                        "is_downloaded": t.is_downloaded,
                    }
                    for t in pl.tracks
                ],
            }
            for pl in playlists
        ],
    }
    out_path = sys.argv[1] if len(sys.argv) > 1 else "spotdownload_backup.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Exported {len(playlists)} playlists to {out_path}")
finally:
    db.close()
