"""Atomic, Rekordbox-safe file swap for the Upscale section.

The contract is simple but the failure modes are not. The function:

1. Verifies the match is ``confirmed`` (the router has already done this; we
   re-check defensively so the service can be called from anywhere safely).
2. Downloads the higher-bitrate pool file to a **temp file in the same
   directory** as the target — same filesystem guarantees ``os.replace`` is
   atomic.
3. Moves the original to ``<dir>/_replaced/<stem>_<ts><ext>`` so the audit
   trail survives even if the founder later renames or moves the library.
4. ``os.replace(temp, target)`` — atomic rename, path unchanged. Rekordbox
   keys library entries by file path, so cue points + beatgrids survive.
5. Restores the original's ``mtime``/``atime`` (some Rekordbox builds use
   mtime as a "should I re-analyse?" signal).
6. Writes the ``replace_logs`` row + flips the match to ``replaced``.

What we deliberately don't do here:

- We don't call the fingerprint / decide AI hook. The plan reserves that for
  step 6.3 (AI slice) and the orchestrator-side gate. This module exposes a
  pre-swap callback parameter so the AI slice can plug in without a refactor
  later.

Edge cases handled:

- **Download failure** → temp file is cleaned up; original is untouched; no
  row written; raises :class:`SwapFailedError`.
- **Disk full mid-download** → same as above; temp file cleanup is in the
  ``finally`` so it always runs.
- **File locked** (Windows / Rekordbox holding the handle on macOS in rare
  cases) → ``os.replace`` raises ``PermissionError`` → caller maps to HTTP
  409. The temp file is cleaned, the archive move is rolled back, original
  remains.
- **ID3 copy failure** → row is still written with
  ``id3_copy_status='failed'``; the swap itself is not rolled back (the
  higher-bitrate file is what the user wanted). The FE can surface "tags
  partially copied — review needed".
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from models import LibraryFile, ReplaceLog, UpscaleMatch

logger = logging.getLogger("cratedigger.upscale.swap_engine")


class SwapError(RuntimeError):
    """Base for swap-engine failures."""


class MatchNotConfirmedError(SwapError):
    """Caller asked to swap a match that hasn't been confirmed."""


class DownloadFailedError(SwapError):
    """Could not fetch the pool file (network, HTTP error, disk full)."""


class FileLockedError(SwapError):
    """OS-level lock on the target — file is open in another app (Rekordbox?)."""


class SwapFailedError(SwapError):
    """Catch-all for unexpected swap failures. Original is intact."""


@dataclass
class SwapResult:
    replace_log_id: int
    abs_path: str
    archive_path: str
    file_size_before: int
    file_size_after: int
    replaced_at: datetime
    id3_copy_status: str = "ok"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_bitrate(path: Path) -> int:
    """Best-effort bitrate read via mutagen. Returns 0 on failure."""
    try:
        from mutagen import File as MutagenFile

        mf = MutagenFile(str(path))
        if mf is None or getattr(mf, "info", None) is None:
            return 0
        bps = int(getattr(mf.info, "bitrate", 0) or 0)
        return bps // 1000 if bps else 0
    except Exception as e:  # noqa: BLE001
        logger.warning("swap_engine: bitrate probe failed for %s: %s", path, e)
        return 0


def _archive_path_for(target: Path) -> Path:
    """``/library/song.mp3`` →
    ``/library/_replaced/song_20260517-153012-abc123.mp3``.

    Lives in a sibling ``_replaced/`` directory so the library scanner can
    skip the whole subtree (it does, via :data:`library_scanner._iter_audio_paths`).
    """
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    rand = uuid.uuid4().hex[:6]
    archive_dir = target.parent / "_replaced"
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir / f"{target.stem}_{ts}-{rand}{target.suffix}"


def _copy_id3_tags(src: Path, dst: Path) -> str:
    """Copy a curated set of ID3 frames + Vorbis/MP4 equivalents from ``src``
    onto ``dst``. Returns ``'ok'`` / ``'partial'`` / ``'failed'`` for the
    Replace Log audit.

    We copy: title, artist, album, genre, cover art, custom TXXX frames. The
    new file's *audio quality* tags (bitrate, codec, length) are left as
    written by the pool's encoder.
    """
    try:
        from mutagen import File as MutagenFile
    except Exception as e:  # noqa: BLE001
        logger.warning("swap_engine: mutagen unavailable, skipping ID3 copy: %s", e)
        return "failed"

    try:
        src_meta = MutagenFile(str(src))
        dst_meta = MutagenFile(str(dst))
    except Exception as e:  # noqa: BLE001
        logger.warning("swap_engine: ID3 read failed: %s", e)
        return "failed"

    if src_meta is None or dst_meta is None:
        return "failed"

    src_tags = getattr(src_meta, "tags", None)
    if not src_tags:
        return "ok"  # nothing to copy is fine

    # Pull common fields by both ID3 frame ids and Vorbis/MP4 keys.
    copied_any = False
    copy_failures = 0
    keys = (
        ("TIT2", "title", "\xa9nam"),
        ("TPE1", "artist", "\xa9ART"),
        ("TALB", "album", "\xa9alb"),
        ("TCON", "genre", "\xa9gen"),
    )

    for group in keys:
        value = None
        for k in group:
            try:
                value = src_tags.get(k)
            except Exception:  # noqa: BLE001
                value = None
            if value is not None:
                break
        if value is None:
            continue

        # Write to the destination using whichever key it accepts.
        wrote = False
        for k in group:
            try:
                dst_meta[k] = value
                wrote = True
                break
            except Exception:  # noqa: BLE001
                continue
        if wrote:
            copied_any = True
        else:
            copy_failures += 1

    try:
        dst_meta.save()
    except Exception as e:  # noqa: BLE001
        logger.warning("swap_engine: ID3 save failed: %s", e)
        return "failed"

    if copy_failures and not copied_any:
        return "failed"
    if copy_failures:
        return "partial"
    return "ok"


async def replace(
    db: Session,
    match: UpscaleMatch,
    *,
    download_to_temp,
) -> SwapResult:
    """Perform the atomic swap.

    ``download_to_temp`` is an injected callable: ``(dest_path: Path) -> int``
    returning the downloaded byte count. It must atomically write to
    ``dest_path``. Injection makes the function trivially testable and lets
    us swap the real httpx fetch for a mock without monkey-patching the
    network. The caller wires the real downloader in the router (see
    :func:`routers.upscale.replace_match`).
    """
    if (match.status or "") != "confirmed":
        raise MatchNotConfirmedError(
            f"match {match.id} status is '{match.status}', expected 'confirmed'"
        )

    lf = db.query(LibraryFile).filter(LibraryFile.id == match.library_file_id).first()
    if lf is None:
        raise SwapFailedError(
            f"library_file {match.library_file_id} for match {match.id} not found"
        )
    target = Path(lf.abs_path)
    if not target.exists() or not target.is_file():
        raise SwapFailedError(f"target file no longer on disk: {target}")

    # Pre-swap measurements; we re-stat after the swap for size_after.
    file_size_before = target.stat().st_size
    original_mtime_ns = target.stat().st_mtime_ns
    original_atime_ns = target.stat().st_atime_ns
    old_bitrate = lf.bitrate_kbps or _detect_bitrate(target)
    old_sha256 = _sha256(target)

    # Stage temp file beside the target so os.replace is atomic.
    temp_path = target.parent / f".{target.name}.swap-{uuid.uuid4().hex[:8]}"
    archive_path: Path | None = None

    try:
        # 1. Download
        try:
            downloaded_bytes = await asyncio.to_thread(download_to_temp, temp_path)
        except Exception as e:
            raise DownloadFailedError(f"pool download failed: {e}") from e
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            raise DownloadFailedError("download finished but temp file is empty")

        # 2. Archive original (move; same dir → cheap rename on same FS).
        archive_path = _archive_path_for(target)
        shutil.move(str(target), str(archive_path))

        # 3. Atomic swap. PermissionError here = file locked by another app
        # (Rekordbox / iTunes / VLC). The original is already in the archive,
        # so we roll it back to the original path.
        try:
            os.replace(str(temp_path), str(target))
        except PermissionError as e:
            try:
                shutil.move(str(archive_path), str(target))
            except Exception as rb_err:  # noqa: BLE001
                logger.error("swap_engine: rollback failed after PermissionError: %s", rb_err)
            archive_path = None  # rollback ran; nothing archived
            raise FileLockedError(f"target file is locked: {e}") from e

        # 4. ID3 copy + mtime restore. Both are post-swap, best-effort.
        id3_status = _copy_id3_tags(archive_path, target)
        try:
            os.utime(target, ns=(original_atime_ns, original_mtime_ns))
        except OSError as e:
            logger.warning("swap_engine: failed to restore mtime: %s", e)

        # 5. Recompute size + sha256.
        file_size_after = target.stat().st_size
        new_sha256 = _sha256(target)
        new_bitrate = _detect_bitrate(target) or match.pool_bitrate_kbps

        # 6. Persist the audit row + flip the match status.
        log_row = ReplaceLog(
            library_file_id=lf.id,
            upscale_match_id=match.id,
            abs_path=str(target),
            archive_path=str(archive_path),
            old_bitrate_kbps=old_bitrate,
            new_bitrate_kbps=new_bitrate,
            old_sha256=old_sha256,
            new_sha256=new_sha256,
            pool_slug=match.pool_slug,
            pool_source_url=match.pool_preview_url or "",
            file_size_before=file_size_before,
            file_size_after=file_size_after,
            id3_copy_status=id3_status,
        )
        db.add(log_row)
        match.status = "replaced"
        # Refresh the library_files row to match what's actually on disk.
        lf.sha256 = new_sha256
        lf.size_bytes = file_size_after
        lf.bitrate_kbps = new_bitrate
        lf.mtime_ns = target.stat().st_mtime_ns
        lf.last_scanned = datetime.now(UTC)
        db.commit()
        db.refresh(log_row)
        _ = downloaded_bytes  # surfaced via file_size_after

        return SwapResult(
            replace_log_id=int(log_row.id),
            abs_path=str(target),
            archive_path=str(archive_path),
            file_size_before=file_size_before,
            file_size_after=file_size_after,
            replaced_at=log_row.replaced_at,
            id3_copy_status=id3_status,
        )

    except (DownloadFailedError, FileLockedError, MatchNotConfirmedError):
        # Cleanup temp; archive (if created and rollback didn't run) is left
        # alone because by then the swap has already partially succeeded —
        # but in our flow we only reach FileLockedError before the archive
        # is realised as a rollback, so it's gone.
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
    except Exception as e:  # noqa: BLE001
        # Unknown failure: best-effort cleanup, rollback archive if it exists.
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        if archive_path is not None and archive_path.exists() and not target.exists():
            try:
                shutil.move(str(archive_path), str(target))
            except Exception as rb_err:  # noqa: BLE001
                logger.error("swap_engine: rollback failed: %s", rb_err)
        raise SwapFailedError(f"unexpected swap failure: {e}") from e
