import asyncio
import os
import logging
from pathlib import Path

from database import SessionLocal
from models import AppSetting

logger = logging.getLogger("spotdownload.downloader")

DEFAULT_DOWNLOAD_PATH = str(Path.home() / "Music" / "SpotDownload")


def get_download_path() -> str:
    """Read download path from DB settings, fall back to default."""
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "download_path").first()
        path = row.value if row else DEFAULT_DOWNLOAD_PATH
    finally:
        db.close()
    os.makedirs(path, exist_ok=True)
    return path


class DownloaderService:
    async def download_track(
        self, name: str, artist: str, spotify_url: str = ""
    ) -> bool:
        """Download a single track using yt-dlp by searching YouTube."""
        search_query = f"{artist} - {name}"
        download_path = get_download_path()
        output_template = os.path.join(download_path, "%(title)s.%(ext)s")

        try:
            process = await asyncio.create_subprocess_exec(
                "yt-dlp",
                f"ytsearch1:{search_query}",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--output", output_template,
                "--no-playlist",
                "--quiet",
                "--no-warnings",
                "--embed-thumbnail",
                "--add-metadata",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"Downloaded: {search_query} -> {download_path}")
                return True
            else:
                err_msg = stderr.decode().strip() if stderr else "Unknown error"
                logger.error(f"Failed to download '{search_query}': {err_msg}")
                return False

        except FileNotFoundError:
            raise RuntimeError(
                "yt-dlp not found. Install it with: pip install yt-dlp"
            )
        except Exception as e:
            logger.error(f"Download error for '{search_query}': {e}")
            raise RuntimeError(f"Download failed: {e}")
