"""Tests for the Upscale swap engine + ``/upscale/match/{id}/replace`` + Replace Log.

Stubs the pool download with a local source file so the engine exercises the
real archive + atomic-rename + ID3 + log-row paths against the filesystem.
The route layer is tested end-to-end against the FastAPI app with httpx.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from database import SessionLocal
from models import LibraryFile, ReplaceLog, UpscaleMatch
from services import swap_engine

# Reasonable MP3 frame header so mutagen doesn't reject our fake files outright.
# The bytes don't decode to real audio — that's fine for our tests; mutagen
# tolerates incomplete frames for tag-read attempts.
_MP3_BYTES_A = b"\xff\xfb\x90\x00" + b"\x00" * 4096
_MP3_BYTES_B = b"\xff\xfb\xb0\x00" + b"\x01" * 16384  # bigger ≈ "higher bitrate"


@pytest.fixture(autouse=True)
def _reset_upscale_tables(setup_test_db):
    """Short-lived SessionLocal — using conftest's db_session here deadlocks
    against tests that open their own SessionLocal (it holds an open
    transaction for the whole test)."""
    db = SessionLocal()
    try:
        db.query(ReplaceLog).delete(synchronize_session=False)
        db.query(UpscaleMatch).delete(synchronize_session=False)
        db.query(LibraryFile).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def _seed_pair(db_session, tmp_path: Path, *, status: str = "confirmed"):
    """Create an on-disk library file + a matching DB row + a confirmed match."""
    audio = tmp_path / "song.mp3"
    audio.write_bytes(_MP3_BYTES_A)
    lf = LibraryFile(
        abs_path=str(audio),
        sha256="0" * 64,
        size_bytes=len(_MP3_BYTES_A),
        bitrate_kbps=128,
        duration_s=200.0,
        mtime_ns=audio.stat().st_mtime_ns,
        tag_title="Original Title",
        tag_artist="Original Artist",
        tag_album="Original Album",
    )
    db_session.add(lf)
    db_session.commit()
    m = UpscaleMatch(
        library_file_id=lf.id,
        pool_slug="djcity",
        pool_hit_id="hit-1",
        pool_title="Pool Title",
        pool_artist="Pool Artist",
        pool_bitrate_kbps=320,
        pool_format="mp3",
        pool_preview_url="https://example.com/p.mp3",
        status=status,
    )
    db_session.add(m)
    db_session.commit()
    return audio, lf, m


# --- swap_engine.replace direct tests ---------------------------------------


def test_replace_success_path(setup_test_db, tmp_path):
    """Happy path: file is swapped at the same path; archive exists; row written."""
    db = SessionLocal()
    try:
        audio, lf, m = _seed_pair(db, tmp_path)
        original_path = str(audio)

        def download(dest):
            Path(dest).write_bytes(_MP3_BYTES_B)
            return len(_MP3_BYTES_B)

        result = asyncio.run(swap_engine.replace(db, m, download_to_temp=download))

        # Path on disk is unchanged — this is the Rekordbox-safety invariant.
        assert Path(result.abs_path) == audio
        assert audio.exists()
        # File content was actually swapped.
        assert audio.read_bytes() == _MP3_BYTES_B
        # Archive lives under _replaced/ alongside the original directory.
        archive = Path(result.archive_path)
        assert archive.exists()
        assert archive.read_bytes() == _MP3_BYTES_A
        assert archive.parent.name == "_replaced"
        assert archive.parent.parent == audio.parent

        # Match row flipped to replaced.
        db.expire_all()
        m_after = db.query(UpscaleMatch).filter(UpscaleMatch.id == m.id).first()
        assert m_after.status == "replaced"

        # Replace log row persisted with the expected fields.
        log = db.query(ReplaceLog).filter(ReplaceLog.id == result.replace_log_id).first()
        assert log is not None
        assert log.abs_path == original_path
        assert log.file_size_before == len(_MP3_BYTES_A)
        assert log.file_size_after == len(_MP3_BYTES_B)
        assert log.pool_slug == "djcity"

        # LibraryFile metadata updated to reflect what's on disk now.
        lf_after = db.query(LibraryFile).filter(LibraryFile.id == lf.id).first()
        assert lf_after.size_bytes == len(_MP3_BYTES_B)
    finally:
        db.close()


def test_replace_refuses_unconfirmed_match(setup_test_db, tmp_path):
    db = SessionLocal()
    try:
        _, _, m = _seed_pair(db, tmp_path, status="candidate")

        def download(dest):
            Path(dest).write_bytes(_MP3_BYTES_B)
            return len(_MP3_BYTES_B)

        with pytest.raises(swap_engine.MatchNotConfirmedError):
            asyncio.run(swap_engine.replace(db, m, download_to_temp=download))
    finally:
        db.close()


def test_replace_download_failure_leaves_original_intact(setup_test_db, tmp_path):
    """Download raises → temp cleaned, no archive, no row written, original intact."""
    db = SessionLocal()
    try:
        audio, lf, m = _seed_pair(db, tmp_path)
        original_bytes = audio.read_bytes()

        def boom(dest):
            raise RuntimeError("network gone")

        with pytest.raises(swap_engine.DownloadFailedError):
            asyncio.run(swap_engine.replace(db, m, download_to_temp=boom))

        assert audio.exists()
        assert audio.read_bytes() == original_bytes
        # No temp leftover in target's directory.
        leftovers = [p for p in audio.parent.iterdir() if p.name.startswith(".song.mp3.swap-")]
        assert leftovers == []
        # No archive directory created on a failed download.
        assert not (audio.parent / "_replaced").exists() or not list(
            (audio.parent / "_replaced").iterdir()
        )
        # No log row, status unchanged.
        db.expire_all()
        m_after = db.query(UpscaleMatch).filter(UpscaleMatch.id == m.id).first()
        assert m_after.status == "confirmed"
        assert db.query(ReplaceLog).count() == 0
    finally:
        db.close()


def test_replace_empty_download_is_treated_as_failure(setup_test_db, tmp_path):
    """A 'download' that yields an empty file must not swap."""
    db = SessionLocal()
    try:
        audio, _, m = _seed_pair(db, tmp_path)
        original_bytes = audio.read_bytes()

        def empty(dest):
            Path(dest).write_bytes(b"")
            return 0

        with pytest.raises(swap_engine.DownloadFailedError):
            asyncio.run(swap_engine.replace(db, m, download_to_temp=empty))

        assert audio.read_bytes() == original_bytes
        db.expire_all()
        assert db.query(ReplaceLog).count() == 0
    finally:
        db.close()


def test_replace_file_locked_rolls_back(setup_test_db, tmp_path, monkeypatch):
    """``os.replace`` raising PermissionError must roll the archive back to the
    target path and surface :class:`FileLockedError` with the original intact."""
    db = SessionLocal()
    try:
        audio, _, m = _seed_pair(db, tmp_path)
        original_bytes = audio.read_bytes()

        real_replace = os.replace

        def flaky_replace(src, dst):
            # First call (the swap) fails; subsequent calls (none expected) succeed.
            if str(dst) == str(audio):
                raise PermissionError("file held by Rekordbox")
            return real_replace(src, dst)

        monkeypatch.setattr("services.swap_engine.os.replace", flaky_replace)

        def download(dest):
            Path(dest).write_bytes(_MP3_BYTES_B)
            return len(_MP3_BYTES_B)

        with pytest.raises(swap_engine.FileLockedError):
            asyncio.run(swap_engine.replace(db, m, download_to_temp=download))

        # Original is back at the original path with original bytes.
        assert audio.exists()
        assert audio.read_bytes() == original_bytes
        db.expire_all()
        m_after = db.query(UpscaleMatch).filter(UpscaleMatch.id == m.id).first()
        assert m_after.status == "confirmed"
        assert db.query(ReplaceLog).count() == 0
    finally:
        db.close()


def test_replace_missing_target_file_is_explicit_error(setup_test_db, tmp_path):
    """Library row says the file exists but it has been deleted from disk."""
    db = SessionLocal()
    try:
        audio, lf, m = _seed_pair(db, tmp_path)
        audio.unlink()

        def download(dest):
            Path(dest).write_bytes(_MP3_BYTES_B)
            return len(_MP3_BYTES_B)

        with pytest.raises(swap_engine.SwapFailedError):
            asyncio.run(swap_engine.replace(db, m, download_to_temp=download))
    finally:
        db.close()


# --- Route-level tests -------------------------------------------------------


def test_route_rejects_unconfirmed_match(client, db_session, tmp_path):
    audio, lf, m = _seed_pair(db_session, tmp_path, status="candidate")
    r = client.post(f"/api/upscale/match/{m.id}/replace")
    assert r.status_code == 409


def test_route_rejects_already_replaced(client, db_session, tmp_path):
    audio, lf, m = _seed_pair(db_session, tmp_path, status="replaced")
    r = client.post(f"/api/upscale/match/{m.id}/replace")
    assert r.status_code == 409
    assert "already replaced" in r.json()["detail"]


def test_route_rejects_match_with_no_preview_url(client, db_session, tmp_path):
    audio, lf, m = _seed_pair(db_session, tmp_path)
    m.pool_preview_url = ""
    db_session.commit()
    r = client.post(f"/api/upscale/match/{m.id}/replace")
    assert r.status_code == 409


def test_route_replace_end_to_end_with_httpx_stub(client, db_session, tmp_path, monkeypatch):
    """End-to-end: route → swap_engine → DB. Pool fetch is stubbed via httpx
    MockTransport so we don't touch the network."""
    import httpx

    audio, lf, m = _seed_pair(db_session, tmp_path)
    original_path = str(audio)

    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=_MP3_BYTES_B))
    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", patched_client)

    r = client.post(f"/api/upscale/match/{m.id}/replace")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "replaced"
    assert body["abs_path"] == original_path
    assert body["file_size_before"] == len(_MP3_BYTES_A)
    assert body["file_size_after"] == len(_MP3_BYTES_B)
    assert body["archive_path"].endswith(".mp3")

    # File on disk really got swapped, path preserved.
    assert Path(original_path).exists()
    assert Path(original_path).read_bytes() == _MP3_BYTES_B


def test_route_502_on_pool_http_error(client, db_session, tmp_path, monkeypatch):
    import httpx

    audio, lf, m = _seed_pair(db_session, tmp_path)
    original_bytes = audio.read_bytes()

    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", patched_client)

    r = client.post(f"/api/upscale/match/{m.id}/replace")
    assert r.status_code == 502
    # Original survives.
    assert audio.read_bytes() == original_bytes


# --- Replace Log routes ------------------------------------------------------


def test_replace_log_list_paginates_newest_first(client, db_session, tmp_path):
    audio, lf, m = _seed_pair(db_session, tmp_path)
    # Seed 3 log rows directly.
    for i in range(3):
        db_session.add(
            ReplaceLog(
                library_file_id=lf.id,
                upscale_match_id=m.id,
                abs_path=f"/a/{i}.mp3",
                archive_path=f"/a/_replaced/{i}.mp3",
                old_bitrate_kbps=128,
                new_bitrate_kbps=320,
                old_sha256="0" * 64,
                new_sha256="1" * 64,
                pool_slug="djcity",
                pool_source_url="https://example.com",
                file_size_before=1000 + i,
                file_size_after=2000 + i,
            )
        )
    db_session.commit()

    r = client.get("/api/upscale/replace-log")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    # Newest first = highest id first since they were inserted in order
    # and have ties on replaced_at (within the same second).
    assert body["items"][0]["id"] > body["items"][-1]["id"]


def test_replace_log_filters_by_library_file_id(client, db_session, tmp_path):
    (tmp_path / "a").mkdir()
    a_audio, a_lf, a_m = _seed_pair(db_session, tmp_path / "a")
    # Re-seed under a different tmp dir for the second file.
    (tmp_path / "b").mkdir()
    b_audio = tmp_path / "b" / "other.mp3"
    b_audio.write_bytes(_MP3_BYTES_A)
    b_lf = LibraryFile(
        abs_path=str(b_audio),
        sha256="0" * 64,
        size_bytes=len(_MP3_BYTES_A),
        bitrate_kbps=128,
        duration_s=200.0,
        mtime_ns=b_audio.stat().st_mtime_ns,
        tag_title="",
        tag_artist="",
        tag_album="",
    )
    db_session.add(b_lf)
    db_session.commit()

    db_session.add_all(
        [
            ReplaceLog(
                library_file_id=a_lf.id,
                upscale_match_id=a_m.id,
                abs_path="/a/song.mp3",
                archive_path="/a/_replaced/song.mp3",
                old_bitrate_kbps=128,
                new_bitrate_kbps=320,
                old_sha256="0" * 64,
                new_sha256="1" * 64,
                pool_slug="djcity",
            ),
            ReplaceLog(
                library_file_id=b_lf.id,
                upscale_match_id=None,
                abs_path="/b/other.mp3",
                archive_path="/b/_replaced/other.mp3",
                old_bitrate_kbps=128,
                new_bitrate_kbps=320,
                old_sha256="0" * 64,
                new_sha256="1" * 64,
                pool_slug="zipdj",
            ),
        ]
    )
    db_session.commit()

    r = client.get(f"/api/upscale/replace-log?library_file_id={a_lf.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["library_file_id"] == a_lf.id
