"""Tests for settings API."""


def test_get_settings_defaults(client):
    """GET /api/settings returns default values when none set."""
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "download_path" in data
    assert "monitor_interval_minutes" in data
    assert data["archive_playlist_name"] == "DJ Archive"


def test_update_settings_archive_name(client):
    """PUT /api/settings can update archive_playlist_name."""
    r = client.put(
        "/api/settings",
        json={"archive_playlist_name": "My Archive"},
    )
    assert r.status_code == 200
    assert r.json()["archive_playlist_name"] == "My Archive"

    r2 = client.get("/api/settings")
    assert r2.json()["archive_playlist_name"] == "My Archive"


def test_update_settings_monitor_interval(client):
    """PUT /api/settings can update monitor_interval_minutes."""
    r = client.put(
        "/api/settings",
        json={"monitor_interval_minutes": 15},
    )
    assert r.status_code == 200
    assert r.json()["monitor_interval_minutes"] == 15


def test_validate_path(client):
    """POST /api/settings/validate-path returns path info."""
    r = client.post(
        "/api/settings/validate-path",
        json={"download_path": "/tmp"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "path" in data
    assert "exists" in data
    assert "writable" in data
    assert "created" in data
