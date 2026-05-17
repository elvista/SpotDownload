"""Tests for the DJCity → zipDJ → BPM Supreme fallback orchestrator.

Each test swaps the three real scrapers in the registry for async stubs so
we exercise the fallback logic without touching Playwright. The orchestrator
itself is the unit under test; pool-specific Playwright behaviour lives in
:mod:`test_pool_djcity_parsing` (and would in test_pool_zipdj_parsing /
test_pool_bpmsupreme_parsing if those modules were less trivially parallel
to DJCity's).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from database import SessionLocal
from models import AppSetting
from services import pool_base, pool_orchestrator
from services.pool_base import (
    PoolAuthError,
    PoolDisabledError,
    PoolHit,
    PoolUnavailableError,
)
from services.pool_orchestrator import OrchestratorResult


@dataclass
class _StubScraper:
    """Drop-in for a PoolScraper. Records call count + can raise on demand."""

    slug: str
    display_name: str
    hits: list[PoolHit]
    raise_with: BaseException | None = None
    call_count: int = 0

    async def login_interactive(self) -> None:  # pragma: no cover — not exercised here
        return None

    async def search(self, query: str, *, limit: int = 25) -> list[PoolHit]:
        self.call_count += 1
        if self.raise_with is not None:
            raise self.raise_with
        return list(self.hits[:limit])

    async def download(self, hit_id: str, dest_path: Any) -> None:  # pragma: no cover
        raise NotImplementedError

    async def has_session(self) -> bool:
        return True

    async def clear_session(self) -> None:
        return None


@pytest.fixture
def stub_pools(monkeypatch):
    """Replace the registry with three stub scrapers. Yields the dict so tests
    can mutate ``hits`` / ``raise_with`` per-stub."""
    stubs = {
        "djcity": _StubScraper(slug="djcity", display_name="DJcity", hits=[]),
        "zipdj": _StubScraper(slug="zipdj", display_name="zipDJ", hits=[]),
        "bpmsupreme": _StubScraper(slug="bpmsupreme", display_name="BPM Supreme", hits=[]),
    }
    monkeypatch.setattr(pool_base, "_REGISTRY", stubs)
    yield stubs


@pytest.fixture(autouse=True)
def _reset_priority_setting(setup_test_db):
    """Drop any leftover priority row so tests start from DEFAULT_PRIORITY."""
    db = SessionLocal()
    try:
        db.query(AppSetting).filter(AppSetting.key == "upscale_pool_priority").delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()
    yield


def _hit(hit_id: str) -> PoolHit:
    return PoolHit(
        hit_id=hit_id,
        title=f"Title {hit_id}",
        artist=f"Artist {hit_id}",
        bitrate_kbps=320,
        format="mp3",
        duration_s=200.0,
    )


def test_djcity_first_when_hits_returned(stub_pools, setup_test_db):
    stub_pools["djcity"].hits = [_hit("dj-1"), _hit("dj-2")]
    stub_pools["zipdj"].hits = [_hit("zd-1")]
    stub_pools["bpmsupreme"].hits = [_hit("bp-1")]

    db = SessionLocal()
    try:
        result: OrchestratorResult = asyncio.run(pool_orchestrator.search(db, "any query"))
    finally:
        db.close()

    assert result.served_by == "djcity"
    assert [h.hit_id for h in result.hits] == ["dj-1", "dj-2"]
    # zipdj + bpmsupreme were never queried — chain short-circuited.
    assert stub_pools["zipdj"].call_count == 0
    assert stub_pools["bpmsupreme"].call_count == 0
    assert [t.slug for t in result.tried] == ["djcity"]
    assert result.tried[0].hits_count == 2


def test_falls_through_to_zipdj_when_djcity_empty(stub_pools, setup_test_db):
    stub_pools["djcity"].hits = []
    stub_pools["zipdj"].hits = [_hit("zd-1")]
    stub_pools["bpmsupreme"].hits = [_hit("bp-1")]

    db = SessionLocal()
    try:
        result = asyncio.run(pool_orchestrator.search(db, "any query"))
    finally:
        db.close()

    assert result.served_by == "zipdj"
    assert [t.slug for t in result.tried] == ["djcity", "zipdj"]
    assert result.tried[0].hits_count == 0
    assert result.tried[1].hits_count == 1
    # BPM Supreme not queried.
    assert stub_pools["bpmsupreme"].call_count == 0


def test_falls_through_to_bpmsupreme_when_first_two_empty(stub_pools, setup_test_db):
    stub_pools["djcity"].hits = []
    stub_pools["zipdj"].hits = []
    stub_pools["bpmsupreme"].hits = [_hit("bp-1")]

    db = SessionLocal()
    try:
        result = asyncio.run(pool_orchestrator.search(db, "any query"))
    finally:
        db.close()

    assert result.served_by == "bpmsupreme"
    assert [t.slug for t in result.tried] == ["djcity", "zipdj", "bpmsupreme"]


def test_skips_pool_that_raises_pool_auth_error(stub_pools, setup_test_db):
    """A scraper raising PoolAuthError shouldn't kill the chain — orchestrator
    records the error in ``tried`` and falls through."""
    stub_pools["djcity"].raise_with = PoolAuthError("session expired")
    stub_pools["zipdj"].hits = [_hit("zd-1")]

    db = SessionLocal()
    try:
        result = asyncio.run(pool_orchestrator.search(db, "any query"))
    finally:
        db.close()

    assert result.served_by == "zipdj"
    djcity_entry = next(t for t in result.tried if t.slug == "djcity")
    assert djcity_entry.hits_count == 0
    assert "session expired" in djcity_entry.error


def test_skips_pool_that_raises_pool_unavailable(stub_pools, setup_test_db):
    stub_pools["djcity"].raise_with = PoolUnavailableError("DOM moved")
    stub_pools["zipdj"].hits = [_hit("zd-1")]

    db = SessionLocal()
    try:
        result = asyncio.run(pool_orchestrator.search(db, "any query"))
    finally:
        db.close()

    assert result.served_by == "zipdj"
    djcity_entry = next(t for t in result.tried if t.slug == "djcity")
    assert "DOM moved" in djcity_entry.error


def test_stops_chain_on_pool_disabled(stub_pools, setup_test_db):
    """If pools are disabled, every pool will raise the same way — short-circuit
    so we don't pointlessly attempt all three."""
    stub_pools["djcity"].raise_with = PoolDisabledError("UPSCALE_POOLS_ENABLED=0")

    db = SessionLocal()
    try:
        result = asyncio.run(pool_orchestrator.search(db, "any query"))
    finally:
        db.close()

    assert result.served_by == ""
    assert result.hits == []
    # Only djcity attempted, then the chain stops.
    assert [t.slug for t in result.tried] == ["djcity"]
    assert stub_pools["zipdj"].call_count == 0
    assert stub_pools["bpmsupreme"].call_count == 0


def test_all_pools_empty_returns_empty_result(stub_pools, setup_test_db):
    db = SessionLocal()
    try:
        result = asyncio.run(pool_orchestrator.search(db, "any query"))
    finally:
        db.close()

    assert result.served_by == ""
    assert result.hits == []
    assert [t.slug for t in result.tried] == ["djcity", "zipdj", "bpmsupreme"]
    assert all(t.hits_count == 0 for t in result.tried)
    assert all(t.error == "" for t in result.tried)


def test_blank_query_short_circuits(stub_pools, setup_test_db):
    stub_pools["djcity"].hits = [_hit("dj-1")]
    db = SessionLocal()
    try:
        result = asyncio.run(pool_orchestrator.search(db, "   "))
    finally:
        db.close()

    assert result.served_by == ""
    assert result.tried == []
    assert stub_pools["djcity"].call_count == 0


def test_custom_priority_from_app_setting(stub_pools, setup_test_db):
    """Founder can re-rank via the upscale_pool_priority AppSetting."""
    stub_pools["djcity"].hits = [_hit("dj-1")]
    stub_pools["zipdj"].hits = [_hit("zd-1")]

    db = SessionLocal()
    try:
        db.add(AppSetting(key="upscale_pool_priority", value="zipdj,djcity,bpmsupreme"))
        db.commit()
        result = asyncio.run(pool_orchestrator.search(db, "q"))
    finally:
        db.query(AppSetting).filter(AppSetting.key == "upscale_pool_priority").delete()
        db.commit()
        db.close()

    assert result.served_by == "zipdj"
    assert [t.slug for t in result.tried] == ["zipdj"]


def test_unknown_pool_slug_in_priority_is_skipped(stub_pools, setup_test_db):
    stub_pools["djcity"].hits = [_hit("dj-1")]
    db = SessionLocal()
    try:
        db.add(AppSetting(key="upscale_pool_priority", value="totally-fake,djcity"))
        db.commit()
        result = asyncio.run(pool_orchestrator.search(db, "q"))
    finally:
        db.query(AppSetting).filter(AppSetting.key == "upscale_pool_priority").delete()
        db.commit()
        db.close()

    assert result.served_by == "djcity"
    # Both slugs show up in tried — the unknown one with an error string.
    slugs = [t.slug for t in result.tried]
    assert slugs == ["totally-fake", "djcity"]
    unknown_entry = result.tried[0]
    assert "unknown pool" in unknown_entry.error.lower()
