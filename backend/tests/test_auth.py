"""Tests for auth API."""

from routers.auth import spotify_redirect_uri_warnings


def test_spotify_redirect_uri_warnings_typo():
    assert spotify_redirect_uri_warnings("http://127.0.01:8000/api/auth/spotify/callback")
    assert not spotify_redirect_uri_warnings("http://127.0.0.1:8000/api/auth/spotify/callback")


def test_spotify_status_disconnected(client):
    """GET /api/auth/spotify/status when not connected."""
    r = client.get("/api/auth/spotify/status")
    assert r.status_code == 200
    data = r.json()
    assert data["connected"] is False
    assert data["has_token"] is False
    assert "redirect_uri" in data
    assert "redirect_uri_warnings" in data
    assert isinstance(data["redirect_uri_warnings"], list)


def test_spotify_status_connected(client, db_session):
    """GET /api/auth/spotify/status when token is stored."""
    from models import AppSetting

    db_session.add(AppSetting(key="spotify_refresh_token", value="fake_refresh"))
    db_session.commit()

    r = client.get("/api/auth/spotify/status")
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert r.json()["has_token"] is True


def test_spotify_disconnect(client, db_session):
    """DELETE /api/auth/spotify clears tokens."""
    from models import AppSetting

    db_session.add(AppSetting(key="spotify_refresh_token", value="token"))
    db_session.add(AppSetting(key="spotify_access_token", value="access"))
    db_session.commit()

    r = client.delete("/api/auth/spotify")
    assert r.status_code == 200
    assert "disconnected" in r.json()["detail"].lower()

    r2 = client.get("/api/auth/spotify/status")
    assert r2.json()["connected"] is False


def test_spotify_login_redirects(client, monkeypatch):
    """GET /api/auth/spotify returns redirect to Spotify."""
    import routers.auth as auth_router

    patched = auth_router.settings.model_copy(
        update={"SPOTIFY_CLIENT_ID": "test_client_id", "SPOTIFY_CLIENT_SECRET": "test_client_secret"}
    )
    monkeypatch.setattr(auth_router, "settings", patched)

    r = client.get("/api/auth/spotify", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers.get("location", "")
    assert "spotify.com" in loc
    assert "code_challenge=" in loc
    assert "code_challenge_method=S256" in loc
    assert "state=" in loc


def test_spotify_callback_no_code(client):
    """GET /api/auth/spotify/callback without code returns 400."""
    r = client.get("/api/auth/spotify/callback")
    assert r.status_code == 400
    assert "code" in r.json()["detail"].lower()
