# CrateDigger

**Your personal vinyl shop for the digital age.**

Vibecoded by Elius (https://hmelius.com)

---

You know that feeling — you're three hours deep in a DJ set on YouTube, you hear a track that stops you mid-scroll, and you *need* it. Or you've got a Spotify playlist that's become your lifeline and you want those files on your drive, tagged properly, no questions asked. Or maybe someone sends you a two-hour mixtape and you want to know every single track in it, timestamped, ready to save.

**CrateDigger** is a self-hosted web app for music obsessives who want to own their listening, not just stream it. Three tools, one app:

### Spotify ID — Your playlist, your files

Point it at any Spotify playlist. CrateDigger monitors it for new additions, downloads audio via **yt-dlp**, and writes clean **ID3 tags from Spotify** — artist, title, album art, the works. Set it and forget it: new tracks get pulled automatically on a schedule. It's your music library on autopilot.

### Mixtape ID — Crack open any mix

Paste a YouTube, SoundCloud, or Mixcloud URL (or upload a file directly). CrateDigger chops the mix into segments, fingerprints each one through **ACRCloud** and **AudD**, and hands you a **timestamped tracklist**. From there, download individual tracks or **export the whole list straight to a Spotify playlist** with one click — reusing the same Spotify connection as Spotify ID (one OAuth, shared across the app).

### Genre ID — Fill missing genres in your Lexicon DJ library

Connect your **Lexicon DJ** library (reads the local SQLite database, read-only). Scan for tracks with empty genres, classify them via **Last.fm** tag lookups, review the suggestions in the UI, and write approved genres back to the Lexicon database. Nothing is changed without your approval.

---

No cloud accounts, no subscriptions, no data leaving your machine. Everything runs locally: **FastAPI + SQLite + React**.

## Two ways to run it

| Mode | Ports | When to use |
|---|---|---|
| **Dev** — `npm run dev` | Vite `:5173`, FastAPI `:8000` | Active development with hot reload |
| **Always-on (macOS)** — launchd agent | FastAPI `:5174` serves everything | Day-to-day use; starts when you log in, survives crashes, no terminal needed |

Set up the always-on deploy once → open http://127.0.0.1:5174 any time (or `http://<hostname>.local:5174` from your phone on the same Wi-Fi). See [Documentation.md](Documentation.md#running-cratedigger-always-on-macos-no-terminal) for the step-by-step.

## Quick start — dev mode

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

- **Spotify** — `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`. Must use **`127.0.0.1`**, not `localhost` ([Spotify requires loopback as an IP](https://developer.spotify.com/documentation/web-api/tutorials/migration-insecure-redirect-uri)). Register the exact URI in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Spotify ID login uses **Authorization Code + PKCE**.
  - Always-on deploy: `http://127.0.0.1:5174/api/auth/spotify/callback`
  - Dev mode: `http://127.0.0.1:8000/api/auth/spotify/callback`
  - Register **both** redirect URIs in the Dashboard if you use both modes.
- **`FRONTEND_ORIGIN`** — where the browser is sent after Spotify login. Match your deploy: `http://127.0.0.1:5174` for always-on, `http://localhost:5173` for dev.
- **Mixtape → Spotify playlists** — Reuses the same Spotify connection as **Settings → Spotify ID**. No second OAuth.
- **Mixtape fingerprinting** — `ACRCLOUD_HOST`, `ACRCLOUD_ACCESS_KEY`, `ACRCLOUD_ACCESS_SECRET`; optional `AUDD_API_TOKEN`.
- **Genre ID** — `LASTFM_API_KEY` (get one free at [last.fm/api](https://www.last.fm/api/account/create)).
- **Optional** — `DOWNLOAD_PATH`, `MONITOR_INTERVAL_MINUTES`, `DOWNLOAD_CONCURRENCY` (1–8, default 3), `ENCRYPTION_KEY`.

## Features (Spotify ID)

- Paste a playlist URL, monitor on an interval, download new or all tracks.
- Real-time download progress (SSE).
- Optional archive / empty workflow after download (Spotify user connection in Settings).
- Supports **non-owned public playlists** via an embed fallback when Spotify Dev Mode blocks API access (capped at 100 tracks; details in [Documentation.md](Documentation.md#spotify-id--adding-non-owned-public-playlists)).

### Known limitation: YouTube match vs Spotify track

Downloads use **yt-dlp** with **YouTube search** (`artist - title`), then **ID3 tags are taken from Spotify**. The audio file is whatever that search returns first — it may be a cover, live cut, wrong upload, or a bad match, especially for **indie or niche** tracks where YouTube metadata is messy.

There is **no automatic verification** that the downloaded audio is the same recording as on Spotify. Doing that reliably (fingerprinting, duration heuristics, multi-result ranking, etc.) is **non-trivial and still error-prone** for small-catalog music, so this is a **documented, intentional non-goal** for this project — not something we plan to "fix" with a quick feature.

**What you can do:** use the download progress UI: it shows the **YouTube title** and a **link to the source video** so you can sanity-check before trusting the file.

## Features (Mixtape ID)

- Fingerprint status check: `GET /api/mixtape/fingerprint-status` — confirms whether ACRCloud/AudD env is detected (no secrets returned).
- **Import to Spotify** uses the same user session as **Spotify ID → Settings** (one connect covers Mixtape playlists too).
- Multi-strategy search: tries the specific remix/edit first, falls back to the base track. Candidate scoring rejects wrong matches.

## Features (Genre ID)

- Reads your **Lexicon DJ** database (read-only during scan; configurable path in the UI, default `~/Library/Application Support/Lexicon/main.db`).
- **Scan** — finds tracks with empty genres, looks up each via **Last.fm** (artist+title → artist tags fallback), streams progress over SSE.
- **Review** — suggested genres appear inline in the table. Edit, accept, or skip per-track. Approved tracks get staged.
- **Export** — writes approved genres back into the Lexicon database in a single commit.
- No artist/title changes, no other metadata touched — **genres only**.

## Requirements

- **Python 3.11+**
- **Node.js 18+**
- **yt-dlp** and **ffmpeg** on `PATH` (downloads and Mixtape audio processing). Example: `brew install yt-dlp ffmpeg` (macOS).

## Troubleshooting

| Issue | What to do |
|-------|------------|
| **Connection refused / API errors in the UI** | Always-on: check `launchctl list \| grep cratedigger` and `~/Library/Logs/cratedigger/stderr.log`. Dev: make sure `npm run dev` is running. |
| **Spotify: HTTP 400, invalid redirect, or Dashboard "not secure"** | Use `http://127.0.0.1:<port>/api/auth/spotify/callback`. The IP is **127.0.0.1** (four parts). Not `localhost`. Match the Dashboard and `SPOTIFY_REDIRECT_URI` in `.env` exactly, then restart. |
| **Downloads fail** | Install **yt-dlp** and **ffmpeg**; ensure the download folder in Settings exists and is writable. |
| **Mixtape finds no tracks** | Call `/api/mixtape/fingerprint-status`. Ensure ACRCloud (and optionally AudD) keys in repo-root `.env`, then restart. |
| **Genre ID "database not found"** | Open Genre ID, set the correct Lexicon DB path (default: `~/Library/Application Support/Lexicon/main.db`). |
| **Genre ID returns no suggestions** | Check `LASTFM_API_KEY` in `.env`. |
| **DB migrations** | `cd backend && alembic upgrade head` |

## Docs

- **[Documentation.md](Documentation.md)** — detailed product notes, always-on deployment guide, and operational commands.
- **[CLAUDE.md](CLAUDE.md)** — developer/agent overview (architecture, commands).

## License / usage

Playlist and track metadata come from Spotify. Audio is matched via YouTube search. Mixtape ID uses third-party fingerprinting APIs. Genre ID uses Last.fm tags. Use complies with Spotify, YouTube, Last.fm, and those providers' terms; respect copyright.
