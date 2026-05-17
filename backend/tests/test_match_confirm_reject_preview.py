"""Tests for the step-5 match confirm/reject + A/B preview endpoints.

End-to-end exercises ``POST /upscale/match/{id}/confirm|reject``,
``GET /upscale/match/{id}``, and ``GET /upscale/match/{id}/preview-original``.
The pool-proxy ``/preview`` endpoint is covered with a stubbed ``httpx``
transport so we don't hit the real internet.
"""

from __future__ import annotations

import pytest

from models import LibraryFile, UpscaleMatch


@pytest.fixture(autouse=True)
def _reset_upscale_tables(setup_test_db, db_session):
    db_session.query(UpscaleMatch).delete(synchronize_session=False)
    db_session.query(LibraryFile).delete(synchronize_session=False)
    db_session.commit()
    yield


def _seed_library_file(db_session, *, abs_path="/tmp/song.mp3") -> int:
    lf = LibraryFile(
        abs_path=abs_path,
        sha256="0" * 64,
        size_bytes=1000,
        bitrate_kbps=128,
        duration_s=200.0,
        mtime_ns=0,
        tag_title="t",
        tag_artist="a",
        tag_album="",
    )
    db_session.add(lf)
    db_session.commit()
    return int(lf.id)


def _seed_match(
    db_session,
    *,
    library_file_id: int,
    pool_slug: str = "djcity",
    pool_hit_id: str = "hit-1",
    preview_url: str = "https://example.com/preview.mp3",
    status: str = "candidate",
) -> int:
    m = UpscaleMatch(
        library_file_id=library_file_id,
        pool_slug=pool_slug,
        pool_hit_id=pool_hit_id,
        pool_title="Pool Title",
        pool_artist="Pool Artist",
        pool_bitrate_kbps=320,
        pool_format="mp3",
        pool_preview_url=preview_url,
        status=status,
    )
    db_session.add(m)
    db_session.commit()
    return int(m.id)


# --- get_match ---------------------------------------------------------------


def test_get_match_returns_match(client, db_session):
    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id)
    r = client.get(f"/api/upscale/match/{m_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == m_id
    assert body["status"] == "candidate"
    assert body["pool_preview_url"] == "https://example.com/preview.mp3"


def test_get_match_404_for_unknown(client):
    r = client.get("/api/upscale/match/99999")
    assert r.status_code == 404


# --- confirm -----------------------------------------------------------------


def test_confirm_flips_candidate_to_confirmed(client, db_session):
    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id)
    r = client.post(f"/api/upscale/match/{m_id}/confirm")
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"


def test_confirm_demotes_prior_confirmed_on_same_library_file(client, db_session):
    """Only one match per library_file may be confirmed at a time."""
    lf_id = _seed_library_file(db_session)
    a_id = _seed_match(db_session, library_file_id=lf_id, pool_hit_id="a", status="confirmed")
    b_id = _seed_match(db_session, library_file_id=lf_id, pool_hit_id="b", pool_slug="zipdj")

    r = client.post(f"/api/upscale/match/{b_id}/confirm")
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    # Reload — `a` should now be rejected.
    r_a = client.get(f"/api/upscale/match/{a_id}")
    assert r_a.json()["status"] == "rejected"


def test_confirm_does_not_touch_other_library_files(client, db_session):
    """Demotion is scoped to the same library_file, not all confirmed rows."""
    lf1 = _seed_library_file(db_session, abs_path="/tmp/a.mp3")
    lf2 = _seed_library_file(db_session, abs_path="/tmp/b.mp3")
    other_id = _seed_match(db_session, library_file_id=lf1, pool_hit_id="x", status="confirmed")
    new_id = _seed_match(db_session, library_file_id=lf2, pool_hit_id="y")

    client.post(f"/api/upscale/match/{new_id}/confirm")

    r = client.get(f"/api/upscale/match/{other_id}")
    assert r.json()["status"] == "confirmed"


def test_confirm_rejects_terminal_status(client, db_session):
    """Once a match has been swapped, /confirm refuses to flip it back."""
    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id, status="replaced")
    r = client.post(f"/api/upscale/match/{m_id}/confirm")
    assert r.status_code == 409
    assert "terminal" in r.json()["detail"]


# --- reject ------------------------------------------------------------------


def test_reject_flips_to_rejected(client, db_session):
    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id, status="confirmed")
    r = client.post(f"/api/upscale/match/{m_id}/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_reject_rejects_terminal_status(client, db_session):
    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id, status="replaced")
    r = client.post(f"/api/upscale/match/{m_id}/reject")
    assert r.status_code == 409


# --- preview-original (local file) -------------------------------------------


def test_preview_original_streams_local_file(client, db_session, tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"ID3FAKE-DATA")
    lf_id = _seed_library_file(db_session, abs_path=str(audio))
    m_id = _seed_match(db_session, library_file_id=lf_id)

    r = client.get(f"/api/upscale/match/{m_id}/preview-original")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.content == b"ID3FAKE-DATA"


def test_preview_original_410_when_file_purged(client, db_session, tmp_path):
    """File-system rug-pull: row exists, file deleted → 410 Gone."""
    audio = tmp_path / "ghost.mp3"
    audio.write_bytes(b"x")
    lf_id = _seed_library_file(db_session, abs_path=str(audio))
    m_id = _seed_match(db_session, library_file_id=lf_id)
    audio.unlink()

    r = client.get(f"/api/upscale/match/{m_id}/preview-original")
    assert r.status_code == 410


# --- preview (pool proxy) ----------------------------------------------------


def test_preview_404_when_no_preview_url(client, db_session):
    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id, preview_url="")
    r = client.get(f"/api/upscale/match/{m_id}/preview")
    assert r.status_code == 404
    assert "preview_url" in r.json()["detail"]


def test_preview_streams_from_pool_via_httpx_stub(client, db_session, monkeypatch):
    """Stub httpx.AsyncClient so we exercise the proxy path without the network."""
    import httpx

    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id, preview_url="https://example.com/p.mp3")

    audio_bytes = b"\xff\xfb" * 1024
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=audio_bytes, headers={"content-type": "audio/mpeg"})
    )

    real_async_client = httpx.AsyncClient

    def _patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _patched_async_client)

    r = client.get(f"/api/upscale/match/{m_id}/preview")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.content == audio_bytes


def test_preview_502_when_pool_returns_error(client, db_session, monkeypatch):
    import httpx

    lf_id = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf_id, preview_url="https://example.com/p.mp3")

    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    real_async_client = httpx.AsyncClient

    def _patched_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _patched_async_client)

    r = client.get(f"/api/upscale/match/{m_id}/preview")
    assert r.status_code == 502
