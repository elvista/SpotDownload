import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from config import settings


class SpotifyService:
    def __init__(self):
        self._sp = None

    @property
    def sp(self):
        if self._sp is None:
            if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
                raise RuntimeError(
                    "Spotify credentials not configured. "
                    "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env"
                )
            auth_manager = SpotifyClientCredentials(
                client_id=settings.SPOTIFY_CLIENT_ID,
                client_secret=settings.SPOTIFY_CLIENT_SECRET,
            )
            self._sp = spotipy.Spotify(auth_manager=auth_manager)
        return self._sp

    def extract_playlist_id(self, url: str) -> str | None:
        patterns = [
            r"spotify\.com/playlist/([a-zA-Z0-9]+)",
            r"spotify:playlist:([a-zA-Z0-9]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def get_playlist(self, playlist_id: str) -> dict | None:
        try:
            result = self.sp.playlist(playlist_id)
        except Exception:
            return None

        tracks = []
        items = result["tracks"]["items"]

        # Handle pagination
        while True:
            for item in items:
                track = item.get("track")
                if not track or not track.get("id"):
                    continue
                tracks.append({
                    "id": track["id"],
                    "name": track["name"],
                    "artist": ", ".join(a["name"] for a in track["artists"]),
                    "album": track["album"]["name"],
                    "duration_ms": track["duration_ms"],
                    "image_url": (
                        track["album"]["images"][0]["url"]
                        if track["album"]["images"]
                        else ""
                    ),
                    "spotify_url": track["external_urls"].get("spotify", ""),
                })

            next_page = result["tracks"].get("next")
            if not next_page:
                break
            result["tracks"] = self.sp.next(result["tracks"])
            items = result["tracks"]["items"]

        images = result.get("images", [])
        return {
            "id": result["id"],
            "name": result["name"],
            "description": result.get("description", ""),
            "owner": result["owner"]["display_name"],
            "image_url": images[0]["url"] if images else "",
            "spotify_url": result["external_urls"].get("spotify", ""),
            "tracks": tracks,
        }
