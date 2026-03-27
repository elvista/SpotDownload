# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Music Studio** is a self-hosted web app with two areas in one React shell:

1. **Spotify ID (SpotDownload)** — Monitors Spotify playlists and downloads new tracks (Python FastAPI, SQLite, SSE).
2. **Mixtape ID** — Fingerprints long mixes (upload or YouTube / SoundCloud / Mixcloud) and builds a timestamped track list (FastAPI routes at `/api/mixtape`, ACRCloud / AudD, SSE).

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
- **Routers**: playlists, downloads, monitor, settings, auth, export_import, **mixtape** — under `/api`
- **Key services**: `spotify.py`, `downloader.py`, `monitor.py`, `sync_ops.py`, **`audio_processor.py`**, **`fingerprinter.py`**, **`mixtape_processor.py`**
- **Config**: `backend/config.py` loads **repo-root** `.env` (`Path(backend).parent.parent / ".env"`)

### Spotify ID downloads (by design)

`downloader.py` resolves audio via **YouTube search** (`ytsearch1`), then applies **Spotify** metadata to the file. **Wrong-video matches are possible**; there is **no** built-in acoustic or metadata verification. Reliable auto-verification is **hard for indie/niche** tracks, so this limitation is **documented in README** and treated as an **intentional non-goal** — not a pending bugfix. Progress payloads expose `source_title` / `source_url` for manual checks.

### Frontend (React 18 + Vite + TailwindCSS)

- **Entry**: `frontend/src/main.jsx` — `BrowserRouter`, `HeaderProvider`, `App`
- **Routes** (`frontend/src/App.jsx`): `/` → `SpotDownloadView`, `/mixtape` → `MixtapeView`
- **Layout**: `frontend/src/components/Layout.jsx` — **Music Studio** branding, nav **Spotify ID** / **Mixtape ID**, settings hidden on `/mixtape`
- **Header go-home**: `frontend/src/context/HeaderContext.jsx` — playlist detail view registers “back” for the header
- **API client**: `frontend/src/api/client.js` — SpotDownload REST
- **SSE**: `hooks/useSSE.js` — download progress; Mixtape uses `EventSource` on `/api/mixtape/stream/:id` inside `MixtapeView`

### Vite dev proxy (`frontend/vite.config.js`)

- `/api` → `http://localhost:8000` (FastAPI — includes `/api/mixtape`)

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

**Spotify ID OAuth** (`routers/auth.py`): Authorization Code **with PKCE** (`code_challenge` / `code_verifier`); token exchange posts `client_id` and `code_verifier` only (no `client_secret` in that request, per Spotify’s PKCE tutorial).

**Shared optional**

- `DOWNLOAD_PATH`, `MONITOR_INTERVAL_MINUTES`, `ENCRYPTION_KEY`

## Code Style

- **Python**: ruff, line-length 100, Python 3.11 (`backend/ruff.toml`)
- **JavaScript**: ESLint (`frontend/eslint.config.js`) with `globals` for browser APIs
- **CSS**: TailwindCSS, dark theme default
