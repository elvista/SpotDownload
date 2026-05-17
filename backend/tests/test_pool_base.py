"""Unit tests for the pool-scraper framework (``services/pool_base.py``).

The Playwright-driven DJCity scraper itself can't run in CI without a real
browser + credentials, so we cover the *framework* exhaustively here and
exercise the routes via a stub scraper. The DJCity-specific row parsing
helpers are unit-tested in :mod:`test_pool_djcity_parsing`.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from database import SessionLocal
from models import PoolCredential
from services import pool_base
from services.pool_base import (
    CIRCUIT_BREAKER_THRESHOLD,
    CircuitBreaker,
    PoolUnavailableError,
    RateLimiter,
)

# --- pools_enabled feature flag ---------------------------------------------


def test_pools_enabled_off_by_default(monkeypatch):
    monkeypatch.delenv("UPSCALE_POOLS_ENABLED", raising=False)
    assert pool_base.pools_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "True", "yes", "on"])
def test_pools_enabled_truthy(monkeypatch, val):
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", val)
    assert pool_base.pools_enabled() is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "garbage"])
def test_pools_enabled_falsy(monkeypatch, val):
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", val)
    assert pool_base.pools_enabled() is False


# --- RateLimiter -------------------------------------------------------------


def test_rate_limiter_zero_interval_does_not_block():
    rl = RateLimiter(0)

    async def run():
        t0 = time.monotonic()
        await rl.acquire()
        await rl.acquire()
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    assert elapsed < 0.05


def test_rate_limiter_enforces_min_interval():
    rl = RateLimiter(50)  # 50 ms

    async def run():
        t0 = time.monotonic()
        await rl.acquire()
        await rl.acquire()
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    # Second call must wait ≥ 50 ms; allow scheduler jitter.
    assert elapsed >= 0.045


# --- CircuitBreaker ----------------------------------------------------------


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(threshold=3, cooldown_s=60)
    assert cb.is_open is False
    cb.record_error()
    cb.record_error()
    assert cb.is_open is False  # still under threshold
    cb.record_error()
    assert cb.is_open is True


def test_circuit_breaker_guard_raises_when_open():
    cb = CircuitBreaker(threshold=1, cooldown_s=60)
    cb.record_error()
    assert cb.is_open is True
    with pytest.raises(PoolUnavailableError):
        cb.guard()


def test_circuit_breaker_success_resets_counter():
    cb = CircuitBreaker(threshold=3, cooldown_s=60)
    cb.record_error()
    cb.record_error()
    cb.record_success()
    cb.record_error()
    cb.record_error()
    assert cb.is_open is False  # counter was reset


def test_circuit_breaker_half_open_after_cooldown():
    cb = CircuitBreaker(threshold=1, cooldown_s=0.05)
    cb.record_error()
    assert cb.is_open is True
    time.sleep(0.06)
    # After cooldown the breaker reports closed (half-open semantics: one
    # trial call is allowed; record_success/record_error decides next).
    assert cb.is_open is False


def test_circuit_breaker_uses_module_threshold_default():
    cb = CircuitBreaker()
    for _ in range(CIRCUIT_BREAKER_THRESHOLD - 1):
        cb.record_error()
    assert cb.is_open is False
    cb.record_error()
    assert cb.is_open is True


# --- State persistence -------------------------------------------------------


def test_write_and_clear_pool_state_round_trip(setup_test_db, tmp_path, monkeypatch):
    """Encrypted DB write + plaintext disk write + clear all reconcile."""
    # Use an isolated state dir so we don't litter the dev cache.
    monkeypatch.setattr(pool_base, "POOL_STATE_DIR", tmp_path / "pool-state")

    db = SessionLocal()
    try:
        # Wipe any pre-existing row from earlier tests.
        db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").delete()
        db.commit()

        sample = {"cookies": [{"name": "session", "value": "abc"}], "origins": []}
        pool_base.write_pool_state(db, "djcity", sample)

        # On-disk file exists and is the unencrypted JSON we passed in.
        disk = pool_base.pool_state_file("djcity")
        assert disk.exists()
        assert json.loads(disk.read_text()) == sample

        # DB row exists with a non-empty (encrypted) blob.
        row = db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first()
        assert row is not None
        assert row.state_blob
        assert row.last_login is not None
        # If ENCRYPTION_KEY is set in the env the blob is prefixed `enc:`;
        # otherwise it's stored as-is. Either way it must be non-empty.
        # We don't assert the prefix because the test env may not have a key.

        # restore_pool_state_to_disk is a no-op when disk file exists.
        restored = pool_base.restore_pool_state_to_disk(db, "djcity")
        assert restored == disk

        # Delete the on-disk file → restore_pool_state_to_disk re-creates it.
        disk.unlink()
        restored = pool_base.restore_pool_state_to_disk(db, "djcity")
        assert restored is not None
        assert restored.exists()
        assert json.loads(restored.read_text()) == sample

        # Clear wipes both sides.
        cleared = pool_base.clear_pool_state(db, "djcity")
        assert cleared is True
        assert not disk.exists()
        row = db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first()
        assert row is None

        # Clear is idempotent.
        assert pool_base.clear_pool_state(db, "djcity") is False
    finally:
        db.close()


def test_record_pool_error_only_updates_existing_row(setup_test_db, tmp_path, monkeypatch):
    monkeypatch.setattr(pool_base, "POOL_STATE_DIR", tmp_path / "pool-state")
    db = SessionLocal()
    try:
        db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").delete()
        db.commit()
        # No row yet → no phantom row created.
        pool_base.record_pool_error(db, "djcity", "boom")
        assert db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first() is None

        pool_base.write_pool_state(db, "djcity", {"cookies": []})
        pool_base.record_pool_error(db, "djcity", "later boom")
        row = db.query(PoolCredential).filter(PoolCredential.pool_slug == "djcity").first()
        assert row is not None
        assert row.last_error == "later boom"

        pool_base.clear_pool_state(db, "djcity")
    finally:
        db.close()


# --- Registry ----------------------------------------------------------------


def test_registry_contains_djcity_after_import():
    # Importing services.pool_djcity (which routers/upscale.py does) registers
    # the singleton scraper. The conftest already imports the app, which
    # transitively imports it.
    scraper = pool_base.get_scraper("djcity")
    assert scraper is not None
    assert scraper.slug == "djcity"
    assert scraper.display_name == "DJcity"


def test_registry_returns_none_for_unknown_slug():
    assert pool_base.get_scraper("totally-fake-pool") is None
