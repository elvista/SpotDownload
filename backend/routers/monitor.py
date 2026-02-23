import asyncio
import json
from collections import deque
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import get_db
from services.monitor import MonitorService

router = APIRouter(tags=["monitor"])

monitor_service = MonitorService()

# Bounded notification store (max 200 entries)
notifications: deque[dict] = deque(maxlen=200)


def _add_notification(result: dict):
    """Add a notification if changes were detected."""
    if result.get("added", 0) > 0 or result.get("removed", 0) > 0:
        notifications.append(
            {
                "type": "playlist_changed",
                "playlist_name": result.get("playlist_name", ""),
                "playlist_id": result.get("playlist_id"),
                "added": result.get("added", 0),
                "removed": result.get("removed", 0),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )


@router.post("/monitor/check-all")
def check_all_playlists(db: Session = Depends(get_db)):
    results = monitor_service.check_all(db)
    for r in results:
        _add_notification(r)
    return {"detail": "Check complete", "results": results}


@router.post("/monitor/check/{playlist_id}")
def check_playlist(playlist_id: int, db: Session = Depends(get_db)):
    result = monitor_service.check_one(playlist_id, db)
    _add_notification(result)
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
                new_items = list(notifications)[last_count:]
                last_count = current_count
                yield {
                    "event": "notification",
                    "data": json.dumps(new_items),
                }
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


@router.delete("/monitor/notifications")
def clear_notifications():
    notifications.clear()
    return {"detail": "Notifications cleared"}
