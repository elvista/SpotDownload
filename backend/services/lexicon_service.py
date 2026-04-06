"""Lexicon DJ library reader."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("cratedigger.lexicon")

DEFAULT_DB_PATH = "~/Library/Application Support/Lexicon/main.db"

# Re-export shared Spotify functions so existing imports still work
from services.spotify_service import (  # noqa: E402, F401
    import_playlist_to_spotify,
    search_spotify_track,
    find_existing_spotify_playlist,
)


def resolve_path(raw: str) -> str:
    return str(Path(raw).expanduser().resolve())


def validate_db_path(raw: str) -> dict[str, Any]:
    path = resolve_path(raw)
    if not os.path.isfile(path):
        return {"valid": False, "error": f"File not found: {path}", "path": path}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Playlist'")
        if not cur.fetchone():
            conn.close()
            return {"valid": False, "error": "Not a Lexicon database (missing Playlist table)", "path": path}
        conn.close()
        return {"valid": True, "error": None, "path": path}
    except sqlite3.DatabaseError as e:
        return {"valid": False, "error": f"Not a valid SQLite database: {e}", "path": path}


def get_playlists(db_path: str) -> list[dict[str, Any]]:
    path = resolve_path(db_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, name, type, parentId, position FROM Playlist ORDER BY position")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_playlist_tracks(db_path: str, playlist_id: int) -> list[dict[str, Any]]:
    path = resolve_path(db_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Check if this is a smart playlist (type 3)
    cur.execute("SELECT type, smartlist FROM Playlist WHERE id = ?", (playlist_id,))
    pl = cur.fetchone()
    if pl and str(pl["type"]) == "3" and pl["smartlist"]:
        rows = _execute_smart_playlist(cur, pl["smartlist"])
    else:
        cur.execute(
            """
            SELECT t.artist, t.title
            FROM LinkTrackPlaylist ltp
            JOIN Track t ON t.id = ltp.trackId
            WHERE ltp.playlistId = ?
            ORDER BY ltp.position
            """,
            (playlist_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    conn.close()
    return rows


def _execute_smart_playlist(cur, smartlist_json: str) -> list[dict[str, Any]]:
    """Execute a Lexicon smart playlist definition as a SQL query."""
    import json

    try:
        sl = json.loads(smartlist_json)
    except (json.JSONDecodeError, TypeError):
        return []

    rules = sl.get("rules", [])
    if not rules:
        return []

    match_all = sl.get("matchAll", False)
    conditions = []
    params = []

    # Map Lexicon fields to Track table columns
    field_map = {
        "genre": "genre",
        "artist": "artist",
        "title": "title",
        "albumTitle": "albumTitle",
        "comment": "comment",
        "key": "key",
        "label": "label",
        "remixer": "remixer",
        "composer": "composer",
    }

    for rule in rules:
        field = rule.get("field", "")
        operator = rule.get("operator", "")
        values = rule.get("values", [])
        col = field_map.get(field)
        if not col:
            continue

        value = values[0] if values else None
        if value is None:
            continue

        if operator == "StringContains":
            conditions.append(f"{col} LIKE ?")
            params.append(f"%{value}%")
        elif operator == "StringEquals":
            conditions.append(f"{col} = ?")
            params.append(value)
        elif operator == "StringNotContains":
            conditions.append(f"{col} NOT LIKE ?")
            params.append(f"%{value}%")
        elif operator == "StringNotEquals":
            conditions.append(f"{col} != ?")
            params.append(value)

    if not conditions:
        return []

    joiner = " AND " if match_all else " OR "
    where = joiner.join(conditions)
    cur.execute(f"SELECT artist, title FROM Track WHERE {where} ORDER BY artist, title", params)
    return [dict(r) for r in cur.fetchall()]


def get_playlist_name(db_path: str, playlist_id: int) -> str | None:
    path = resolve_path(db_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT name FROM Playlist WHERE id = ?", (playlist_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None
