# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CrateDigger** is a self-hosted web app with three sections in one React shell:

1. **Spotify ID** — Monitors Spotify playlists and downloads new tracks (Python FastAPI, SQLite, SSE).
2. **Mixtape ID** — Fingerprints long mixes (upload or YouTube / SoundCloud / Mixcloud) and builds a timestamped track list (FastAPI routes at `/api/mixtape`, ACRCloud / AudD, SSE).
3. **Genre ID** — Scans a local Lexicon DJ library (SQLite) for tracks with empty `genre` fields, classifies via Last.fm, stages suggestions, and writes approved genres back to Lexicon (`/api/genreid`, SSE).

Single **FastAPI** backend serving both API and built frontend bundle. Two run modes:

- **Dev** (`npm run dev`): Vite `:5173` + FastAPI `:8000`, Vite proxies `/api` to FastAPI.
- **Always-on** (macOS launchd): FastAPI `:5174` serves API and `frontend/dist/` same-origin.

One repo-root `.env`. One Spotify OAuth (Spotify ID Settings) covers every feature that needs Spotify.

## Development Commands

### All services (repo root)

```bash
npm install          # installs concurrently
npm run dev          # FastAPI :8000 + Vite :5173 (see package.json scripts)
```

### Always-on deploy (macOS)

```bash
./scripts/install-service.sh     # Build frontend, install + load launchd agent on :5174
./scripts/rebuild.sh             # Rebuild frontend + restart backend after a code change
./scripts/uninstall-service.sh   # Remove the launchd agent
tail -f ~/Library/Logs/cratedigger/stderr.log
```

Plist source: [scripts/com.cratedigger.plist](scripts/com.cratedigger.plist). See [Documentation.md](Documentation.md#operational-commands-mac) for full details.

### Backend — FastAPI (from `backend/`)

```bash
source venv/bin/activate
uvicorn main:app --reload                # Dev server on :8000
pytest tests/ -v                         # Run tests
pytest tests/test_file.py::test_name -v  # Single test
ruff check .                             # Lint
ruff format .                            # Format
alembic upgrade head                     # Apply migrations
alembic revision --autogenerate -m "msg" # Create migration
```

**Mixtape ID** requires **FFmpeg** and **yt-dlp** on `PATH`.

### Frontend (from `frontend/`)

```bash
npm run dev          # Dev server on :5173
npm run test         # Watch mode tests (vitest)
npm run test:run     # Single test run
npm run lint         # ESLint check
npm run lint:fix     # ESLint auto-fix
npm run build        # Production build → frontend/dist/ (served by FastAPI in always-on mode)
```

### Pre-commit hooks

```bash
pre-commit run --all-files   # Runs ruff (backend) + eslint (frontend)
```

## Architecture

### Backend (FastAPI, async)

- **Entry point**: `backend/main.py` — app init, lifespan (DB init, dirs, APScheduler start), CORS, router registration, static mount of `frontend/dist/` with SPA fallback at the bottom of the route table.
- **3-layer pattern**: `routers/` → `services/` → `models.py` + `database.py`
- **Routers**: `playlists`, `downloads`, `monitor`, `settings`, `auth`, `export_import`, **`mixtape`**, **`genreid`** — all mounted under `/api`
- **Key services**: `spotify.py`, `downloader.py`, `monitor.py`, `sync_ops.py`, **`audio_processor.py`**, **`fingerprinter.py`**, **`mixtape_processor.py`**, **`spotify_service.py`** (shared Spotify search/matching/playlist import used by Mixtape ID), **`genreid_service.py`** (Lexicon DB reader + Last.fm lookups + writeback)
- **Config**: `backend/config.py` loads **repo-root** `.env` (`Path(backend).parent.parent / ".env"`)

### Spotify ID downloads (by design)

`downloader.py` resolves audio via **YouTube search** (`ytsearch1`), then applies **Spotify** metadata to the file. **Wrong-video matches are possible**; there is **no** built-in acoustic or metadata verification. Reliable auto-verification is **hard for indie/niche** tracks, so this limitation is **documented in README** and treated as an **intentional non-goal** — not a pending bugfix. Progress payloads expose `source_title` / `source_url` for manual checks.

### Genre ID

`genreid_service.py` reads the Lexicon DJ SQLite DB in **read-only mode** (`?mode=ro`) during scan (listing tracks, filtering by empty `genre`). Export opens the same file read/write and runs `UPDATE Track SET genre = ? WHERE id = ?` — **only the `genre` column is written**. No other Lexicon fields are touched.

Lookup flow (per track): Last.fm track tags (title-cleaned) → Last.fm track tags (parentheticals stripped) → Last.fm artist top tags. Requires `LASTFM_API_KEY`. `ANTHROPIC_API_KEY` is declared in config but not currently used by this service — the Last.fm-only flow is intentional.

### Shared Spotify Import (`spotify_service.py`)

Used by Mixtape ID. Multi-strategy search with candidate scoring:
1. Tries the **specific version** first (with remix/edit info in title).
2. Falls back to the **base track** (all parentheticals stripped) only if the specific version isn't on Spotify.
3. Fetches 5 candidates per search and scores by artist + title token overlap; rejects mismatches below threshold.
4. Uses Spotify's Feb 2026 `/items` endpoint (not the deprecated `/tracks`).

### Frontend (React 18 + Vite + TailwindCSS)

- **Entry**: `frontend/src/main.jsx` — `BrowserRouter`, `HeaderProvider`, `App`
- **Routes** (`frontend/src/App.jsx`): `/` → `SpotDownloadView`, `/mixtape` → `MixtapeView`, `/genreid` → `GenreIDView`
- **Layout**: `frontend/src/components/Layout.jsx` — **CrateDigger** branding, nav **Spotify ID** / **Mixtape ID** / **Genre ID**, settings gear on all pages, dynamic Spotify connection indicator
- **Header go-home**: `frontend/src/context/HeaderContext.jsx` — detail views register "back" for the header
- **API client**: `frontend/src/api/client.js` — CrateDigger REST (relative `/api` base URL, same-origin for both dev and prod)
- **SSE**: `hooks/useSSE.js` — download progress; Mixtape uses `EventSource` on `/api/mixtape/stream/:id`; Genre ID uses `EventSource` on `/api/genreid/stream/:id`

### Vite dev proxy (`frontend/vite.config.js`)

- `/api` → `http://localhost:8000` (dev mode only)

### Production/always-on hosting

FastAPI mounts `frontend/dist/assets` as static files and adds a catch-all SPA fallback to serve `index.html` for any non-`/api` route (see the tail of `backend/main.py`). The launchd agent at [scripts/com.cratedigger.plist](scripts/com.cratedigger.plist) runs uvicorn on `0.0.0.0:5174`.

### Database (SQLite + SQLAlchemy + Alembic)

- **Playlist**, **Track**, **AppSetting**, **StagedGenre** (Genre ID review queue)
- Migrations in `backend/alembic/`

## Environment Variables

Single **`.env` at the repository root** (see `.env.example`).

**Spotify (shared)**

- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`. Spotify rejects `localhost`; use `127.0.0.1`. Always-on default: `http://127.0.0.1:5174/api/auth/spotify/callback`. Dev: `http://127.0.0.1:8000/api/auth/spotify/callback`.
- `FRONTEND_ORIGIN` — where browser is sent after Spotify ID OAuth callback. Always-on: `http://127.0.0.1:5174`. Dev: `http://localhost:5173`.

**Mixtape fingerprinting**

- `ACRCLOUD_ACCESS_KEY`, `ACRCLOUD_ACCESS_SECRET`, `ACRCLOUD_HOST`, `AUDD_API_TOKEN`

**Mixtape Spotify playlist export**

- Reuses the `spotify_refresh_token` from the DB (written by the Spotify ID Settings OAuth flow). **No separate Mixtape OAuth.**
- `SPOTIFY_REFRESH_TOKEN` (optional env override) if the user never connects via Settings.

**Genre ID**

- `LASTFM_API_KEY` — required. Free at <https://www.last.fm/api/account/create>.

**Spotify ID OAuth** (`routers/auth.py`): Authorization Code **with PKCE** (`code_challenge` / `code_verifier`); token exchange posts `client_id`, `code_verifier`, AND `client_secret` via `Authorization: Basic` header. PKCE state is stored in a **file** (`cache/pkce-states.json`), not in-memory, so it survives server restarts/auto-reload. Auth popup uses `show_dialog=true` to force re-consent.

**Spotify API (Feb 2026)**: Playlist item endpoints were renamed from `/tracks` to `/items` (e.g., `POST /playlists/{id}/items`). The old `/tracks` endpoints return 403 for Development Mode apps. All code uses the new `/items` endpoints.

**Shared optional**

- `DOWNLOAD_PATH`, `MONITOR_INTERVAL_MINUTES`, `DOWNLOAD_CONCURRENCY`, `ENCRYPTION_KEY`

## Code Style

- **Python**: ruff, line-length 100, Python 3.11 (`backend/ruff.toml`)
- **JavaScript**: ESLint (`frontend/eslint.config.js`) with `globals` for browser APIs
- **CSS**: TailwindCSS, dark theme default
