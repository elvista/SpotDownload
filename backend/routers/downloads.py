import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from database import get_db
from models import Track
from services.downloader import DownloaderService

router = APIRouter(tags=["downloads"])

downloader = DownloaderService()

# In-memory progress store
download_progress: dict[str, dict] = {}


class DownloadRequest(BaseModel):
    track_ids: list[int] = []
    playlist_id: int | None = None


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

    track_data = [
        {
            "id": t.id,
            "spotify_url": t.spotify_url,
            "name": t.name,
            "artist": t.artist,
        }
        for t in tracks
    ]

    # Launch download in background
    asyncio.create_task(
        _run_downloads(track_data, db_tracks={t.id: t for t in tracks}, db=db)
    )

    return {"detail": f"Started downloading {len(tracks)} tracks", "count": len(tracks)}


async def _run_downloads(track_data: list[dict], db_tracks: dict, db: Session):
    for t in track_data:
        track_id = str(t["id"])
        download_progress[track_id] = {
            "id": t["id"],
            "name": t["name"],
            "artist": t["artist"],
            "status": "downloading",
            "progress": 0,
        }

        try:
            success = await downloader.download_track(
                name=t["name"],
                artist=t["artist"],
                spotify_url=t["spotify_url"],
            )
            download_progress[track_id]["status"] = "completed" if success else "failed"
            download_progress[track_id]["progress"] = 100 if success else 0

            if success and t["id"] in db_tracks:
                db_track = db_tracks[t["id"]]
                db_track.is_downloaded = True
                db.commit()
        except Exception as e:
            download_progress[track_id]["status"] = "failed"
            download_progress[track_id]["error"] = str(e)


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
    return {"detail": "Progress cleared"}
