import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import get_db
from services.monitor import MonitorService

router = APIRouter(tags=["monitor"])

monitor_service = MonitorService()

# In-memory store for notifications
notifications: list[dict] = []


@router.post("/monitor/check-all")
def check_all_playlists(db: Session = Depends(get_db)):
    results = monitor_service.check_all(db)
    # Store notifications for any changes found
    for r in results:
        if r.get("added", 0) > 0 or r.get("removed", 0) > 0:
            notifications.append({
                "type": "playlist_changed",
                "playlist_name": r.get("playlist_name", ""),
                "playlist_id": r.get("playlist_id"),
                "added": r.get("added", 0),
                "removed": r.get("removed", 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    return {"detail": "Check complete", "results": results}


@router.post("/monitor/check/{playlist_id}")
def check_playlist(playlist_id: int, db: Session = Depends(get_db)):
    result = monitor_service.check_one(playlist_id, db)
    if result.get("added", 0) > 0 or result.get("removed", 0) > 0:
        notifications.append({
            "type": "playlist_changed",
            "playlist_name": result.get("playlist_name", ""),
            "playlist_id": result.get("playlist_id"),
            "added": result.get("added", 0),
            "removed": result.get("removed", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return result


@router.get("/monitor/notifications")
async def notification_stream():
    """SSE endpoint for real-time notifications about playlist changes."""
    last_count = len(notifications)

    async def event_generator():
        nonlocal last_count
        while True:
            current_count = len(notifications)
            if current_count > last_count:
                new_notifications = notifications[last_count:]
                last_count = current_count
                yield {
                    "event": "notification",
                    "data": json.dumps(new_notifications),
                }
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


@router.delete("/monitor/notifications")
def clear_notifications():
    notifications.clear()
    return {"detail": "Notifications cleared"}
