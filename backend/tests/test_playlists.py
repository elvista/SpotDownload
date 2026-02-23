"""Tests for playlists API."""

from unittest.mock import patch

from sqlalchemy.orm import Session

from models import Playlist, Track


def test_list_playlists_empty(client):
    """GET /api/playlists returns empty list when no playlists."""
    r = client.get("/api/playlists")
    assert r.status_code == 200
    assert r.json() == []


def test_list_playlists_with_data(client, db_session: Session):
    """GET /api/playlists returns playlists with tracks."""
    pl = Playlist(
        spotify_id="pid1",
        name="Test Playlist",
        description="",
        owner="user",
        track_count=1,
    )
    db_session.add(pl)
    db_session.flush()
    db_session.add(
        Track(
            playlist_id=pl.id,
            spotify_id="tid1",
            name="Track 1",
            artist="Artist 1",
            album="Album",
            duration_ms=200000,
        )
    )
    db_session.commit()

    r = client.get("/api/playlists")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Playlist"
    assert data[0]["spotify_id"] == "pid1"
    assert len(data[0]["tracks"]) == 1
    assert data[0]["tracks"][0]["name"] == "Track 1"


def test_get_playlist_not_found(client):
    """GET /api/playlists/999 returns 404."""
    r = client.get("/api/playlists/999")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_get_playlist_ok(client, db_session: Session):
    """GET /api/playlists/{id} returns playlist when exists."""
    pl = Playlist(
        spotify_id="pid2",
        name="My List",
        track_count=0,
    )
    db_session.add(pl)
    db_session.commit()

    r = client.get(f"/api/playlists/{pl.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "My List"
    assert r.json()["tracks"] == []


def test_delete_playlist_not_found(client):
    """DELETE /api/playlists/999 returns 404."""
    r = client.delete("/api/playlists/999")
    assert r.status_code == 404


def test_delete_playlist_ok(client, db_session: Session):
    """DELETE /api/playlists/{id} removes playlist."""
    pl = Playlist(spotify_id="pid3", name="To Delete", track_count=0)
    db_session.add(pl)
    db_session.commit()
    pid = pl.id

    r = client.delete(f"/api/playlists/{pid}")
    assert r.status_code == 200

    r2 = client.get(f"/api/playlists/{pid}")
    assert r2.status_code == 404


def test_add_playlist_invalid_url(client):
    """POST /api/playlists with invalid URL returns 400."""
    r = client.post("/api/playlists", json={"url": "https://example.com/not-spotify"})
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"].lower()


def test_add_playlist_url_with_query_string(client, db_session: Session):
    """POST /api/playlists accepts URL with query string (e.g. ?si=...)."""
    fake_playlist_data = {
        "id": "playlist_id_abc",
        "name": "Shared Playlist",
        "description": "",
        "owner": "user",
        "image_url": "",
        "spotify_url": "https://open.spotify.com/playlist/playlist_id_abc",
        "tracks": [],
    }

    class FakeSpotify:
        @staticmethod
        def extract_playlist_id(url: str):
            if "spotify" in url and "playlist" in url:
                return "playlist_id_abc"
            return None

        async def get_playlist(self, playlist_id: str):
            return fake_playlist_data

    with patch("routers.playlists.get_spotify_service", return_value=FakeSpotify()):
        r = client.post(
            "/api/playlists",
            json={"url": "https://open.spotify.com/playlist/playlist_id_abc?si=2205"},
        )
    assert r.status_code == 200
    assert r.json()["spotify_id"] == "playlist_id_abc"


def test_add_playlist_success(client, db_session: Session):
    """POST /api/playlists with valid URL and mocked Spotify creates playlist."""
    fake_playlist_data = {
        "id": "spotify_playlist_id_123",
        "name": "Fake Playlist",
        "description": "Desc",
        "owner": "owner",
        "image_url": "",
        "spotify_url": "https://open.spotify.com/playlist/spotify_playlist_id_123",
        "tracks": [
            {
                "id": "track1",
                "name": "Song One",
                "artist": "Artist A",
                "album": "Album A",
                "genre": "Pop",
                "duration_ms": 180000,
                "image_url": "",
                "spotify_url": "",
            }
        ],
    }

    class FakeSpotify:
        @staticmethod
        def extract_playlist_id(url: str):
            if "spotify" in url and "playlist" in url:
                return "spotify_playlist_id_123"
            return None

        async def get_playlist(self, playlist_id: str):
            return fake_playlist_data

    with patch("routers.playlists.get_spotify_service", return_value=FakeSpotify()):
        r = client.post(
            "/api/playlists",
            json={"url": "https://open.spotify.com/playlist/spotify_playlist_id_123"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Fake Playlist"
    assert data["spotify_id"] == "spotify_playlist_id_123"
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["name"] == "Song One"
    assert data["tracks"][0]["genre"] == "Pop"


def test_add_playlist_already_exists(client, db_session: Session):
    """POST /api/playlists with already-added playlist returns 409."""
    pl = Playlist(spotify_id="existing_id", name="Existing", track_count=0)
    db_session.add(pl)
    db_session.commit()

    class FakeSpotify:
        @staticmethod
        def extract_playlist_id(url: str):
            return "existing_id"

    with patch("routers.playlists.get_spotify_service", return_value=FakeSpotify()):
        r = client.post(
            "/api/playlists",
            json={"url": "https://open.spotify.com/playlist/existing_id"},
        )
    assert r.status_code == 409
    assert "already" in r.json()["detail"].lower()
