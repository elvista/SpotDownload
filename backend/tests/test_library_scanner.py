"""Tests for the Upscale library scanner — service unit + REST surface.

We can't depend on a real MP3 fixture file in CI, so the unit tests stub the
mutagen probe; the route-level test exercises the in-process flow with the
test DB and asserts the candidate listing is filtered by bitrate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from database import SessionLocal
from models import LibraryFile, ScanRun
from services import library_scanner
from services.library_scanner import FileProbe


def _make_probe(path: Path, *, bitrate: int = 128, size: int = 1024) -> FileProbe:
    return FileProbe(
        abs_path=str(path.resolve()),
        sha256="0" * 64,
        size_bytes=size,
        bitrate_kbps=bitrate,
        duration_s=120.0,
        mtime_ns=int(path.stat().st_mtime_ns) if path.exists() else 0,
        tag_title="Test Title",
        tag_artist="Test Artist",
        tag_album="Test Album",
    )


def _seed_audio_tree(tmp_path: Path) -> dict[str, Path]:
    """Create a small fake tree. Real bytes don't matter — we stub `_probe`."""
    root = tmp_path / "library"
    root.mkdir()
    paths = {
        "low": root / "low_bitrate.mp3",
        "mid": root / "mid_bitrate.mp3",
        "high": root / "high_bitrate.mp3",
        "non_audio": root / "notes.txt",
        "archived": root / "_replaced" / "2026" / "01" / "old.mp3",
    }
    for p in paths.values():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return paths


def test_iter_audio_paths_skips_non_audio_and_replaced_archive(tmp_path):
    paths = _seed_audio_tree(tmp_path)
    found = library_scanner._iter_audio_paths(tmp_path / "library")
    names = {p.name for p in found}
    assert "low_bitrate.mp3" in names
    assert "mid_bitrate.mp3" in names
    assert "high_bitrate.mp3" in names
    # Non-audio extension is skipped.
    assert "notes.txt" not in names
    # Files under `_replaced/` are skipped to avoid re-upscale loops.
    assert "old.mp3" not in names
    # And the archived path really exists — we're just not walking it.
    assert paths["archived"].exists()


def test_upsert_library_file_inserts_then_updates(db_session, tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    probe = _make_probe(path, bitrate=128)
    row, created = library_scanner._upsert_library_file(db_session, probe)
    db_session.commit()
    assert created is True
    assert row.abs_path == str(path.resolve())
    assert row.bitrate_kbps == 128

    # Second call with a different bitrate should update in place.
    probe2 = _make_probe(path, bitrate=160)
    row2, created2 = library_scanner._upsert_library_file(db_session, probe2)
    db_session.commit()
    assert created2 is False
    assert row2.id == row.id
    assert row2.bitrate_kbps == 160


def test_scan_root_persists_candidates_and_marks_run_complete(setup_test_db, tmp_path):
    """End-to-end: walk a temp tree, probe (stubbed), commit rows, mark run done.

    Uses a real (non-rollback) SessionLocal because :func:`scan_root` opens its
    own sessions internally — the conftest ``db_session`` fixture wraps the
    test in an outer transaction that's invisible to fresh sessions.
    """
    paths = _seed_audio_tree(tmp_path)
    bitrates = {
        paths["low"]: 128,
        paths["mid"]: 192,
        paths["high"]: 320,
    }

    def fake_probe(p: Path) -> FileProbe | None:
        if p in bitrates:
            return _make_probe(p, bitrate=bitrates[p])
        return None

    setup_db = SessionLocal()
    try:
        run = library_scanner.start_scan_run(setup_db, str(tmp_path / "library"))
        scan_id = int(run.id)
    finally:
        setup_db.close()

    events: list[dict] = []

    async def send_event(data):
        events.append(data)

    with patch("services.library_scanner._probe", side_effect=fake_probe):
        asyncio.run(
            library_scanner.scan_root(
                scan_id=scan_id,
                root_path=str(tmp_path / "library"),
                threshold_kbps=192,
                send_event=send_event,
            )
        )

    verify_db = SessionLocal()
    try:
        rows = (
            verify_db.query(LibraryFile)
            .filter(LibraryFile.abs_path.in_([str(p.resolve()) for p in bitrates]))
            .all()
        )
        assert len(rows) == 3
        assert {r.bitrate_kbps for r in rows} == {128, 192, 320}

        run_after = verify_db.query(ScanRun).filter(ScanRun.id == scan_id).first()
        assert run_after is not None
        assert run_after.finished_at is not None
        assert run_after.files_seen == 3
        # candidates = bitrate ≤ threshold (192) → low + mid count, high does not.
        assert run_after.candidates == 2
        assert run_after.error == ""
    finally:
        # Clean up rows so the next test starts with an empty library.
        verify_db.query(LibraryFile).filter(
            LibraryFile.abs_path.in_([str(p.resolve()) for p in bitrates])
        ).delete(synchronize_session=False)
        verify_db.query(ScanRun).filter(ScanRun.id == scan_id).delete(synchronize_session=False)
        verify_db.commit()
        verify_db.close()

    event_types = [e.get("type") for e in events]
    assert "start" in event_types
    assert "complete" in event_types
    complete = next(e for e in events if e.get("type") == "complete")
    assert complete["scanned"] == 3
    assert complete["candidates"] == 2


def test_scan_root_errors_when_root_missing(setup_test_db, tmp_path):
    missing = tmp_path / "does-not-exist"
    setup_db = SessionLocal()
    try:
        run = library_scanner.start_scan_run(setup_db, str(missing))
        scan_id = int(run.id)
    finally:
        setup_db.close()

    events: list[dict] = []

    async def send_event(data):
        events.append(data)

    asyncio.run(
        library_scanner.scan_root(
            scan_id=scan_id,
            root_path=str(missing),
            threshold_kbps=192,
            send_event=send_event,
        )
    )

    verify_db = SessionLocal()
    try:
        run_after = verify_db.query(ScanRun).filter(ScanRun.id == scan_id).first()
        assert run_after is not None
        assert run_after.finished_at is not None
        assert run_after.error
        verify_db.query(ScanRun).filter(ScanRun.id == scan_id).delete(synchronize_session=False)
        verify_db.commit()
    finally:
        verify_db.close()

    assert any(e.get("type") == "error" for e in events)


# --- Route-level smoke tests --------------------------------------------------


def test_get_settings_returns_defaults(client):
    r = client.get("/api/upscale/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["threshold_kbps"] == 192
    assert body["library_root"]  # falls back to download_path or config default


def test_put_settings_persists(client, tmp_path):
    r = client.put(
        "/api/upscale/settings",
        json={"library_root": str(tmp_path), "threshold_kbps": 256},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["threshold_kbps"] == 256
    assert body["library_root"] == str(tmp_path.resolve())

    r2 = client.get("/api/upscale/settings")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["threshold_kbps"] == 256


def test_post_scan_requires_existing_root(client, tmp_path):
    r = client.post(
        "/api/upscale/scan",
        json={"root": str(tmp_path / "nope"), "threshold_kbps": 192},
    )
    assert r.status_code == 400


def test_candidates_filtered_by_bitrate(client, db_session, tmp_path):
    # Seed three files directly; bypass the scanner so the test is fast and
    # deterministic. The scanner end-to-end is exercised by the unit test
    # above.
    rows = [
        LibraryFile(
            abs_path=str(tmp_path / f"f{i}.mp3"),
            sha256="0" * 64,
            size_bytes=1000,
            bitrate_kbps=br,
            duration_s=180.0,
            mtime_ns=0,
            tag_title=f"t{i}",
            tag_artist="a",
            tag_album="alb",
        )
        for i, br in enumerate([128, 192, 320])
    ]
    for row in rows:
        db_session.add(row)
    db_session.commit()

    r = client.get("/api/upscale/candidates?threshold_kbps=192")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    bitrates = {item["bitrate_kbps"] for item in body["items"]}
    assert bitrates == {128, 192}


@pytest.fixture(autouse=True)
def _reset_upscale_settings(db_session):
    """Ensure upscale settings rows don't bleed between tests."""
    from models import AppSetting

    db_session.query(AppSetting).filter(
        AppSetting.key.in_(["upscale_bitrate_threshold_kbps", "upscale_library_root"])
    ).delete(synchronize_session=False)
    db_session.commit()
    yield
