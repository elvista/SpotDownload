# CrateDigger

**Your personal vinyl shop for the digital age.**

Vibecoded by Elius (https://hmelius.com)

---

You know that feeling — you're three hours deep in a DJ set on YouTube, you hear a track that stops you mid-scroll, and you *need* it. Or you've got a Spotify playlist that's become your lifeline and you want those files on your drive, tagged properly, no questions asked. Or maybe someone sends you a two-hour mixtape and you want to know every single track in it, timestamped, ready to save.

**CrateDigger** is a self-hosted web app for music obsessives who want to own their listening, not just stream it. Two tools, one app:

### Spotify ID — Your playlist, your files

Point it at any Spotify playlist. CrateDigger monitors it for new additions, downloads audio via **yt-dlp**, and writes clean **ID3 tags from Spotify** — artist, title, album art, the works. Set it and forget it: new tracks get pulled automatically on a schedule. It's your music library on autopilot.

### Mixtape ID — Crack open any mix

Paste a YouTube, SoundCloud, or Mixcloud URL (or upload a file directly). CrateDigger chops the mix into segments, fingerprints each one through **ACRCloud** and **AudD**, and hands you a **timestamped tracklist**. From there, download individual tracks or **export the whole list straight to a Spotify playlist** with one click.

---

No cloud accounts, no subscriptions, no data leaving your machine. Everything runs locally: **FastAPI + SQLite + React**.

**Stack:** FastAPI + SQLite on **:8000**, Vite on **:5173**, single repo-root **`.env`**.

## Quick start (recommended)

From the **repository root** (where `package.json` lives):

```bash
cp .env.example .env
# Edit .env: Spotify credentials; for Mixtape ID add ACRCloud (and optionally AudD). See .env.example.

npm install
npm run dev
```

This runs **uvicorn** (`:8000`) and **Vite** (`:5173`) together. Open **http://localhost:5173**. The dev server proxies **`/api`** to FastAPI.

API docs: **http://localhost:8000/docs**

### Alternative: run backend and frontend separately

```bash
cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

## Environment (repo-root `.env`)

- **Spotify** — `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI` (default **`http://127.0.0.1:8000/api/auth/spotify/callback`** — not `localhost`; [Spotify requires loopback as an IP](https://developer.spotify.com/documentation/web-api/tutorials/migration-insecure-redirect-uri)). Register that exact URI in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Spotify ID login uses **Authorization Code + PKCE** (required by current Spotify rules). Optional: `FRONTEND_ORIGIN` if the post-login redirect should not be `http://localhost:5173`.
- **Mixtape → Spotify playlists** — If you already connect Spotify under **Settings** on Spotify ID, no second login is needed. Register a **second redirect URI** only if you use the optional Mixtape-only login: `http://127.0.0.1:8000/api/mixtape/spotify/callback` (see `SPOTIFY_REDIRECT_URI_MIXID` in `.env.example`).
- **Mixtape fingerprinting** — `ACRCLOUD_HOST`, `ACRCLOUD_ACCESS_KEY`, `ACRCLOUD_ACCESS_SECRET`; optional `AUDD_API_TOKEN`.
- **Optional** — `DOWNLOAD_PATH`, `MONITOR_INTERVAL_MINUTES`, `DOWNLOAD_CONCURRENCY` (1–8, default 3; parallel downloads), `ENCRYPTION_KEY`.

## Features (Spotify ID)

- Paste a playlist URL, monitor on an interval, download new or all tracks.
- Real-time download progress (SSE).
- Optional archive / empty workflow after download (Spotify user connection in Settings).

### Known limitation: YouTube match vs Spotify track

Downloads use **yt-dlp** with **YouTube search** (`artist - title`), then **ID3 tags are taken from Spotify**. The audio file is whatever that search returns first — it may be a cover, live cut, wrong upload, or a bad match, especially for **indie or niche** tracks where YouTube metadata is messy.

There is **no automatic verification** that the downloaded audio is the same recording as on Spotify. Doing that reliably (fingerprinting, duration heuristics, multi-result ranking, etc.) is **non-trivial and still error-prone** for small-catalog music, so this is a **documented, intentional non-goal** for this project — not something we plan to “fix” with a quick feature.

**What you can do:** use the download progress UI: it shows the **YouTube title** and a **link to the source video** so you can sanity-check before trusting the file.

## Features (Mixtape ID)

- Fingerprint status check: **`GET http://localhost:8000/api/mixtape/fingerprint-status`** — confirms whether ACRCloud/AudD env is detected (no secrets returned).
- **Export to Spotify playlist** uses the same user session as **Spotify ID → Settings** (one connect). Optional Mixtape-only OAuth exists if you never open Settings.

## Requirements

- **Python 3.11+**
- **Node.js 18+**
- **yt-dlp** and **ffmpeg** on `PATH` (downloads and Mixtape audio processing). Example: `brew install yt-dlp ffmpeg` (macOS).

## Troubleshooting

| Issue | What to do |
|-------|------------|
| **Connection refused / API errors in the UI** | Run the backend on :8000 (`npm run dev` from root, or `uvicorn` from `backend/`). |
| **Spotify: HTTP 400, invalid redirect, or Dashboard “not secure”** | Use **`http://127.0.0.1:8000/api/auth/spotify/callback`** — the IP is **127.0.0.1** (four parts: 127, 0, 0, 1). A common mistake is **127.0.01** (wrong). Not `localhost`. Match Dashboard and **`SPOTIFY_REDIRECT_URI`** in `.env`, then restart the API. |
| **Downloads fail** | Install **yt-dlp** and **ffmpeg**; ensure the download folder in Settings exists and is writable. |
| **Mixtape finds no tracks** | Call **`/api/mixtape/fingerprint-status`**. Ensure ACRCloud (and optionally AudD) keys in repo-root `.env`, then restart the API. |
| **DB migrations** | `cd backend && alembic upgrade head` |

## Docs

- **[CLAUDE.md](CLAUDE.md)** — developer/agent overview (architecture, commands).
- **[Documentation.md](Documentation.md)** — short product notes; detailed setup is above.

## License / usage

Playlist and track metadata come from Spotify. Audio is matched via YouTube search. Mixtape ID uses third-party fingerprinting APIs. Use complies with Spotify, YouTube, and those providers’ terms; respect copyright.