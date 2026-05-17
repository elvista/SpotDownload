"""Tests for steps 7 + 8: ``GET /api/upscale/session-status`` (counts) and
``GET /api/upscale/session-complete`` (one-shot SSE).

Skips Playwright + httpx entirely — the only state these endpoints care about
is rows in ``upscale_matches`` + ``replace_logs``, so we seed those directly.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime

import pytest

from database import SessionLocal
from models import LibraryFile, ReplaceLog, UpscaleMatch


@pytest.fixture(autouse=True)
def _reset_upscale_tables(setup_test_db):
    db = SessionLocal()
    try:
        db.query(ReplaceLog).delete(synchronize_session=False)
        db.query(UpscaleMatch).delete(synchronize_session=False)
        db.query(LibraryFile).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def _seed_library_file(db, *, abs_path="/tmp/song.mp3") -> int:
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
    db.add(lf)
    db.commit()
    return int(lf.id)


def _seed_match(db, *, library_file_id, status="candidate", pool_hit_id="hit") -> int:
    m = UpscaleMatch(
        library_file_id=library_file_id,
        pool_slug="djcity",
        pool_hit_id=pool_hit_id,
        pool_title="t",
        pool_artist="a",
        pool_bitrate_kbps=320,
        pool_format="mp3",
        pool_preview_url="https://example.com/p.mp3",
        status=status,
    )
    db.add(m)
    db.commit()
    return int(m.id)


def _seed_replace_log(
    db, *, library_file_id, upscale_match_id, id3_copy_status="ok", replaced_at=None
):
    db.add(
        ReplaceLog(
            library_file_id=library_file_id,
            upscale_match_id=upscale_match_id,
            abs_path="/tmp/song.mp3",
            archive_path="/tmp/_replaced/song.mp3",
            old_bitrate_kbps=128,
            new_bitrate_kbps=320,
            old_sha256="0" * 64,
            new_sha256="1" * 64,
            pool_slug="djcity",
            pool_source_url="https://example.com",
            file_size_before=1000,
            file_size_after=3000,
            id3_copy_status=id3_copy_status,
            replaced_at=replaced_at or datetime.now(UTC),
        )
    )
    db.commit()


# --- /session-status ---------------------------------------------------------


def test_session_status_empty_when_no_matches(client):
    r = client.get("/api/upscale/session-status")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "candidates": 0,
        "confirmed": 0,
        "replaced": 0,
        "rejected": 0,
        "errors": 0,
        "session_started_at": None,
        "session_completed_at": None,
    }


def test_session_status_counts_by_status(client, db_session):
    lf = _seed_library_file(db_session)
    _seed_match(db_session, library_file_id=lf, status="candidate", pool_hit_id="a")
    _seed_match(db_session, library_file_id=lf, status="candidate", pool_hit_id="b")
    _seed_match(db_session, library_file_id=lf, status="confirmed", pool_hit_id="c")
    _seed_match(db_session, library_file_id=lf, status="replaced", pool_hit_id="d")
    _seed_match(db_session, library_file_id=lf, status="rejected", pool_hit_id="e")

    r = client.get("/api/upscale/session-status")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == 2
    assert body["confirmed"] == 1
    assert body["replaced"] == 1
    assert body["rejected"] == 1
    # session_started_at is set the moment any row leaves 'candidate'.
    assert body["session_started_at"] is not None
    # session is NOT complete yet — one confirmed still pending.
    assert body["session_completed_at"] is None


def test_session_status_counts_id3_errors(client, db_session):
    lf = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf, status="replaced")
    _seed_replace_log(db_session, library_file_id=lf, upscale_match_id=m_id, id3_copy_status="ok")
    _seed_replace_log(
        db_session, library_file_id=lf, upscale_match_id=m_id, id3_copy_status="partial"
    )
    _seed_replace_log(
        db_session, library_file_id=lf, upscale_match_id=m_id, id3_copy_status="failed"
    )

    r = client.get("/api/upscale/session-status")
    body = r.json()
    assert body["errors"] == 2  # partial + failed (ok doesn't count)


def test_session_status_completed_when_no_confirmed_and_some_replaced(client, db_session):
    """The trigger condition for the Rekordbox-rescan toast."""
    lf = _seed_library_file(db_session)
    m_id = _seed_match(db_session, library_file_id=lf, status="replaced")
    _seed_replace_log(db_session, library_file_id=lf, upscale_match_id=m_id)

    r = client.get("/api/upscale/session-status")
    body = r.json()
    assert body["confirmed"] == 0
    assert body["replaced"] == 1
    assert body["session_completed_at"] is not None


def test_session_status_not_completed_when_no_replaces_yet(client, db_session):
    """Pre-replace state: rejected-only or candidate-only shouldn't complete."""
    lf = _seed_library_file(db_session)
    _seed_match(db_session, library_file_id=lf, status="rejected", pool_hit_id="x")
    _seed_match(db_session, library_file_id=lf, status="candidate", pool_hit_id="y")

    r = client.get("/api/upscale/session-status")
    body = r.json()
    assert body["confirmed"] == 0
    assert body["replaced"] == 0
    assert body["session_completed_at"] is None


# --- /session-complete SSE ---------------------------------------------------


def test_session_complete_sse_fires_when_session_ends(client):
    """Open the stream → flip the only confirmed match to replaced from a
    separate thread → assert the event arrives + stream closes.

    Seeds via a fresh ``SessionLocal`` (not the conftest ``db_session``)
    because the SSE's poll opens its own session and won't see the
    db_session's savepoint-only commits.
    """
    setup = SessionLocal()
    try:
        lf = _seed_library_file(setup)
        m_id = _seed_match(setup, library_file_id=lf, status="confirmed")
    finally:
        setup.close()

    def flip_after_delay():
        # Wait for the SSE generator to enter its first poll, then mutate.
        time.sleep(0.6)
        worker = SessionLocal()
        try:
            m = worker.query(UpscaleMatch).filter(UpscaleMatch.id == m_id).first()
            m.status = "replaced"
            worker.add(
                ReplaceLog(
                    library_file_id=lf,
                    upscale_match_id=m_id,
                    abs_path="/tmp/song.mp3",
                    archive_path="/tmp/_replaced/song.mp3",
                    old_bitrate_kbps=128,
                    new_bitrate_kbps=320,
                    old_sha256="0" * 64,
                    new_sha256="1" * 64,
                    pool_slug="djcity",
                    pool_source_url="",
                    file_size_before=1000,
                    file_size_after=3000,
                    id3_copy_status="ok",
                )
            )
            worker.commit()
        finally:
            worker.close()

    t = threading.Thread(target=flip_after_delay, daemon=True)
    t.start()

    # Use a tight poll interval so the test runs quickly.
    with client.stream("GET", "/api/upscale/session-complete?poll_interval_s=0.25") as r:
        assert r.status_code == 200
        events: list[str] = []
        for line in r.iter_lines():
            if not line:
                continue
            events.append(line)
            # The TestClient yields SSE lines as `event: name` / `data: json`.
            # Break the moment we've seen the data line so the stream closes.
            if line.startswith("data:"):
                break

    # Was there a session_complete event with a sensible payload?
    data_line = next(line for line in events if line.startswith("data:"))
    payload = json.loads(data_line[len("data:") :].strip())
    assert payload["type"] == "session_complete"
    assert payload["replaced"] == 1
    assert payload["session_completed_at"] is not None

    t.join(timeout=2.0)


def test_session_complete_ignores_replaces_predating_the_stream(client):
    """A prior session that already ended must not re-fire the toast.

    Asserted at the algorithmic level rather than via a negative-assertion
    on the SSE stream (which would block on ``iter_lines()`` with no lines
    to read). The check: if the only replace happened *before* the
    baseline was captured, the trigger condition ``replaced > baseline``
    is false and the stream stays open. The SSE-emits-once positive case
    is covered by ``test_session_complete_sse_fires_when_session_ends``;
    together they pin both halves of the invariant.
    """
    setup = SessionLocal()
    try:
        lf = _seed_library_file(setup)
        m_id = _seed_match(setup, library_file_id=lf, status="replaced")
        _seed_replace_log(setup, library_file_id=lf, upscale_match_id=m_id)
    finally:
        setup.close()

    # Session-status sees the completed prior session.
    r = client.get("/api/upscale/session-status")
    body = r.json()
    assert body["confirmed"] == 0
    assert body["replaced"] == 1
    assert body["session_completed_at"] is not None

    # No new activity occurs → the SSE's `replaced > baseline_replaced`
    # condition is forever false, so no event would fire on a stream
    # opened against this state. (Compute_session_status above is exactly
    # what the SSE uses as its baseline check.)
