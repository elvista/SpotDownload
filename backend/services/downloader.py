"""Download audio via yt-dlp and apply Spotify metadata (ID3 tags, cover art).

YouTube search returns the first hit; audio may not match the Spotify track (covers, wrong
uploads, indie/niche ambiguity). The project documents this as a known limitation and does
not implement automatic verification — see README. Download progress includes source_url /
source_title for manual checks.
"""

import asyncio
import logging
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass

from mutagen.id3 import APIC, ID3, TALB, TCON, TIT2, TPE1
from mutagen.mp3 import MP3

logger = logging.getLogger("spotdownload.downloader")


@dataclass(frozen=True)
class DownloadResult:
    """Result of a yt-dlp download; audio is matched from YouTube, not Spotify."""

    ok: bool
    source_url: str = ""
    source_title: str = ""


def _sanitize_filename(s: str) -> str:
    """Remove or replace characters that are invalid in filenames. Max 255 chars."""
    if not s or not isinstance(s, str):
        return "Unknown"
    # Remove path separators and other invalid chars
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s)
    # Normalize whitespace and strip
    s = " ".join(s.split()).strip() or "Unknown"
    # Truncate to 255 bytes for filesystem compatibility (UTF-8)
    if len(s.encode("utf-8")) > 255:
        while s and len(s.encode("utf-8")) > 255:
            s = s[:-1]
    return s or "Unknown"


def _unique_path(download_path: str, base_name: str, ext: str = "mp3") -> str:
    """Return a path that does not overwrite existing files."""
    path = os.path.join(download_path, f"{base_name}.{ext}")
    if not os.path.exists(path):
        return path
    i = 1
    while True:
        path = os.path.join(download_path, f"{base_name} ({i}).{ext}")
        if not os.path.exists(path):
            return path
        i += 1


def _fetch_cover_bytes(image_url: str) -> bytes | None:
    """Fetch image bytes from URL; return None on failure."""
    if not image_url or not image_url.startswith("http"):
        return None
    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": "SpotDownload/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except Exception as e:
        logger.warning(f"Failed to fetch cover image: {e}")
        return None


def _apply_id3_spotify(
    file_path: str,
    name: str,
    artist: str,
    album: str = "",
    image_url: str = "",
    genre: str = "",
) -> None:
    """Set ID3 tags from Spotify data. Best-effort: log and continue on APIC failure."""
    try:
        audio = MP3(file_path, ID3=ID3)
        try:
            audio.add_tags()
        except Exception:
            pass

        if audio.tags is None:
            audio.add_tags()

        audio.tags.add(TIT2(encoding=3, text=name))
        audio.tags.add(TPE1(encoding=3, text=artist))
        if album:
            audio.tags.add(TALB(encoding=3, text=album))
        if genre:
            audio.tags.add(TCON(encoding=3, text=genre))

        if image_url:
            cover_data = _fetch_cover_bytes(image_url)
            if cover_data:
                # Determine mime from URL or default to jpeg
                mime = "image/jpeg"
                if ".png" in image_url.lower():
                    mime = "image/png"
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime=mime,
                        type=3,  # Cover (front)
                        desc="Cover",
                        data=cover_data,
                    )
                )

        audio.save()
    except Exception as e:
        logger.warning(f"ID3 tag write failed for {file_path}: {e}")
        raise


class DownloaderService:
    async def download_track(
        self,
        name: str,
        artist: str,
        download_path: str,
        spotify_url: str = "",
        *,
        album: str = "",
        image_url: str = "",
        genre: str = "",
        track_id: int | None = None,
    ) -> DownloadResult:
        """Download a single track using yt-dlp, then set ID3 tags from Spotify and rename."""
        search_query = f"{artist} - {name}"
        tid = track_id if track_id is not None else id(self)
        output_template = os.path.join(download_path, f"track_{tid}.%(ext)s")
        expected_mp3 = os.path.join(download_path, f"track_{tid}.mp3")
        path_u: str | None = None
        path_t: str | None = None

        try:
            fd_u, path_u = tempfile.mkstemp(
                suffix=".txt", prefix=f"ytdlp_{tid}_url_", dir=download_path
            )
            fd_t, path_t = tempfile.mkstemp(
                suffix=".txt", prefix=f"ytdlp_{tid}_title_", dir=download_path
            )
            os.close(fd_u)
            os.close(fd_t)

            process = await asyncio.create_subprocess_exec(
                "yt-dlp",
                f"ytsearch1:{search_query}",
                "--print-to-file",
                "%(webpage_url)s",
                path_u,
                "--print-to-file",
                "%(title)s",
                path_t,
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "--output",
                output_template,
                "--no-playlist",
                "--no-progress",
                "--no-warnings",
                "--embed-thumbnail",
                "--add-metadata",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            source_url = ""
            source_title = ""
            try:
                if os.path.isfile(path_u):
                    with open(path_u, encoding="utf-8", errors="replace") as f:
                        source_url = f.read().strip()
                if os.path.isfile(path_t):
                    with open(path_t, encoding="utf-8", errors="replace") as f:
                        source_title = f.read().strip()
            finally:
                for p in (path_u, path_t):
                    if p:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                path_u = path_t = None

            if process.returncode != 0:
                err_msg = stderr.decode().strip() if stderr else "Unknown error"
                logger.error(f"Failed to download '{search_query}': {err_msg}")
                return DownloadResult(False)

            if not os.path.isfile(expected_mp3):
                logger.error(f"Expected file missing after yt-dlp: {expected_mp3}")
                return DownloadResult(False)

            if os.path.getsize(expected_mp3) <= 0:
                logger.error(f"Downloaded file is empty: {expected_mp3}")
                try:
                    os.remove(expected_mp3)
                except OSError:
                    pass
                return DownloadResult(False)

            # Set ID3 tags from Spotify in thread (blocking: file I/O + cover fetch)
            try:
                await asyncio.to_thread(
                    _apply_id3_spotify, expected_mp3, name, artist, album, image_url, genre
                )
            except Exception as e:
                logger.warning(f"ID3 tagging failed, keeping file: {e}")

            # Rename to friendly name (blocking file op)
            safe_artist = _sanitize_filename(artist)
            safe_name = _sanitize_filename(name)
            base_name = f"{safe_artist} - {safe_name}"
            final_path = _unique_path(download_path, base_name, "mp3")
            try:
                await asyncio.to_thread(os.rename, expected_mp3, final_path)
            except OSError as e:
                logger.warning(f"Rename failed, leaving as {expected_mp3}: {e}")

            logger.info(f"Downloaded: {search_query} -> {download_path}")
            return DownloadResult(True, source_url=source_url, source_title=source_title)

        except FileNotFoundError:
            raise RuntimeError("yt-dlp not found. Install it with: pip install yt-dlp")
        except Exception as e:
            logger.error(f"Download error for '{search_query}': {e}")
            raise RuntimeError(f"Download failed: {e}")
        finally:
            if path_u:
                try:
                    os.remove(path_u)
                except OSError:
                    pass
            if path_t:
                try:
                    os.remove(path_t)
                except OSError:
                    pass
