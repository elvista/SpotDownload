# CrateDigger — product notes

**CrateDigger** is a self-hosted app that combines:

1. **Spotify ID** — Track Spotify playlists, diff new tracks, download audio locally using **yt-dlp** and **ffmpeg**, with metadata from Spotify.
2. **Mixtape ID** — Analyze long mixes (file or streaming URL), fingerprint samples via **ACRCloud** / **AudD**, produce a timestamped list, and optionally push tracks through the same download path or to a Spotify playlist.
3. **Lexicon ID** — Read your local **Lexicon DJ** library, browse playlists, and import them to Spotify with intelligent track matching that prefers specific remixes/edits when available.

Everything runs locally: **FastAPI** + **SQLite** + **React (Vite)**. One **repo-root `.env`** configures Spotify, fingerprinting, and paths.

**Spotify OAuth redirect:** use **`http://127.0.0.1:8000/...`** in the Developer Dashboard, not `localhost` (Spotify treats `localhost` as insecure for redirect URIs).

**Spotify Import to Spotify** (Mixtape ID and Lexicon ID) reuses the same user session as **Spotify ID → Settings** (one browser connect). Both features share a common import engine (`spotify_service.py`) with multi-strategy search and candidate scoring.

**Spotify ID downloads:** audio comes from **YouTube search**, tags from **Spotify** — the two can disagree (wrong upload, cover, live version; worse odds for **indie** tracks). The app does **not** try to verify the match automatically; that is **by design** (no easy robust solution). See **README → Known limitation** and use **source link / title** in the download UI when in doubt.

**Lexicon ID** reads the Lexicon DJ SQLite database in **read-only mode** — it never modifies your library. The database path is configurable in the Lexicon ID UI (default: `~/Library/Application Support/Lexicon/main.db`).

## Spotify ID — adding non-owned public playlists

CrateDigger supports adding any public Spotify playlist, including ones you don't own. This works around a Spotify **Developer Mode** restriction (Feb 2026) that blocks third-party apps from reading tracks of non-owned playlists — even public ones — via the Web API:

- `GET /playlists/{id}` returns metadata only, with no `tracks` field
- `GET /playlists/{id}/items` and `/tracks` both return **403 Forbidden**

When the API blocks track access, CrateDigger falls back to parsing the **public Spotify embed page** (`open.spotify.com/embed/playlist/{id}`), which inlines a JSON payload with track info. This is the same page that powers the shareable Spotify widget, so no authenticated or undocumented endpoints are involved.

**Limitations of the embed fallback** (only triggered for non-owned playlists):

- **Capped at 100 tracks** — the embed only inlines the first 100; there is no pagination mechanism.
- **Album name unavailable** — stored as empty string.
- **Per-track artwork** falls back to the playlist cover.
- **No artist genre lookup** — artist IDs are not exposed via the embed.

Playlists you own (or collaborate on) are fetched through the full Web API and have none of these limitations.

**Workarounds for > 100 tracks on non-owned playlists:** duplicate the playlist to your own Spotify account first (right-click → "Add to Other Playlist" → "New Playlist"), then add that URL. Or apply for Spotify Extended Quota mode to lift Dev Mode restrictions on your developer app.

## Where to read more

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Setup, env vars, troubleshooting, quick start with `npm run dev` |
| [CLAUDE.md](CLAUDE.md) | Architecture, routers, services, dev commands for contributors and tooling |

For API behavior and endpoints, use the interactive OpenAPI UI at `/docs` when the server is running.

## Historical note

Earlier long-form architecture write-ups targeted the Spotify-only stack before **Mixtape ID** lived in the same FastAPI app. The **README** and **CLAUDE.md** above are the maintained sources of truth.
