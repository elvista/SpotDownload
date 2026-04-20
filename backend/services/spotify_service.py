"""Shared Spotify search, matching, and playlist import service.

Used by Mixtape ID.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("cratedigger.spotify")

# ---------------------------------------------------------------------------
# Search / matching
# ---------------------------------------------------------------------------

_MATCH_THRESHOLD = 0.3
_rate_limited_until = 0.0  # timestamp when rate limit expires

# Patterns to strip from titles — DJ-specific suffixes that hurt Spotify search
_TITLE_NOISE = re.compile(
    r"\s*\("
    r"(?:Original|Extended|Radio|Club|Dub|Instrumental|Short|Full Length|Array)"
    r"(?:\s+(?:Mix|Edit|Version|Club Mix|Dub Mix))?"
    r"\)",
    re.IGNORECASE,
)
# Role annotations in artist fields (e.g., "- Vocals", "- Remix")
_ARTIST_ROLE = re.compile(r"\s*-\s*(?:Vocals?|Remix|Producer|DJ)\b.*", re.IGNORECASE)


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def _tokenize(s: str) -> set[str]:
    return set(_normalize(s).split())


def _token_overlap(a: str, b: str) -> float:
    """Ratio of shared tokens between two strings (0.0–1.0)."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _score_match(
    query_artist: str, query_title: str, result_artist: str, result_title: str
) -> float:
    """Score a Spotify result against the query (0.0–1.0). Higher is better."""
    title_score = _token_overlap(query_title, result_title)
    artist_score = _token_overlap(query_artist, result_artist)

    # If neither title nor artist tokens overlap at all, reject
    if title_score == 0.0 and artist_score == 0.0:
        return 0.0

    # Weight title more heavily (0.6 title, 0.4 artist)
    return title_score * 0.6 + artist_score * 0.4


def clean_for_search(artist: str, title: str) -> tuple[str, str]:
    """Strip DJ metadata that hurts Spotify search accuracy."""
    clean_title = _TITLE_NOISE.sub("", title).strip()
    parts = re.split(r"[,;/]", artist)
    cleaned_parts = [_ARTIST_ROLE.sub("", p).strip() for p in parts]
    clean_artist = " ".join(p for p in cleaned_parts if p)
    return clean_artist, clean_title


def _parse_track(track: dict) -> dict[str, str]:
    return {
        "uri": track["uri"],
        "name": track.get("name", ""),
        "artist": ", ".join(a["name"] for a in track.get("artists", [])),
        "spotifyUrl": (track.get("external_urls") or {}).get("spotify", ""),
    }


async def _spotify_search_best(
    query: str,
    query_artist: str,
    query_title: str,
    token: str,
    client: httpx.AsyncClient,
) -> dict[str, str] | None:
    """Search Spotify, fetch 5 candidates, return the best-scored match or None."""
    import asyncio as _aio
    import time as _time

    global _rate_limited_until
    if _time.time() < _rate_limited_until:
        return None

    for attempt in range(2):
        r = await client.get(
            "https://api.spotify.com/v1/search",
            params={"q": query, "type": "track", "limit": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code == 429:
            wait = int(r.headers.get("retry-after", "2"))
            if wait > 30:
                _rate_limited_until = _time.time() + wait
                logger.warning("Spotify rate limited for %ds — search disabled until reset", wait)
                return None
            await _aio.sleep(min(wait, 5))
            continue
        break
    if r.status_code != 200:
        return None
    items = (r.json().get("tracks") or {}).get("items") or []
    if not items:
        return None

    best_result = None
    best_score = 0.0
    for track in items:
        parsed = _parse_track(track)
        score = _score_match(query_artist, query_title, parsed["artist"], parsed["name"])
        if score > best_score:
            best_score = score
            best_result = parsed

    if best_score < _MATCH_THRESHOLD:
        return None
    return best_result


def _strip_all_parens(s: str) -> str:
    """Remove all parenthetical content: 'Hot Blooded (Remix) (Club Mix)' → 'Hot Blooded'."""
    return re.sub(r"\s*\([^)]*\)", "", s).strip()


async def search_spotify_track(
    artist: str, title: str, token: str
) -> dict[str, str] | None:
    """Multi-strategy Spotify search with candidate scoring.

    Phase 1: Try with full original title (preserves remix/edit info).
    Phase 2: Strip all parenthetical content and search for the base track.
    """
    if not artist and not title:
        return None

    clean_artist, _ = clean_for_search(artist, title)
    first_artist = re.split(r"[,;/&]", artist)[0].strip()
    first_artist_clean = _ARTIST_ROLE.sub("", first_artist).strip()

    orig_title = title.strip()
    base_title = _strip_all_parens(orig_title) or orig_title

    strategies: list[tuple[str, str, str]] = []  # (query, score_artist, score_title)

    # Phase 1: Search with FULL original title (specific remix/edit)
    strategies += [
        (f"artist:{clean_artist} track:{orig_title}", clean_artist, orig_title),
        (f"{clean_artist} {orig_title}", clean_artist, orig_title),
        (f"artist:{first_artist_clean} track:{orig_title}", first_artist_clean, orig_title),
    ]

    # Phase 2: Fall back to BASE title (all parentheticals stripped)
    if base_title != orig_title:
        strategies += [
            (f"artist:{clean_artist} track:{base_title}", clean_artist, base_title),
            (f"{clean_artist} {base_title}", clean_artist, base_title),
            (f"artist:{first_artist_clean} track:{base_title}", first_artist_clean, base_title),
            (f"track:{base_title}", "", base_title),
        ]

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[tuple[str, str, str]] = []
    for entry in strategies:
        if entry[0] not in seen:
            seen.add(entry[0])
            unique.append(entry)

    async with httpx.AsyncClient(timeout=15.0) as client:
        for query, score_artist, score_title in unique:
            result = await _spotify_search_best(
                query, score_artist, score_title, token, client
            )
            if result:
                return result

    return None


# ---------------------------------------------------------------------------
# Playlist helpers
# ---------------------------------------------------------------------------


async def find_existing_spotify_playlist(
    name: str, token: str
) -> dict[str, Any] | None:
    """Find a user's playlist by exact name match. Returns id, name, existingUris, url."""
    headers = {"Authorization": f"Bearer {token}"}
    offset = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            r = await client.get(
                "https://api.spotify.com/v1/me/playlists",
                params={"limit": 50, "offset": offset},
                headers=headers,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            for pl in data.get("items") or []:
                if pl.get("name") == name:
                    existing_uris = await _get_playlist_item_uris(client, pl["id"], headers)
                    return {
                        "id": pl["id"],
                        "name": pl["name"],
                        "existingUris": existing_uris,
                        "url": (pl.get("external_urls") or {}).get("spotify", ""),
                    }
            if not data.get("next"):
                break
            offset += 50
    return None


async def _get_playlist_item_uris(
    client: httpx.AsyncClient, playlist_id: str, headers: dict
) -> set[str]:
    uris: set[str] = set()
    offset = 0
    while True:
        r = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
            params={"limit": 100, "offset": offset, "fields": "items(item(uri)),next"},
            headers=headers,
        )
        if r.status_code != 200:
            break
        data = r.json()
        for item in data.get("items") or []:
            track = item.get("item") or item.get("track")
            if track and track.get("uri"):
                uris.add(track["uri"])
        if not data.get("next"):
            break
        offset += 100
    return uris


# ---------------------------------------------------------------------------
# Create / update playlist and add tracks
# ---------------------------------------------------------------------------


async def create_or_update_spotify_playlist(
    playlist_name: str,
    uris: list[str],
    token: str,
    description: str = "",
    update_existing: bool = True,
) -> dict[str, Any]:
    """Create a Spotify playlist (or update if it exists) and add tracks.

    Returns dict with playlistUrl, playlistId, added, mode.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    existing = await find_existing_spotify_playlist(playlist_name, token) if update_existing else None
    mode = "update" if existing else "create"

    async with httpx.AsyncClient(timeout=60.0) as client:
        if existing:
            playlist_id = existing["id"]
            playlist_url = existing["url"]
            new_uris = [u for u in uris if u not in existing["existingUris"]]
        else:
            if not description:
                description = f"Created by CrateDigger — {datetime.now().strftime('%Y-%m-%d')}"
            cr = await client.post(
                "https://api.spotify.com/v1/me/playlists",
                json={"name": playlist_name, "description": description, "public": False},
                headers=headers,
            )
            if cr.status_code not in (200, 201):
                return {"error": f"Failed to create playlist: {cr.text}", "added": 0, "mode": mode}
            pdata = cr.json()
            playlist_id = pdata["id"]
            playlist_url = (pdata.get("external_urls") or {}).get("spotify", "")
            new_uris = uris

        added = 0
        for i in range(0, len(new_uris), 100):
            chunk = new_uris[i : i + 100]
            ar = await client.post(
                f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
                json={"uris": chunk},
                headers=headers,
            )
            if ar.status_code in (200, 201):
                added += len(chunk)

    return {
        "playlistId": playlist_id,
        "playlistUrl": playlist_url,
        "added": added,
        "mode": mode,
    }


async def import_playlist_to_spotify(
    playlist_name: str,
    tracks: list[dict[str, str]],
    token: str,
    send_event,
    description: str = "",
    update_existing: bool = True,
) -> dict[str, Any]:
    """Match tracks by artist+title, then create/update a Spotify playlist.

    Streams progress via send_event callback (SSE).
    """
    total = len(tracks)
    matched_uris: list[str] = []
    not_matched: list[dict[str, str]] = []

    for i, track in enumerate(tracks):
        artist = track.get("artist", "")
        title = track.get("title", "")
        await send_event({
            "type": "matching",
            "current": i + 1,
            "total": total,
            "artist": artist,
            "title": title,
        })

        result = await search_spotify_track(artist, title, token)
        if result:
            matched_uris.append(result["uri"])
            await send_event({
                "type": "matched",
                "current": i + 1,
                "total": total,
                "artist": artist,
                "title": title,
                "status": "found",
                "spotifyTrack": f"{result['artist']} - {result['name']}",
            })
        else:
            not_matched.append({"artist": artist, "title": title})
            await send_event({
                "type": "matched",
                "current": i + 1,
                "total": total,
                "artist": artist,
                "title": title,
                "status": "not_found",
            })

    if not matched_uris:
        import time as _t
        if _t.time() < _rate_limited_until:
            await send_event({"type": "error", "error": "Spotify API rate limit active. Please try again later."})
        else:
            await send_event({"type": "error", "error": "No tracks could be matched on Spotify."})
        return {"matched": 0, "notMatched": total, "added": 0}

    await send_event({"type": "creating_playlist", "name": playlist_name, "mode": "create"})

    result = await create_or_update_spotify_playlist(
        playlist_name, matched_uris, token,
        description=description, update_existing=update_existing,
    )

    if result.get("error"):
        await send_event({"type": "error", "error": result["error"]})
        return {"matched": len(matched_uris), "notMatched": len(not_matched), "added": 0}

    await send_event({
        "type": "complete",
        "playlistUrl": result["playlistUrl"],
        "matched": len(matched_uris),
        "notMatched": len(not_matched),
        "added": result["added"],
        "mode": result["mode"],
    })

    return {
        "playlistUrl": result["playlistUrl"],
        "matched": len(matched_uris),
        "notMatched": len(not_matched),
        "added": result["added"],
        "mode": result["mode"],
    }
