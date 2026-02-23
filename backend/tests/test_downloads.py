"""Tests for downloads API."""


def test_start_download_no_body(client):
    """POST /api/downloads with neither track_ids nor playlist_id returns 400."""
    r = client.post("/api/downloads", json={})
    assert r.status_code == 400
    assert "track_ids" in r.json()["detail"].lower() or "playlist_id" in r.json()["detail"].lower()


def test_start_download_empty_track_ids(client):
    """POST /api/downloads with empty track_ids and no playlist_id returns 400."""
    r = client.post("/api/downloads", json={"track_ids": []})
    assert r.status_code == 400


def test_start_download_no_tracks_found(client, db_session):
    """POST /api/downloads with non-existent playlist_id returns 404."""
    r = client.post("/api/downloads", json={"playlist_id": 99999})
    assert r.status_code == 404
    assert "no tracks" in r.json()["detail"].lower() or "not found" in r.json()["detail"].lower()


def test_clear_progress(client):
    """DELETE /api/downloads/progress clears progress and returns 200."""
    r = client.delete("/api/downloads/progress")
    assert r.status_code == 200
    assert "cleared" in r.json()["detail"].lower()
