from sqlalchemy.orm import Session, selectinload

from models import Playlist
from services.spotify import get_spotify_service
from services.sync_ops import refresh_playlist_tracks


class MonitorService:
    def __init__(self):
        self.spotify = get_spotify_service()

    def check_one(self, playlist_id: int, db: Session) -> dict:
        playlist = (
            db.query(Playlist)
            .options(selectinload(Playlist.tracks))
            .filter(Playlist.id == playlist_id)
            .first()
        )
        if not playlist:
            return {"error": "Playlist not found"}

        data = self.spotify.get_playlist_sync(playlist.spotify_id)
        if not data:
            return {"error": "Could not fetch from Spotify"}

        return refresh_playlist_tracks(playlist, data, db)

    def check_all(self, db: Session) -> list[dict]:
        playlists = (
            db.query(Playlist)
            .options(selectinload(Playlist.tracks))
            .filter(Playlist.is_monitoring == True)  # noqa: E712
            .all()
        )
        results = []
        for p in playlists:
            data = self.spotify.get_playlist_sync(p.spotify_id)
            if not data:
                results.append({"error": f"Could not fetch {p.name}"})
                continue
            result = refresh_playlist_tracks(p, data, db)
            results.append(result)
        return results
