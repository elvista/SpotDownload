"""Spotify Web API client: playlists, artists, genres, and user OAuth for archive/empty."""

import asyncio
import json
import logging
import re
import time

import httpx
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger("cratedigger.spotify")

try:
    from spotipy.exceptions import SpotifyException, SpotifyOauthError
except ImportError:
    SpotifyException = Exception  # type: ignore[misc, assignment]
    SpotifyOauthError = Exception  # type: ignore[misc, assignment]


class SpotifyAuthError(Exception):
    """Raised when Spotify returns 401 (token expired or invalid)."""


def _is_retryable_spotify(exc: BaseException) -> bool:
    """Retry on rate limit (429) or server errors (5xx)."""
    if isinstance(exc, SpotifyException) and getattr(exc, "http_status", None) in (
        429,
        500,
        502,
        503,
    ):
        return True
    return False


# Module-level singleton
_instance = None


def get_spotify_service():
    global _instance
    if _instance is None:
        _instance = SpotifyService()
    return _instance


class SpotifyService:
    def __init__(self):
        self._sp = None
        self._artist_genre_cache: dict[str, str] = {}

    def _get_artist_genre_cached(self, artist_id: str) -> str:
        """Return genre for artist (first genre). Uses in-memory cache."""
        if not artist_id:
            return ""
        if artist_id in self._artist_genre_cache:
            return self._artist_genre_cache[artist_id]
        try:
            artist = self.sp.artist(artist_id)
            genres = artist.get("genres") or []
            genre = genres[0] if genres else ""
            self._artist_genre_cache[artist_id] = genre
            return genre
        except Exception as e:
            logger.warning(f"Failed to fetch artist genre for {artist_id}: {e}")
            self._artist_genre_cache[artist_id] = ""
            return ""

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

    @staticmethod
    def extract_playlist_id(url: str) -> str | None:
        patterns = [
            r"spotify\.com/playlist/([a-zA-Z0-9_-]+)",
            r"spotify:playlist:([a-zA-Z0-9_-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @retry(
        retry=retry_if_exception(_is_retryable_spotify),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=60),
    )
    def _fetch_playlist_page(self, playlist_id: str, sp=None) -> dict:
        """Fetch playlist metadata from API (retries on 429/5xx). Uses optional sp client (user auth).

        Feb 2026: Spotify stopped including `tracks` in the default `/playlists/{id}`
        response for non-owned playlists. Tracks are fetched separately via
        `_fetch_playlist_items` hitting the renamed `/playlists/{id}/items` endpoint.
        """
        client = sp if sp is not None else self.sp
        return client.playlist(playlist_id)

    @retry(
        retry=retry_if_exception(_is_retryable_spotify),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=60),
    )
    def _fetch_playlist_items(
        self, playlist_id: str, sp=None, limit: int = 100, offset: int = 0
    ) -> dict:
        """Fetch a page of playlist items via the Feb 2026 `/playlists/{id}/items` endpoint."""
        client = sp if sp is not None else self.sp
        return client._get(
            f"playlists/{playlist_id}/items",
            limit=limit,
            offset=offset,
            additional_types="track",
        )

    def _fetch_playlist_tracks_via_embed(
        self, playlist_id: str, playlist_image_url: str = ""
    ) -> list[dict]:
        """Fetch tracks for a public playlist by scraping the public embed page.

        Used as a fallback when the Web API blocks track access in Development Mode
        for non-owned public playlists. The embed page inlines a `__NEXT_DATA__`
        JSON blob with up to 100 tracks. Beyond 100 tracks cannot be retrieved
        through this mechanism.
        """
        url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        try:
            with httpx.Client(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}) as c:
                r = c.get(url)
            if r.status_code != 200:
                logger.warning("Embed fetch for %s returned %s", playlist_id, r.status_code)
                return []
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                r.text,
                re.DOTALL,
            )
            if not match:
                logger.warning("Embed for %s missing __NEXT_DATA__", playlist_id)
                return []
            data = json.loads(match.group(1))
            track_list = (
                data.get("props", {})
                .get("pageProps", {})
                .get("state", {})
                .get("data", {})
                .get("entity", {})
                .get("trackList")
                or []
            )
        except Exception as e:
            logger.warning("Embed parse failed for %s: %s", playlist_id, e)
            return []

        tracks = []
        for entry in track_list:
            uri = entry.get("uri") or ""
            if not uri.startswith("spotify:track:"):
                continue
            track_id = uri.split(":", 2)[-1]
            tracks.append(
                {
                    "id": track_id,
                    "name": entry.get("title") or "",
                    "artist": entry.get("subtitle") or "",
                    "album": "",
                    "duration_ms": int(entry.get("duration") or 0),
                    "image_url": playlist_image_url,
                    "spotify_url": f"https://open.spotify.com/track/{track_id}",
                    "genre": "",
                }
            )
        return tracks

    def _fetch_artists_batch(self, artist_ids: list[str]) -> None:
        """Fetch artists in chunks of 50 and populate genre cache. Spotify API limit is 50."""
        if not artist_ids:
            return
        for i in range(0, len(artist_ids), 50):
            chunk = artist_ids[i : i + 50]
            try:
                response = self.sp.artists(chunk)
                for artist in response.get("artists", []):
                    if artist and artist.get("id"):
                        genres = artist.get("genres") or []
                        self._artist_genre_cache[artist["id"]] = genres[0] if genres else ""
            except Exception as e:
                logger.warning("Batch artist fetch failed: %s", e)

    def _get_playlist_sync(self, playlist_id: str, sp=None) -> dict | None:
        """Synchronous Spotify API call (runs in thread pool). Uses optional sp client (user auth)."""
        client = sp if sp is not None else self.sp
        try:
            result = self._fetch_playlist_page(playlist_id, sp=client)
        except Exception as e:
            logger.warning("Spotify get_playlist failed for id=%s: %s", playlist_id, e)
            return None

        # Spotify Feb 2026: playlist response key renamed "tracks" → "items",
        # per-entry key renamed "track" → "item".
        paging = result.get("items") or result.get("tracks")
        if not isinstance(paging, dict) or "items" not in paging:
            # Non-owned / editorial playlists omit the embedded tracks object.
            # Fetch items separately via the renamed /playlists/{id}/items endpoint.
            try:
                paging = self._fetch_playlist_items(playlist_id, sp=client)
            except Exception as e:
                logger.warning(
                    "Spotify items fetch failed for id=%s: %s", playlist_id, e
                )
                paging = {"items": [], "next": None}
        all_items = list(paging.get("items") or [])
        while paging.get("next"):
            try:
                paging = client.next(paging)
            except Exception as e:
                logger.warning("Spotify pagination failed for id=%s: %s", playlist_id, e)
                break
            all_items.extend(paging.get("items") or [])

        # Collect unique artist IDs and batch-fetch genres (max 50 per request)
        artist_ids = []
        seen = set()
        for entry in all_items:
            track = entry.get("item") or entry.get("track")
            if not track or not track.get("id") or not track.get("artists"):
                continue
            aid = track["artists"][0]["id"]
            if aid and aid not in seen:
                seen.add(aid)
                artist_ids.append(aid)
        self._fetch_artists_batch(artist_ids)

        tracks = []
        for entry in all_items:
            track = entry.get("item") or entry.get("track")
            if not track or not track.get("id") or not track.get("artists"):
                continue
            artist_id = track["artists"][0]["id"] if track.get("artists") else None
            genre = self._artist_genre_cache.get(artist_id, "") if artist_id else ""
            tracks.append(
                {
                    "id": track["id"],
                    "name": track["name"],
                    "artist": ", ".join(a["name"] for a in track["artists"]),
                    "album": track["album"]["name"],
                    "duration_ms": track["duration_ms"],
                    "image_url": (
                        track["album"]["images"][0]["url"] if track["album"]["images"] else ""
                    ),
                    "spotify_url": track["external_urls"].get("spotify", ""),
                    "genre": genre,
                }
            )

        images = result.get("images", [])
        playlist_image_url = images[0]["url"] if images else ""

        # Dev Mode fallback: if the API blocked track access for a non-owned public
        # playlist, scrape the public embed page (first 100 tracks only).
        if not tracks:
            embed_tracks = self._fetch_playlist_tracks_via_embed(
                playlist_id, playlist_image_url=playlist_image_url
            )
            if embed_tracks:
                logger.info(
                    "Used embed fallback for playlist %s (%d tracks)",
                    playlist_id,
                    len(embed_tracks),
                )
                tracks = embed_tracks

        return {
            "id": result["id"],
            "name": result["name"],
            "description": result.get("description", ""),
            "owner": result["owner"]["display_name"],
            "image_url": playlist_image_url,
            "spotify_url": result["external_urls"].get("spotify", ""),
            "tracks": tracks,
        }

    async def get_playlist(self, playlist_id: str, sp_client=None) -> dict | None:
        """Non-blocking: runs Spotify API calls in a thread pool. Uses optional sp_client (user auth)."""
        return await asyncio.to_thread(self._get_playlist_sync, playlist_id, sp_client)

    def get_playlist_sync(self, playlist_id: str, sp=None) -> dict | None:
        """Blocking version for use in sync contexts (e.g. APScheduler)."""
        return self._get_playlist_sync(playlist_id, sp)

    def get_user_client(self, access_token: str, refresh_token: str, expires_at: int):
        """Get a user-authenticated Spotify client with token refresh."""
        auth_manager = SpotifyOAuth(
            client_id=settings.SPOTIFY_CLIENT_ID,
            client_secret=settings.SPOTIFY_CLIENT_SECRET,
            redirect_uri=settings.SPOTIFY_REDIRECT_URI,
            cache_path=None,
        )

        # Manually set token info
        token_info = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "token_type": "Bearer",
            "scope": "playlist-modify-public playlist-modify-private playlist-read-private",
        }

        # Check if token needs refresh
        if expires_at < int(time.time()):
            logger.info("Access token expired, refreshing...")
            try:
                token_info = auth_manager.refresh_access_token(refresh_token)
            except SpotifyOauthError as e:
                raise SpotifyAuthError("Spotify authentication expired") from e
            except Exception as e:
                if isinstance(e, SpotifyException) and getattr(e, "http_status", None) == 401:
                    raise SpotifyAuthError("Spotify authentication expired") from e
                raise

        return spotipy.Spotify(auth=token_info["access_token"]), token_info

    def _get_or_create_archive_playlist_sync(self, sp_user, archive_name: str) -> str | None:
        """Find or create the single archive playlist by name. Returns playlist ID."""
        try:
            user_id = sp_user.me()["id"]

            # Search user's playlists for exact name match
            offset = 0
            limit = 50
            while True:
                results = sp_user.current_user_playlists(limit=limit, offset=offset)
                for playlist in results["items"]:
                    if playlist["name"] == archive_name:
                        logger.info(
                            f"Found existing archive playlist: {archive_name} (id: {playlist['id']})"
                        )
                        return playlist["id"]

                if not results["next"]:
                    break
                offset += limit

            # No playlist found, create one
            logger.info(f"Creating new archive playlist: {archive_name}")
            new_playlist = sp_user.user_playlist_create(
                user_id,
                archive_name,
                public=False,
                description="Archive for downloaded tracks from CrateDigger",
            )
            return new_playlist["id"]

        except SpotifyException as e:
            if getattr(e, "http_status", None) == 401:
                raise SpotifyAuthError("Spotify authentication expired") from e
            logger.error(f"Failed to get or create archive playlist: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get or create archive playlist: {e}")
            return None

    async def get_or_create_archive_playlist(self, sp_user, archive_name: str) -> str | None:
        """Non-blocking: find or create the single archive playlist by name."""
        return await asyncio.to_thread(
            self._get_or_create_archive_playlist_sync, sp_user, archive_name
        )

    def _add_tracks_to_playlist_sync(
        self, sp_user, playlist_id: str, track_uris: list[str]
    ) -> bool:
        """Add tracks to playlist in batches of 100."""
        try:
            # Spotify allows max 100 tracks per request
            batch_size = 100
            for i in range(0, len(track_uris), batch_size):
                batch = track_uris[i : i + batch_size]
                sp_user.playlist_add_items(playlist_id, batch)
                logger.info(f"Added {len(batch)} tracks to playlist {playlist_id}")
            return True
        except SpotifyException as e:
            if getattr(e, "http_status", None) == 401:
                raise SpotifyAuthError("Spotify authentication expired") from e
            logger.error(f"Failed to add tracks to playlist: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to add tracks to playlist: {e}")
            return False

    async def add_tracks_to_playlist(
        self, sp_user, playlist_id: str, track_uris: list[str]
    ) -> bool:
        """Non-blocking: add tracks to playlist."""
        return await asyncio.to_thread(
            self._add_tracks_to_playlist_sync, sp_user, playlist_id, track_uris
        )

    def _empty_playlist_sync(self, sp_user, playlist_id: str) -> bool:
        """Remove all tracks from a playlist."""
        try:
            # Get all track URIs via full playlist fetch (playlist_tracks 403s in Dev Mode)
            result = sp_user.playlist(playlist_id)
            paging = result.get("items") or result.get("tracks")

            track_uris = []
            for entry in paging["items"]:
                track = entry.get("item") or entry.get("track")
                if track and track.get("uri"):
                    track_uris.append(track["uri"])

            while paging.get("next"):
                paging = sp_user.next(paging)
                for entry in paging["items"]:
                    track = entry.get("item") or entry.get("track")
                    if track and track.get("uri"):
                        track_uris.append(track["uri"])

            if not track_uris:
                logger.info(f"Playlist {playlist_id} is already empty")
                return True

            # Remove in batches of 100
            batch_size = 100
            for i in range(0, len(track_uris), batch_size):
                batch = track_uris[i : i + batch_size]
                sp_user.playlist_remove_all_occurrences_of_items(playlist_id, batch)
                logger.info(f"Removed {len(batch)} tracks from playlist {playlist_id}")

            logger.info(f"Emptied playlist {playlist_id} ({len(track_uris)} tracks removed)")
            return True

        except SpotifyException as e:
            if getattr(e, "http_status", None) == 401:
                raise SpotifyAuthError("Spotify authentication expired") from e
            logger.error(f"Failed to empty playlist: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to empty playlist: {e}")
            return False

    async def empty_playlist(self, sp_user, playlist_id: str) -> bool:
        """Non-blocking: remove all tracks from playlist."""
        return await asyncio.to_thread(self._empty_playlist_sync, sp_user, playlist_id)
