# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CrateDigger** is a self-hosted web app with three sections in one React shell:

1. **Spotify ID** — Monitors Spotify playlists and downloads new tracks (Python FastAPI, SQLite, SSE).
2. **Mixtape ID** — Fingerprints long mixes (upload or YouTube / SoundCloud / Mixcloud) and builds a timestamped track list (FastAPI routes at `/api/mixtape`, ACRCloud / AudD, SSE).
3. **Lexicon ID** — Reads a local Lexicon DJ library (SQLite, read-only) and imports playlists to Spotify with intelligent track matching.

Single **FastAPI** backend on **:8000**, shared **repo-root `.env`**, Vite on **:5173** proxying **`/api` → FastAPI**.

## Development Commands

### All services (repo root)

```bash
npm install          # installs concurrently
npm run dev          # FastAPI :8000 + Vite :5173 (see package.json scripts)
```

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

**Mixtape ID** requires **FFmpeg** and **yt-dlp** on `PATH` (same as before the Node merge).

### Frontend (from `frontend/`)

```bash
npm run dev          # Dev server on :5173
npm run test         # Watch mode tests (vitest)
npm run test:run     # Single test run
npm run lint         # ESLint check
npm run lint:fix     # ESLint auto-fix
npm run build        # Production build
```

### Pre-commit hooks

```bash
pre-commit run --all-files   # Runs ruff (backend) + eslint (frontend)
```

## Architecture

### Backend (FastAPI, async)

- **Entry point**: `backend/main.py` — app init, lifespan (DB init, dirs, APScheduler start), CORS, router registration
- **3-layer pattern**: `routers/` → `services/` → `models.py` + `database.py`
- **Routers**: playlists, downloads, monitor, settings, auth, export_import, **mixtape**, **lexicon** — under `/api`
- **Key services**: `spotify.py`, `downloader.py`, `monitor.py`, `sync_ops.py`, **`audio_processor.py`**, **`fingerprinter.py`**, **`mixtape_processor.py`**, **`spotify_service.py`** (shared Spotify search/matching/playlist import), **`lexicon_service.py`** (Lexicon DJ DB reader)
- **Config**: `backend/config.py` loads **repo-root** `.env` (`Path(backend).parent.parent / ".env"`)

### Spotify ID downloads (by design)

`downloader.py` resolves audio via **YouTube search** (`ytsearch1`), then applies **Spotify** metadata to the file. **Wrong-video matches are possible**; there is **no** built-in acoustic or metadata verification. Reliable auto-verification is **hard for indie/niche** tracks, so this limitation is **documented in README** and treated as an **intentional non-goal** — not a pending bugfix. Progress payloads expose `source_title` / `source_url` for manual checks.

### Lexicon ID

`lexicon_service.py` reads the Lexicon DJ SQLite database in **read-only mode** (`?mode=ro`). Playlists form a tree via `parentId` (type 1 = folder, 2 = playlist, 3 = smart list). Import to Spotify uses the shared `spotify_service.py`.

### Shared Spotify Import (`spotify_service.py`)

Used by both Mixtape ID and Lexicon ID. Multi-strategy search with candidate scoring:
1. Tries the **specific version** first (with remix/edit info in title).
2. Falls back to the **base track** (all parentheticals stripped) only if the specific version isn't on Spotify.
3. Fetches 5 candidates per search and scores by artist + title token overlap; rejects mismatches below threshold.
4. Uses Spotify's Feb 2026 `/items` endpoint (not the deprecated `/tracks`).

### Frontend (React 18 + Vite + TailwindCSS)

- **Entry**: `frontend/src/main.jsx` — `BrowserRouter`, `HeaderProvider`, `App`
- **Routes** (`frontend/src/App.jsx`): `/` → `SpotDownloadView`, `/mixtape` → `MixtapeView`, `/lexicon` → `LexiconView`
- **Layout**: `frontend/src/components/Layout.jsx` — **CrateDigger** branding, nav **Spotify ID** / **Mixtape ID** / **Lexicon ID**, settings gear on all pages, dynamic Spotify connection indicator
- **Header go-home**: `frontend/src/context/HeaderContext.jsx` — playlist detail view registers "back" for the header
- **API client**: `frontend/src/api/client.js` — CrateDigger REST
- **SSE**: `hooks/useSSE.js` — download progress; Mixtape uses `EventSource` on `/api/mixtape/stream/:id` inside `MixtapeView`; Lexicon uses `EventSource` on `/api/lexicon/import-stream/:id` inside `LexiconView`
- **Components**: `PlaylistTree.jsx` — recursive tree for Lexicon playlist sidebar

### Vite dev proxy (`frontend/vite.config.js`)

- `/api` → `http://localhost:8000` (FastAPI — includes `/api/mixtape` and `/api/lexicon`)

### Production hosting

Serve `frontend/dist` as static files. Reverse-proxy **`/api`** → FastAPI.

### Database (SQLite + SQLAlchemy + Alembic)

- **Playlist**, **Track**, **AppSetting** (includes optional `mixtape_spotify_refresh_token` for Mixtape playlist OAuth)
- Migrations in `backend/alembic/`

## Environment Variables

Single **`.env` at the repository root** (see `.env.example`).

**Spotify (shared)**

- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI` (default **`http://127.0.0.1:8000/api/auth/spotify/callback`** — Spotify rejects `localhost`)
- `FRONTEND_ORIGIN` (optional) — browser redirect after Spotify ID OAuth callback (default `http://localhost:5173`)

**Mixtape fingerprinting**

- `ACRCLOUD_ACCESS_KEY`, `ACRCLOUD_ACCESS_SECRET`, `ACRCLOUD_HOST`, `AUDD_API_TOKEN`

**Mixtape Spotify playlist export**

- **Default:** `fingerprinter.get_spotify_refresh_token()` uses **`spotify_refresh_token`** from the DB (Spotify ID Settings connect) first, then `mixtape_spotify_refresh_token`, then env / cache file — one Settings login covers Mixtape playlists.
- `SPOTIFY_REFRESH_TOKEN` (optional env override), or Mixtape-only `/api/mixtape/spotify/login` if the user never connects via Settings.
- `SPOTIFY_REDIRECT_URI_MIXID` if the default **`http://127.0.0.1:8000/api/mixtape/spotify/callback`** does not match your deployment (Mixtape-only flow only).

Register **both** Spotify redirect URIs in the Spotify Developer Dashboard if you use Mixtape-only login; Settings-only users still need the main **`/api/auth/spotify/callback`** URI.

**Spotify ID OAuth** (`routers/auth.py`): Authorization Code **with PKCE** (`code_challenge` / `code_verifier`); token exchange posts `client_id`, `code_verifier`, AND `client_secret` via `Authorization: Basic` header. PKCE state is stored in a **file** (`cache/pkce-states.json`), not in-memory, so it survives server restarts/auto-reload. Auth popup uses `show_dialog=true` to force re-consent.

**Spotify API (Feb 2026)**: Playlist item endpoints were renamed from `/tracks` to `/items` (e.g., `POST /playlists/{id}/items`). The old `/tracks` endpoints return 403 for Development Mode apps. All code uses the new `/items` endpoints.

**Shared optional**

- `DOWNLOAD_PATH`, `MONITOR_INTERVAL_MINUTES`, `ENCRYPTION_KEY`

## Code Style

- **Python**: ruff, line-length 100, Python 3.11 (`backend/ruff.toml`)
- **JavaScript**: ESLint (`frontend/eslint.config.js`) with `globals` for browser APIs
- **CSS**: TailwindCSS, dark theme default
