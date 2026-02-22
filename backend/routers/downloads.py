import asyncio
import json
import os
from collections import deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import get_db, SessionLocal
from models import Track, AppSetting, Playlist
from config import DEFAULT_DOWNLOAD_PATH
from services.downloader import DownloaderService
from services.spotify import get_spotify_service

router = APIRouter(tags=["downloads"])

downloader = DownloaderService()

# Bounded progress store (max 200 entries)
MAX_PROGRESS_ENTRIES = 200
download_progress: dict[str, dict] = {}
_progress_order: deque[str] = deque(maxlen=MAX_PROGRESS_ENTRIES)

# Max concurrent downloads
CONCURRENT_DOWNLOADS = 3


class DownloadRequest(BaseModel):
    track_ids: list[int] = []
    playlist_id: int | None = None


def _resolve_download_path() -> str:
    """Resolve download path from DB once per batch."""
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "download_path").first()
        path = row.value if row else DEFAULT_DOWNLOAD_PATH
    finally:
        db.close()
    os.makedirs(path, exist_ok=True)
    return path


@router.post("/downloads")
async def start_download(body: DownloadRequest, db: Session = Depends(get_db)):
    if body.playlist_id:
        tracks = db.query(Track).filter(Track.playlist_id == body.playlist_id).all()
    elif body.track_ids:
        tracks = db.query(Track).filter(Track.id.in_(body.track_ids)).all()
    else:
        raise HTTPException(status_code=400, detail="Provide track_ids or playlist_id")

    if not tracks:
        raise HTTPException(status_code=404, detail="No tracks found")

    # Extract plain data before request ends (don't pass ORM objects to background)
    track_data = [
        {
            "id": t.id,
            "spotify_id": t.spotify_id,
            "spotify_url": t.spotify_url,
            "name": t.name,
            "artist": t.artist,
            "album": t.album or "",
            "image_url": t.image_url or "",
            "genre": getattr(t, "genre", "") or "",
        }
        for t in tracks
    ]
    track_ids = [t.id for t in tracks]

    # Get source playlist info if this is a playlist download
    source_playlist_id = None
    source_playlist_spotify_id = None
    if body.playlist_id:
        playlist = db.query(Playlist).filter(Playlist.id == body.playlist_id).first()
        if playlist:
            source_playlist_id = playlist.id
            source_playlist_spotify_id = playlist.spotify_id

    # Resolve download path once for the entire batch
    download_path = _resolve_download_path()

    # Launch download in background with its own DB session
    asyncio.create_task(
        _run_downloads(
            track_data, 
            track_ids, 
            download_path,
            source_playlist_id,
            source_playlist_spotify_id
        )
    )

    return {"detail": f"Started downloading {len(tracks)} tracks", "count": len(tracks)}


def _get_setting_from_db(key: str, default: str = "") -> str:
    """Helper to get setting from DB (sync)."""
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        return row.value if row else default
    finally:
        db.close()


async def _post_download_workflow(
    track_data: list[dict], 
    successful_ids: list[int], 
    monitored_playlist_spotify_id: str
):
    """
    Post-download workflow: move successful tracks to archive playlist 
    and empty the monitored playlist on Spotify.
    """
    import logging
    logger = logging.getLogger("spotdownload.downloads")
    
    try:
        # Get user tokens from DB
        access_token = _get_setting_from_db("spotify_access_token", "")
        refresh_token = _get_setting_from_db("spotify_refresh_token", "")
        expires_at_str = _get_setting_from_db("spotify_token_expires_at", "0")
        
        if not refresh_token:
            logger.warning("No Spotify user token found. Skipping post-download workflow. Connect Spotify account to enable archive and empty features.")
            return
        
        expires_at = int(expires_at_str)
        
        # Get archive playlist name from settings
        archive_name = _get_setting_from_db("archive_playlist_name", "DJ Archive")
        
        # Get user-authenticated Spotify client
        spotify = get_spotify_service()
        sp_user, updated_token_info = spotify.get_user_client(
            access_token, refresh_token, expires_at
        )
        
        # Update tokens in DB if they were refreshed
        if updated_token_info["access_token"] != access_token:
            db = SessionLocal()
            try:
                def set_setting(key: str, value: str):
                    row = db.query(AppSetting).filter(AppSetting.key == key).first()
                    if row:
                        row.value = value
                    else:
                        db.add(AppSetting(key=key, value=value))
                
                set_setting("spotify_access_token", updated_token_info["access_token"])
                set_setting("spotify_token_expires_at", str(updated_token_info["expires_at"]))
                db.commit()
            finally:
                db.close()
        
        # 1. Get or create archive playlist
        archive_playlist_id = await spotify.get_or_create_archive_playlist(
            sp_user, archive_name
        )
        
        if not archive_playlist_id:
            logger.error("Failed to get or create archive playlist")
            return
        
        # 2. Build Spotify URIs for successful tracks
        successful_track_uris = []
        for track in track_data:
            if track["id"] in successful_ids and track.get("spotify_id"):
                uri = f"spotify:track:{track['spotify_id']}"
                successful_track_uris.append(uri)
        
        if not successful_track_uris:
            logger.warning("No Spotify URIs to add to archive")
            return
        
        # 3. Add successful tracks to archive playlist
        logger.info(f"Adding {len(successful_track_uris)} tracks to archive playlist '{archive_name}'")
        success = await spotify.add_tracks_to_playlist(
            sp_user, archive_playlist_id, successful_track_uris
        )
        
        if not success:
            logger.error("Failed to add tracks to archive playlist")
            return
        
        # 4. Empty the monitored playlist
        logger.info(f"Emptying monitored playlist {monitored_playlist_spotify_id}")
        success = await spotify.empty_playlist(sp_user, monitored_playlist_spotify_id)
        
        if success:
            logger.info("Post-download workflow completed successfully")
        else:
            logger.error("Failed to empty monitored playlist")
    
    except Exception as e:
        logger.error(f"Post-download workflow failed: {e}", exc_info=True)


async def _download_one(
    t: dict, download_path: str, sem: asyncio.Semaphore
):
    """Download a single track with semaphore-limited concurrency."""
    track_id = str(t["id"])
    download_progress[track_id] = {
        "id": t["id"],
        "name": t["name"],
        "artist": t["artist"],
        "status": "downloading",
        "progress": 0,
    }
    _progress_order.append(track_id)

    async with sem:
        try:
            success = await downloader.download_track(
                name=t["name"],
                artist=t["artist"],
                album=t.get("album", "") or "",
                image_url=t.get("image_url", "") or "",
                genre=t.get("genre", "") or "",
                track_id=t["id"],
                download_path=download_path,
                spotify_url=t["spotify_url"],
            )
            download_progress[track_id]["status"] = "completed" if success else "failed"
            download_progress[track_id]["progress"] = 100 if success else 0
            return t["id"] if success else None
        except Exception as e:
            download_progress[track_id]["status"] = "failed"
            download_progress[track_id]["error"] = str(e)
            return None


async def _run_downloads(
    track_data: list[dict], 
    track_ids: list[int], 
    download_path: str,
    source_playlist_id: int | None = None,
    source_playlist_spotify_id: str | None = None
):
    """Run concurrent downloads with own DB session."""
    sem = asyncio.Semaphore(CONCURRENT_DOWNLOADS)

    # Run all downloads concurrently
    results = await asyncio.gather(
        *[_download_one(t, download_path, sem) for t in track_data]
    )

    # Update DB with successful downloads using a fresh session
    successful_ids = [r for r in results if r is not None]
    if successful_ids:
        db = SessionLocal()
        try:
            db.query(Track).filter(Track.id.in_(successful_ids)).update(
                {Track.is_downloaded: True}, synchronize_session="fetch"
            )
            db.commit()
        finally:
            db.close()

    # Post-download workflow: move to archive and empty monitored playlist
    if source_playlist_id and source_playlist_spotify_id and successful_ids:
        await _post_download_workflow(
            track_data, successful_ids, source_playlist_spotify_id
        )

    # Evict old entries if over limit
    while len(download_progress) > MAX_PROGRESS_ENTRIES:
        oldest = _progress_order.popleft() if _progress_order else None
        if oldest and oldest in download_progress:
            del download_progress[oldest]


@router.get("/downloads/progress")
async def download_progress_stream():
    async def event_generator():
        while True:
            if download_progress:
                yield {
                    "event": "progress",
                    "data": json.dumps(list(download_progress.values())),
                }
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())


@router.delete("/downloads/progress")
def clear_progress():
    download_progress.clear()
    _progress_order.clear()
    return {"detail": "Progress cleared"}
