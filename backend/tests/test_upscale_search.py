"""Route-level tests for ``POST /api/upscale/search``.

Stubs the three scrapers in the registry so we exercise the route + the
orchestrator + the persistence layer without launching Playwright.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from database import SessionLocal
from models import AppSetting, LibraryFile, UpscaleMatch
from services import pool_base
from services.pool_base import PoolHit


@dataclass
class _StubScraper:
    slug: str
    display_name: str
    hits: list[PoolHit]
    raise_with: BaseException | None = None

    async def login_interactive(self) -> None:
        return None

    async def search(self, query: str, *, limit: int = 25) -> list[PoolHit]:
        if self.raise_with is not None:
            raise self.raise_with
        return list(self.hits[:limit])

    async def download(self, hit_id: str, dest_path):  # pragma: no cover
        raise NotImplementedError

    async def has_session(self) -> bool:
        return True

    async def clear_session(self) -> None:
        return None


@pytest.fixture
def stub_pools(monkeypatch):
    stubs = {
        "djcity": _StubScraper(slug="djcity", display_name="DJcity", hits=[]),
        "zipdj": _StubScraper(slug="zipdj", display_name="zipDJ", hits=[]),
        "bpmsupreme": _StubScraper(slug="bpmsupreme", display_name="BPM Supreme", hits=[]),
    }
    monkeypatch.setattr(pool_base, "_REGISTRY", stubs)
    yield stubs


@pytest.fixture(autouse=True)
def _reset_upscale_tables(setup_test_db):
    db = SessionLocal()
    try:
        db.query(UpscaleMatch).delete(synchronize_session=False)
        db.query(LibraryFile).delete(synchronize_session=False)
        db.query(AppSetting).filter(AppSetting.key == "upscale_pool_priority").delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()
    yield


def _seed_library_file(db_session, *, artist="Daft Punk", title="Around The World") -> int:
    lf = LibraryFile(
        abs_path="/tmp/song.mp3",
        sha256="0" * 64,
        size_bytes=1000,
        bitrate_kbps=128,
        duration_s=200.0,
        mtime_ns=0,
        tag_title=title,
        tag_artist=artist,
        tag_album="",
    )
    db_session.add(lf)
    db_session.commit()
    return int(lf.id)


def _hit(hit_id: str, *, bitrate=320) -> PoolHit:
    return PoolHit(
        hit_id=hit_id,
        title=f"Title {hit_id}",
        artist=f"Artist {hit_id}",
        bitrate_kbps=bitrate,
        format="mp3",
        duration_s=200.0,
        preview_url=f"https://example.com/preview/{hit_id}.mp3",
    )


def test_search_returns_tried_served_by_and_persists_matches(client, db_session, stub_pools):
    stub_pools["djcity"].hits = [_hit("dj-1"), _hit("dj-2")]

    lf_id = _seed_library_file(db_session)

    r = client.post("/api/upscale/search", json={"library_file_id": lf_id})
    assert r.status_code == 200
    body = r.json()

    assert body["served_by"] == "djcity"
    assert [t["slug"] for t in body["tried"]] == ["djcity"]
    assert body["tried"][0]["hits_count"] == 2
    assert len(body["hits"]) == 2

    # Each hit has the upscale_match_id the FE will pass to /match/{id}/confirm.
    match_ids = [h["upscale_match_id"] for h in body["hits"]]
    assert all(isinstance(mid, int) and mid > 0 for mid in match_ids)
    assert len(set(match_ids)) == 2  # distinct

    # Rows persisted with status='candidate'.
    db_session.expire_all()
    rows = db_session.query(UpscaleMatch).filter(UpscaleMatch.library_file_id == lf_id).all()
    assert len(rows) == 2
    for row in rows:
        assert row.pool_slug == "djcity"
        assert row.status == "candidate"


def test_search_falls_through_and_reports_chain(client, db_session, stub_pools):
    stub_pools["djcity"].hits = []
    stub_pools["zipdj"].hits = [_hit("zd-1")]

    lf_id = _seed_library_file(db_session)

    r = client.post("/api/upscale/search", json={"library_file_id": lf_id})
    assert r.status_code == 200
    body = r.json()

    assert body["served_by"] == "zipdj"
    assert [t["slug"] for t in body["tried"]] == ["djcity", "zipdj"]
    assert body["hits"][0]["pool_slug"] == "zipdj"


def test_search_rerun_does_not_duplicate_rows(client, db_session, stub_pools):
    """Same hit_id on a re-search updates the existing row rather than inserting."""
    stub_pools["djcity"].hits = [_hit("dj-1", bitrate=320)]

    lf_id = _seed_library_file(db_session)

    r1 = client.post("/api/upscale/search", json={"library_file_id": lf_id})
    assert r1.status_code == 200
    first_match_id = r1.json()["hits"][0]["upscale_match_id"]

    # Re-search with the same hit but a bitrate change (simulating pool updating
    # metadata between calls).
    stub_pools["djcity"].hits = [_hit("dj-1", bitrate=256)]
    r2 = client.post("/api/upscale/search", json={"library_file_id": lf_id})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["hits"][0]["upscale_match_id"] == first_match_id
    assert body2["hits"][0]["bitrate_kbps"] == 256

    db_session.expire_all()
    rows = db_session.query(UpscaleMatch).filter(UpscaleMatch.library_file_id == lf_id).all()
    assert len(rows) == 1
    assert rows[0].pool_bitrate_kbps == 256


def test_search_returns_empty_when_all_pools_empty(client, db_session, stub_pools):
    lf_id = _seed_library_file(db_session)

    r = client.post("/api/upscale/search", json={"library_file_id": lf_id})
    assert r.status_code == 200
    body = r.json()
    assert body["served_by"] == ""
    assert body["hits"] == []
    assert [t["slug"] for t in body["tried"]] == ["djcity", "zipdj", "bpmsupreme"]


def test_search_unknown_library_file_returns_404(client, db_session):
    r = client.post("/api/upscale/search", json={"library_file_id": 99999})
    assert r.status_code == 404


def test_search_empty_tags_and_filename_stem_falls_back_to_stem(client, db_session, stub_pools):
    """If tags are empty, the query falls back to the filename stem so we still
    have something to hand the pool."""
    stub_pools["djcity"].hits = [_hit("dj-1")]
    lf = LibraryFile(
        abs_path="/library/Some Artist - Cool Song.mp3",
        sha256="0" * 64,
        size_bytes=1000,
        bitrate_kbps=128,
        duration_s=200.0,
        mtime_ns=0,
        tag_title="",
        tag_artist="",
        tag_album="",
    )
    db_session.add(lf)
    db_session.commit()

    r = client.post("/api/upscale/search", json={"library_file_id": int(lf.id)})
    assert r.status_code == 200
    assert r.json()["served_by"] == "djcity"


def test_query_override_takes_precedence(client, db_session, stub_pools):
    """The FE can pass a manual query_override and it overrides the tag-derived one."""
    # Stub records the query passed in via a sentinel hits[] keyed off it.
    captured_queries: list[str] = []

    async def fake_search(query, *, limit=25):
        captured_queries.append(query)
        return [_hit("dj-1")]

    stub_pools["djcity"].search = fake_search  # type: ignore[method-assign]

    lf_id = _seed_library_file(db_session)

    r = client.post(
        "/api/upscale/search",
        json={"library_file_id": lf_id, "query_override": "custom search string"},
    )
    assert r.status_code == 200
    assert captured_queries == ["custom search string"]
