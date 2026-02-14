from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import Playlist, Track
from services.spotify import SpotifyService


class MonitorService:
    def __init__(self):
        self.spotify = SpotifyService()

    def check_one(self, playlist_id: int, db: Session) -> dict:
        playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
        if not playlist:
            return {"error": "Playlist not found"}

        data = self.spotify.get_playlist(playlist.spotify_id)
        if not data:
            return {"error": "Could not fetch from Spotify"}

        existing_ids = {t.spotify_id for t in playlist.tracks}
        new_track_ids = {t["id"] for t in data["tracks"]}

        added = [t for t in data["tracks"] if t["id"] not in existing_ids]
        removed_ids = existing_ids - new_track_ids

        # Mark existing tracks as not new
        for track in playlist.tracks:
            track.is_new = False

        # Remove old tracks
        for track in list(playlist.tracks):
            if track.spotify_id in removed_ids:
                db.delete(track)

        # Add new tracks
        for t in added:
            track = Track(
                playlist_id=playlist.id,
                spotify_id=t["id"],
                name=t["name"],
                artist=t["artist"],
                album=t["album"],
                duration_ms=t["duration_ms"],
                image_url=t.get("image_url", ""),
                spotify_url=t.get("spotify_url", ""),
                is_new=True,
            )
            db.add(track)

        playlist.last_checked = datetime.now(timezone.utc)
        playlist.track_count = len(data["tracks"])
        db.commit()

        return {
            "playlist_id": playlist.id,
            "playlist_name": playlist.name,
            "added": len(added),
            "removed": len(removed_ids),
            "total": len(data["tracks"]),
        }

    def check_all(self, db: Session) -> list[dict]:
        playlists = (
            db.query(Playlist).filter(Playlist.is_monitoring == True).all()  # noqa: E712
        )
        results = []
        for p in playlists:
            result = self.check_one(p.id, db)
            results.append(result)
        return results
