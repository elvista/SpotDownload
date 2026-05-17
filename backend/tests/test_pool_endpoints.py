"""Route-level tests for the pool endpoints (step 3).

Exercises ``GET /api/upscale/pools``, ``POST /api/upscale/pools/{slug}/login``,
and ``DELETE /api/upscale/pools/{slug}`` against the in-process app with a
stubbed scraper — no real Playwright launches.
"""

from __future__ import annotations

import asyncio

import pytest

from database import SessionLocal
from models import PoolCredential
from services import pool_base


@pytest.fixture(autouse=True)
def _reset_djcity_state(setup_test_db, tmp_path, monkeypatch):
    """Isolate pool-state cache per test + drop any leftover DB row."""
    monkeypatch.setattr(pool_base, "POOL_STATE_DIR", tmp_path / "pool-state")
    db = SessionLocal()
    try:
        db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").delete()
        db.commit()
    finally:
        db.close()


def test_get_pools_lists_djcity_with_disabled_flag(client, monkeypatch):
    monkeypatch.delenv("UPSCALE_POOLS_ENABLED", raising=False)
    r = client.get("/api/upscale/pools")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) >= 1
    djcity = next(p for p in body if p["slug"] == "djcity")
    assert djcity["display_name"] == "DJcity"
    assert djcity["enabled"] is False
    assert djcity["connected"] is False
    assert djcity["last_login"] is None


def test_get_pools_shows_enabled_flag_when_env_set(client, monkeypatch):
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", "1")
    r = client.get("/api/upscale/pools")
    assert r.status_code == 200
    djcity = next(p for p in r.json() if p["slug"] == "djcity")
    assert djcity["enabled"] is True


def test_post_login_returns_503_when_pools_disabled(client, monkeypatch):
    monkeypatch.delenv("UPSCALE_POOLS_ENABLED", raising=False)
    r = client.post("/api/upscale/pools/djcity/login")
    assert r.status_code == 503
    assert "UPSCALE_POOLS_ENABLED" in r.json()["detail"]


def test_post_login_returns_404_for_unknown_slug(client, monkeypatch):
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", "1")
    r = client.post("/api/upscale/pools/nope/login")
    assert r.status_code == 404


def test_post_login_runs_scraper_and_records_state(client, monkeypatch, tmp_path):
    """With a stub scraper that writes a fake storage_state, the route returns
    202 immediately and the background task records the encrypted blob in DB."""
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", "1")

    scraper = pool_base.get_scraper("djcity")
    assert scraper is not None

    # Stub login_interactive: write a fake storage_state to disk so the
    # background runner finds it and writes the encrypted DB row.
    async def fake_login() -> None:
        path = pool_base.pool_state_file("djcity")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"cookies": [{"name": "x", "value": "y"}], "origins": []}')

    monkeypatch.setattr(scraper, "login_interactive", fake_login)

    r = client.post("/api/upscale/pools/djcity/login")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "djcity"
    assert body["status"] == "started"

    # Let the background task run.
    asyncio.run(asyncio.sleep(0.05))
    # Drive the loop until the runner has written the DB row (≤1 s budget).
    db = SessionLocal()
    try:
        for _ in range(20):
            row = db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first()
            if row and row.state_blob:
                break
            db.expire_all()
            asyncio.run(asyncio.sleep(0.05))
        assert row is not None
        assert row.state_blob  # encrypted blob present
        assert row.last_error == ""
    finally:
        db.close()


def test_post_login_records_error_when_scraper_raises(client, monkeypatch):
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", "1")
    scraper = pool_base.get_scraper("djcity")
    assert scraper is not None

    async def fake_login() -> None:
        raise RuntimeError("simulated DJCity DOM change")

    monkeypatch.setattr(scraper, "login_interactive", fake_login)

    r = client.post("/api/upscale/pools/djcity/login")
    assert r.status_code == 200

    db = SessionLocal()
    try:
        for _ in range(20):
            row = db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first()
            if row and row.last_error:
                break
            db.expire_all()
            asyncio.run(asyncio.sleep(0.05))
        assert row is not None
        assert "simulated DJCity DOM change" in row.last_error
        # No usable session was captured.
        assert row.state_blob == ""
    finally:
        db.close()


def test_delete_pool_clears_state(client, db_session, monkeypatch):
    """Seed + verify via the same ``db_session`` the route uses, so the test
    sees the route's internal commits despite the outer-transaction rollback
    wrapper. Disk-file cleanup is independent of the DB session."""
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", "1")

    # Seed through the wrapped session — the client fixture binds the route's
    # get_db to this same session, so the DELETE sees the seeded row.
    pool_base.write_pool_state(db_session, "djcity", {"cookies": [], "origins": []})
    assert (
        db_session.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first()
        is not None
    )

    r = client.delete("/api/upscale/pools/djcity")
    assert r.status_code == 204

    db_session.expire_all()
    assert (
        db_session.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first()
        is None
    )
    assert not pool_base.pool_state_file("djcity").exists()


def test_delete_unknown_pool_returns_404(client):
    r = client.delete("/api/upscale/pools/no-such-pool")
    assert r.status_code == 404
