"""Tests for health and main app."""


def test_health(client):
    """GET /api/health returns ok."""
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "monitor_running" in data
