"""Library scanner: walk a folder, identify low-bitrate audio files, persist
to ``library_files`` and ``scan_runs``.

This is step 2 of the Upscale section (see Studio post 93e17e1d). It owns the
on-disk audio inventory — no pool / scrape / swap logic here. Pool scrapers and
the swap engine plug into ``library_files`` rows by ``id`` in later steps.

The scanner is **idempotent**: re-scanning the same root updates rows whose
content (sha256 + mtime_ns) changed and inserts new rows; rows for files that
have moved or been deleted are NOT removed here. Removal/cleanup belongs in a
future step (`/upscale/library/prune`) so a transient mount failure doesn't
wipe rows that downstream `replace_logs` still reference.

Bitrate detection uses ``mutagen`` — already in requirements.txt. Files that
mutagen can't parse are skipped (counted toward ``files_seen`` but not
``candidates``); an error is logged. SHA-256 is read in 1 MiB chunks so we
don't pin memory on large WAVs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from sqlalchemy.orm import Session

from database import SessionLocal
from models import LibraryFile, ScanRun

logger = logging.getLogger("cratedigger.upscale.scanner")

# File extensions we consider for the Upscale inventory. Matches the formats
# Rekordbox/Lexicon DJs typically have in their crates. Lossless formats
# (FLAC, AIFF, WAV) are included so the scanner can report them as "already
# good" rather than skipping silently — downstream filtering happens at the
# /candidates query (bitrate_kbps ≤ threshold).
_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".aiff", ".aif", ".wav", ".ogg", ".opus"}

# Batch size for DB commits during a scan. Keeps the WAL from ballooning on
# multi-thousand-file libraries while still amortising commit overhead.
_COMMIT_BATCH = 50

# Progress-event throttle: emit at most one `progress` event per N files. Avoids
# flooding the SSE channel on big libraries.
_PROGRESS_EVERY = 25


# --- Public dataclasses ------------------------------------------------------


@dataclass(frozen=True)
class FileProbe:
    """Result of probing one file with mutagen + the filesystem."""

    abs_path: str
    sha256: str
    size_bytes: int
    bitrate_kbps: int
    duration_s: float | None
    mtime_ns: int
    tag_title: str
    tag_artist: str
    tag_album: str


SendEvent = Callable[[dict[str, Any]], Awaitable[None]]


# --- Helpers -----------------------------------------------------------------


def _iter_audio_paths(root: Path) -> list[Path]:
    """Walk ``root`` and return every file whose suffix is in :data:`_AUDIO_EXTS`."""
    paths: list[Path] = []
    for dirpath, _, filenames in os.walk(root, followlinks=False):
        # Skip the archive folder produced by the swap engine. Those files are
        # the *originals* we replaced — feeding them back into the candidate
        # list would create a re-upscale loop.
        if "_replaced" in Path(dirpath).parts:
            continue
        for name in filenames:
            if Path(name).suffix.lower() in _AUDIO_EXTS:
                paths.append(Path(dirpath) / name)
    return paths


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(path: Path) -> FileProbe | None:
    """Read filesystem stat + mutagen tags. Returns ``None`` if unparseable."""
    try:
        stat = path.stat()
    except OSError as e:
        logger.warning("scanner: stat failed for %s: %s", path, e)
        return None

    try:
        mf = MutagenFile(str(path))
    except Exception as e:  # noqa: BLE001 — mutagen raises a wide tree
        logger.warning("scanner: mutagen failed on %s: %s", path, e)
        return None

    if mf is None or getattr(mf, "info", None) is None:
        return None

    info = mf.info
    bitrate_bps = int(getattr(info, "bitrate", 0) or 0)
    bitrate_kbps = bitrate_bps // 1000 if bitrate_bps else 0
    duration_s = float(getattr(info, "length", 0.0) or 0.0) or None

    tags = mf.tags
    tag_title = _first_tag(tags, ("TIT2", "title", "\xa9nam"))
    tag_artist = _first_tag(tags, ("TPE1", "artist", "\xa9ART"))
    tag_album = _first_tag(tags, ("TALB", "album", "\xa9alb"))

    return FileProbe(
        abs_path=str(path.resolve()),
        sha256=_sha256(path),
        size_bytes=stat.st_size,
        bitrate_kbps=bitrate_kbps,
        duration_s=duration_s,
        mtime_ns=stat.st_mtime_ns,
        tag_title=tag_title,
        tag_artist=tag_artist,
        tag_album=tag_album,
    )


def _first_tag(tags: Any, keys: tuple[str, ...]) -> str:
    if not tags:
        return ""
    for key in keys:
        try:
            val = tags.get(key)
        except Exception:  # noqa: BLE001
            continue
        if val is None:
            continue
        # Mutagen returns frame objects for ID3, plain lists for Vorbis/MP4.
        if isinstance(val, list):
            return str(val[0]) if val else ""
        text = getattr(val, "text", None)
        if text:
            return str(text[0]) if isinstance(text, list) and text else str(text)
        return str(val)
    return ""


def _upsert_library_file(db: Session, probe: FileProbe) -> tuple[LibraryFile, bool]:
    """Insert or update a ``library_files`` row by ``abs_path``.

    Returns ``(row, created)``; ``created`` is True if a new row was inserted.
    """
    existing = db.query(LibraryFile).filter(LibraryFile.abs_path == probe.abs_path).first()
    if existing is None:
        row = LibraryFile(
            abs_path=probe.abs_path,
            sha256=probe.sha256,
            size_bytes=probe.size_bytes,
            bitrate_kbps=probe.bitrate_kbps,
            duration_s=probe.duration_s,
            mtime_ns=probe.mtime_ns,
            tag_title=probe.tag_title,
            tag_artist=probe.tag_artist,
            tag_album=probe.tag_album,
            last_scanned=datetime.now(UTC),
        )
        db.add(row)
        return row, True

    existing.sha256 = probe.sha256
    existing.size_bytes = probe.size_bytes
    existing.bitrate_kbps = probe.bitrate_kbps
    existing.duration_s = probe.duration_s
    existing.mtime_ns = probe.mtime_ns
    existing.tag_title = probe.tag_title
    existing.tag_artist = probe.tag_artist
    existing.tag_album = probe.tag_album
    existing.last_scanned = datetime.now(UTC)
    return existing, False


# --- Public entry points ------------------------------------------------------


def start_scan_run(db: Session, root_path: str) -> ScanRun:
    """Create a ``scan_runs`` row up-front so the SSE client can subscribe."""
    run = ScanRun(root_path=root_path, started_at=datetime.now(UTC))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


async def scan_root(
    *,
    scan_id: int,
    root_path: str,
    threshold_kbps: int,
    send_event: SendEvent,
) -> None:
    """Walk ``root_path`` and persist every audio file as a ``library_files`` row.

    Emits SSE events via ``send_event``:
      - ``{type: "start", root, total}`` once after the walk completes
      - ``{type: "progress", scanned, total, candidates, current}`` throttled
      - ``{type: "complete", scanned, candidates, duration_s}`` on success
      - ``{type: "error", error}`` on fatal failure (and the scan_run row is
        marked with the error message)

    The function does its own DB session management with batched commits so
    long scans don't hold a single session for minutes (matching the pattern
    in ``routers/downloads.py``).
    """
    root = Path(root_path).expanduser().resolve()
    started = time.monotonic()
    scanned = 0
    candidates = 0

    if not root.exists() or not root.is_dir():
        msg = f"root path does not exist or is not a directory: {root}"
        _mark_scan_finished(scan_id, error=msg)
        await send_event({"type": "error", "error": msg})
        return

    try:
        paths = await asyncio.to_thread(_iter_audio_paths, root)
    except Exception as e:  # noqa: BLE001
        msg = f"failed to walk root: {e}"
        logger.exception("scanner: walk failed")
        _mark_scan_finished(scan_id, error=msg)
        await send_event({"type": "error", "error": msg})
        return

    total = len(paths)
    await send_event({"type": "start", "root": str(root), "total": total})

    db: Session = SessionLocal()
    try:
        batch_pending = 0
        for idx, path in enumerate(paths, start=1):
            probe = await asyncio.to_thread(_probe, path)
            scanned += 1
            if probe is not None:
                _upsert_library_file(db, probe)
                if probe.bitrate_kbps and probe.bitrate_kbps <= threshold_kbps:
                    candidates += 1
                batch_pending += 1

            if batch_pending >= _COMMIT_BATCH:
                db.commit()
                batch_pending = 0

            if idx % _PROGRESS_EVERY == 0 or idx == total:
                await send_event(
                    {
                        "type": "progress",
                        "scanned": scanned,
                        "total": total,
                        "candidates": candidates,
                        "current": str(path),
                    }
                )

        if batch_pending:
            db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        msg = f"scan failed: {e}"
        logger.exception("scanner: scan failed mid-run")
        _mark_scan_finished(scan_id, files_seen=scanned, candidates=candidates, error=msg)
        await send_event({"type": "error", "error": msg})
        return
    finally:
        db.close()

    duration_s = time.monotonic() - started
    _mark_scan_finished(scan_id, files_seen=scanned, candidates=candidates)
    await send_event(
        {
            "type": "complete",
            "scanned": scanned,
            "candidates": candidates,
            "duration_s": round(duration_s, 2),
        }
    )


def _mark_scan_finished(
    scan_id: int,
    *,
    files_seen: int | None = None,
    candidates: int | None = None,
    error: str = "",
) -> None:
    """Update the ``scan_runs`` row with terminal state. Uses its own session."""
    db: Session = SessionLocal()
    try:
        run = db.query(ScanRun).filter(ScanRun.id == scan_id).first()
        if run is None:
            return
        run.finished_at = datetime.now(UTC)
        if files_seen is not None:
            run.files_seen = files_seen
        if candidates is not None:
            run.candidates = candidates
        run.error = error
        db.commit()
    finally:
        db.close()
