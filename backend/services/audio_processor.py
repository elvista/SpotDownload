"""FFmpeg, ffprobe, and yt-dlp helpers for Mixtape ID (chunks and source downloads)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from pathlib import Path

logger = logging.getLogger("spotdownload.audio_processor")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TEMP_DIR = BACKEND_ROOT / "temp"
UPLOADS_DIR = BACKEND_ROOT / "uploads"


def ensure_dirs() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


async def get_audio_duration(file_path: str) -> float:
    """Return duration in seconds via ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        raise RuntimeError(f"ffprobe failed: {err}")
    try:
        return float(stdout.decode().strip())
    except ValueError as e:
        raise RuntimeError(f"Invalid duration from ffprobe: {stdout!r}") from e


async def extract_chunk(
    file_path: str,
    start_time: float,
    duration: float,
    timeout_ms: int = 30000,
) -> str:
    """Extract a segment to MP3 in temp/; returns output path."""
    ensure_dirs()
    output_path = TEMP_DIR / f"chunk-{int(time.time() * 1000)}-{start_time}.mp3"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-ss",
        str(start_time),
        "-i",
        file_path,
        "-t",
        str(duration),
        "-acodec",
        "libmp3lame",
        "-ab",
        "128k",
        "-ac",
        "2",
        "-ar",
        "44100",
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_ms / 1000)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"FFmpeg timed out extracting chunk at {start_time}s")
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        raise RuntimeError(f"FFmpeg extract failed: {err}")
    return str(output_path)


async def _run_ytdlp_json(url: str) -> dict:
    """Fetch metadata JSON without downloading."""
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "--dump-json",
        "--no-download",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        raise RuntimeError(err or "yt-dlp metadata failed")
    import json

    return json.loads(stdout.decode())


async def download_from_url(url: str) -> tuple[str, str]:
    """
    Download audio from YouTube / SoundCloud / Mixcloud (anything yt-dlp supports).
    Returns (file_path, title).
    """
    ensure_dirs()
    metadata = await _run_ytdlp_json(url)
    title = metadata.get("title") or "Download"
    ts = int(time.time() * 1000)
    output_path = TEMP_DIR / f"source-{ts}.%(ext)s"
    final_mp3 = TEMP_DIR / f"source-{ts}.mp3"

    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        url,
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--no-playlist",
        "--no-warnings",
        "--output",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        if "403" in err or "Forbidden" in err:
            proc2 = await asyncio.create_subprocess_exec(
                "yt-dlp",
                url,
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "--no-playlist",
                "-f",
                "ba/b",
                "--output",
                str(output_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err2 = await proc2.communicate()
            if proc2.returncode != 0:
                raise RuntimeError(
                    "YouTube blocked the request or download failed. Try: brew upgrade yt-dlp"
                )
        else:
            if shutil.which("yt-dlp") is None:
                raise RuntimeError("yt-dlp not found. Install with: brew install yt-dlp")
            raise RuntimeError(f"Download failed: {err[:500]}")

    # Find produced file
    if final_mp3.exists() and final_mp3.stat().st_size > 0:
        return str(final_mp3), title

    pattern = re.compile(rf"source-{ts}\.")
    for p in TEMP_DIR.iterdir():
        if pattern.search(p.name) and p.suffix.lower() == ".mp3" and p.stat().st_size > 0:
            return str(p), title

    raise RuntimeError("Download finished but MP3 not found in temp directory")


def cleanup_temp_file(path: str | None) -> None:
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def cleanup_all_temp_files() -> None:
    if not TEMP_DIR.exists():
        return
    for p in TEMP_DIR.iterdir():
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
