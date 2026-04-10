"""Genre ID service: scan Lexicon DB for empty genres, classify via Last.fm."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import requests

from config import settings

logger = logging.getLogger("cratedigger.genreid")

DEFAULT_LEXICON_DB = str(Path.home() / "Library" / "Application Support" / "Lexicon" / "main.db")



def get_lexicon_db_path() -> str:
    """Return configured or default Lexicon DB path."""
    from database import SessionLocal
    from models import AppSetting

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "lexicon_db_path").first()
        if row and row.value:
            return row.value
    finally:
        db.close()
    return DEFAULT_LEXICON_DB


def set_lexicon_db_path(path: str) -> None:
    from database import SessionLocal
    from models import AppSetting

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == "lexicon_db_path").first()
        if row:
            row.value = path
        else:
            db.add(AppSetting(key="lexicon_db_path", value=path))
        db.commit()
    finally:
        db.close()


def validate_lexicon_db(path: str) -> dict[str, Any]:
    """Check if the Lexicon DB exists and has the Track table."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"valid": False, "error": f"File not found: {p}"}
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Track'")
        if not cur.fetchone():
            conn.close()
            return {"valid": False, "error": "Not a valid Lexicon database (no Track table)"}
        cur.execute("SELECT COUNT(*) FROM Track")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM Track WHERE genre = '' OR genre IS NULL")
        empty = cur.fetchone()[0]
        conn.close()
        return {"valid": True, "path": str(p), "totalTracks": total, "emptyGenres": empty}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def fetch_all_tracks(
    path: str,
    search: str = "",
    page: int = 1,
    page_size: int = 50,
    filter_type: str = "all",
) -> dict[str, Any]:
    """Paginated read-only query for Lexicon tracks."""
    p = Path(path).expanduser()
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    where_clauses = []
    params: list[Any] = []

    if filter_type == "empty":
        where_clauses.append("(genre = '' OR genre IS NULL)")

    if search.strip():
        where_clauses.append("(artist LIKE ? OR title LIKE ?)")
        q = f"%{search.strip()}%"
        params.extend([q, q])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    cur.execute(f"SELECT COUNT(*) FROM Track {where_sql}", params)
    total = cur.fetchone()[0]

    offset = (page - 1) * page_size
    cur.execute(
        f"""
        SELECT id, title, artist, remixer, key, genre
        FROM Track
        {where_sql}
        ORDER BY artist, title
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"tracks": rows, "total": total, "page": page, "pageSize": page_size}


def fetch_empty_genre_tracks(path: str) -> list[dict[str, Any]]:
    """Read-only query for tracks with empty genre."""
    p = Path(path).expanduser()
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, artist, remixer, key, comment
        FROM Track
        WHERE genre = '' OR genre IS NULL
        ORDER BY artist, title
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_all_library_tracks(path: str) -> list[dict[str, Any]]:
    """Read-only query for ALL tracks in the library (for rescan)."""
    p = Path(path).expanduser()
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, artist, remixer, key, comment
        FROM Track
        ORDER BY artist, title
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

# Tags that are too generic to be useful as genres
LASTFM_IGNORED_TAGS = {
    "seen live", "favorites", "favourite", "love", "loved",
    "beautiful", "awesome", "cool", "good", "great", "amazing",
    "under 2000 listeners", "spotify", "female vocalists", "male vocalists",
    "remix", "cover", "live", "instrumental", "classic",
}

# Broad parent genres — skip these if a more specific subgenre exists
LASTFM_BROAD_TAGS = {
    "electronic", "dance", "house", "techno", "hip-hop", "hip hop",
    "rap", "pop", "rock", "r&b", "rnb", "soul", "jazz", "reggae",
    "metal", "punk", "folk", "country", "blues", "classical",
    "ambient", "trance", "bass", "experimental", "indie",
}

# Parenthetical suffixes that don't help Last.fm matching
import re

_STRIP_SUFFIXES_RE = re.compile(
    r"\s*\("
    r"(?:original mix|extended mix|radio edit|club mix|extended|"
    r"radio|instrumental mix|instrumental|dub mix|dub|vocal mix|"
    r"vip mix|vip|remaster(?:ed)?|bonus track)"
    r"\)\s*$",
    re.IGNORECASE,
)
_STRIP_ALL_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*")


def _extract_genre_from_tags(tags: list[dict]) -> str | None:
    """Pick the most specific genre tag from a Last.fm tag list.

    Prefers specific subgenres (e.g. 'Afro House') over broad parents ('House').
    Falls back to a broad genre only if no specific one is found.
    """
    broad_fallback = None
    for tag in tags:
        name = tag.get("name", "").strip()
        count = int(tag.get("count", 0))
        if count < 5:
            continue
        if name.lower() in LASTFM_IGNORED_TAGS:
            continue
        if len(name) < 2:
            continue
        if name.lower() in LASTFM_BROAD_TAGS:
            if broad_fallback is None:
                broad_fallback = name.title()
            continue
        # Found a specific subgenre — use it
        return name.title()
    # No specific subgenre found, use the broad one
    return broad_fallback


def _lastfm_track_tags(artist: str, title: str) -> str | None:
    """Call Last.fm track.getTopTags and extract genre."""
    resp = requests.get(
        LASTFM_API_URL,
        params={
            "method": "track.getTopTags",
            "api_key": settings.LASTFM_API_KEY,
            "artist": artist,
            "track": title,
            "format": "json",
        },
        timeout=5,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    tags = data.get("toptags", {}).get("tag", [])
    return _extract_genre_from_tags(tags)


def _lastfm_artist_tags(artist: str) -> str | None:
    """Call Last.fm artist.getTopTags and extract genre."""
    resp = requests.get(
        LASTFM_API_URL,
        params={
            "method": "artist.getTopTags",
            "api_key": settings.LASTFM_API_KEY,
            "artist": artist,
            "format": "json",
        },
        timeout=5,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    tags = data.get("toptags", {}).get("tag", [])
    return _extract_genre_from_tags(tags)


def lookup_genre_lastfm(artist: str, title: str) -> str | None:
    """Multi-step Last.fm genre lookup. Returns genre string or None."""
    if not settings.LASTFM_API_KEY:
        return None
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist:
        return None

    try:
        if title:
            # Step 1: Clean common suffixes and try exact match
            clean_title = _STRIP_SUFFIXES_RE.sub("", title).strip()
            result = _lastfm_track_tags(artist, clean_title)
            if result:
                return result

            # Step 2: Strip ALL parentheticals (remix info etc.) and retry
            stripped = _STRIP_ALL_PARENS_RE.sub("", title).strip()
            if stripped and stripped != clean_title:
                result = _lastfm_track_tags(artist, stripped)
                if result:
                    return result

        # Step 3: Fall back to artist top tags
        result = _lastfm_artist_tags(artist)
        if result:
            return result

    except Exception as e:
        logger.debug("Last.fm lookup failed for %s - %s: %s", artist, title, e)
    return None


def export_genres_to_lexicon(
    staged_tracks: list[dict[str, Any]], lexicon_db_path: str
) -> int:
    """Write approved genres to the Lexicon DB. Returns count of updated rows."""
    p = Path(lexicon_db_path).expanduser()
    conn = sqlite3.connect(str(p))
    cur = conn.cursor()
    updated = 0
    for t in staged_tracks:
        cur.execute(
            "UPDATE Track SET genre = ? WHERE id = ?",
            (t["suggested_genre"], t["lexicon_track_id"]),
        )
        updated += cur.rowcount
    conn.commit()
    conn.close()
    return updated
