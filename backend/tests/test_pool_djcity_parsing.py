"""DJCity scraper unit tests — row parsing helpers + feature flag guards.

End-to-end Playwright tests are out of scope for CI (no browser, no real
credentials); we cover the structural behaviour of the scraper class that
doesn't require a live page.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services import pool_base
from services.pool_base import PoolAuthError, PoolDisabledError
from services.pool_djcity import (
    DJCityScraper,
    _parse_bitrate,
    _parse_duration,
)

# --- Pure parsing helpers ----------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("320 kbps", 320),
        ("128kbps", 128),
        ("256 KBPS", 256),
        ("Bitrate: 192", 192),
        ("", 0),
        ("no numbers", 0),
    ],
)
def test_parse_bitrate(text, expected):
    assert _parse_bitrate(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3:24", 204.0),
        ("0:30", 30.0),
        ("1:05:00", 3900.0),
        ("", None),
        ("garbage", None),
        ("not-a:time", None),
    ],
)
def test_parse_duration(text, expected):
    assert _parse_duration(text) == expected


# --- Feature-flag guards on every public method ------------------------------


def test_search_raises_when_pools_disabled(monkeypatch):
    monkeypatch.delenv("UPSCALE_POOLS_ENABLED", raising=False)
    scraper = DJCityScraper()
    with pytest.raises(PoolDisabledError):
        asyncio.run(scraper.search("test"))


def test_login_interactive_raises_when_pools_disabled(monkeypatch):
    monkeypatch.delenv("UPSCALE_POOLS_ENABLED", raising=False)
    scraper = DJCityScraper()
    with pytest.raises(PoolDisabledError):
        asyncio.run(scraper.login_interactive())


def test_search_returns_empty_for_blank_query(monkeypatch):
    """Even with pools enabled, empty queries short-circuit without hitting Playwright."""
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", "1")
    scraper = DJCityScraper()
    assert asyncio.run(scraper.search("   ")) == []


def test_search_raises_pool_auth_error_without_session(monkeypatch, tmp_path):
    """Pools enabled + no on-disk storage_state → clear auth error, not a crash."""
    monkeypatch.setenv("UPSCALE_POOLS_ENABLED", "1")
    monkeypatch.setattr(pool_base, "POOL_STATE_DIR", tmp_path / "pool-state")
    scraper = DJCityScraper()
    with pytest.raises(PoolAuthError):
        asyncio.run(scraper.search("test query"))


def test_download_is_stubbed_for_now():
    """Step 3 ships pool listing/login/search only; download lands in step 6."""
    scraper = DJCityScraper()
    with pytest.raises(NotImplementedError):
        asyncio.run(scraper.download("hit-1", Path("/tmp/out.mp3")))
