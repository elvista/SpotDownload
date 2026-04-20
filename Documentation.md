# CrateDigger — product notes

**CrateDigger** is a self-hosted app that combines:

1. **Spotify ID** — Track Spotify playlists, diff new tracks, download audio locally using **yt-dlp** and **ffmpeg**, with metadata from Spotify.
2. **Mixtape ID** — Analyze long mixes (file or streaming URL), fingerprint samples via **ACRCloud** / **AudD**, produce a timestamped list, and optionally push tracks through the same download path or to a Spotify playlist (reusing the Spotify ID OAuth connection).
3. **Genre ID** — Scan your local **Lexicon DJ** library for tracks with empty `genre` values, classify them via **Last.fm** tag lookups, review the suggestions, and write approved genres back to the Lexicon database.

Everything runs locally: **FastAPI** + **SQLite** + **React (Vite)**. One **repo-root `.env`** configures Spotify, fingerprinting, and paths.

**Single OAuth across the app.** One Spotify connect under **Settings → Spotify ID** covers every feature that talks to Spotify (playlist monitoring, Mixtape playlist export). No feature-specific OAuth flows.

**Spotify OAuth redirect:** use **`http://127.0.0.1:<port>/...`** in the Developer Dashboard, not `localhost` (Spotify treats `localhost` as insecure for redirect URIs). Port is **5174** for the always-on deploy and **8000** for `npm run dev`.

**Spotify ID downloads:** audio comes from **YouTube search**, tags from **Spotify** — the two can disagree (wrong upload, cover, live version; worse odds for **indie** tracks). The app does **not** try to verify the match automatically; that is **by design** (no easy robust solution). See **README → Known limitation** and use **source link / title** in the download UI when in doubt.

**Genre ID** reads the Lexicon DJ SQLite database in **read-only mode** during scanning and opens it **read/write only when you export** approved genres. The database path is configurable in the Genre ID UI (default: `~/Library/Application Support/Lexicon/main.db`).

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

## Genre ID — how it works

1. **Point at your Lexicon DB.** Default path is `~/Library/Application Support/Lexicon/main.db`. The Genre ID tab validates the path (checks for the `Track` table) and reports total tracks and how many have empty genres.
2. **Scan.** Pulls tracks with empty `genre` values (or the full library if you choose "rescan") and looks each one up on **Last.fm** in three steps:
   - Track tags for `artist` + `title` with common suffixes (e.g., `- Remastered`) stripped.
   - If that fails, strip all parentheticals (remix/edit info) and retry.
   - If that also fails, fall back to the **artist's** top tags.
3. **Review.** Suggestions stream into the UI table as Last.fm returns them (SSE). You can edit or clear the suggested genre per-track.
4. **Stage and export.** Approve the tracks you want, then click export. CrateDigger opens the Lexicon DB in read/write mode, runs one `UPDATE Track SET genre = ? WHERE id = ?` per approved track, and commits.

**Only the `genre` column is ever written.** Artist, title, remixer, key, BPM, and everything else in the Lexicon DB are untouched. This is an intentional constraint — Genre ID does one thing.

**Requires** `LASTFM_API_KEY` in `.env`. Free to create at <https://www.last.fm/api/account/create>.

## Running CrateDigger always-on (macOS, no terminal)

For day-to-day use you don't want `npm run dev` in a terminal. Install CrateDigger as a **launchd LaunchAgent** so it starts when you log in, auto-restarts if it crashes, and runs without any window open.

The single process is **FastAPI on port 5174** serving both the API and the built React bundle (same origin, no Vite, no CORS).

### One-time setup

1. **Update `.env`** (repo root):

   ```
   SPOTIFY_REDIRECT_URI=http://127.0.0.1:5174/api/auth/spotify/callback
   FRONTEND_ORIGIN=http://127.0.0.1:5174
   ```

2. **Register the redirect URI** in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) → your app → **Edit Settings** → add exactly:

   ```
   http://127.0.0.1:5174/api/auth/spotify/callback
   ```

   (If you also use `npm run dev`, keep the `:8000` URI registered too.)

3. **Install the service**:

   ```bash
   ./scripts/install-service.sh
   ```

### Daily URLs

| Device | URL |
| --- | --- |
| Your Mac | <http://127.0.0.1:5174> |
| Any device on your Wi-Fi (phone, laptop) | `http://<your-mac-hostname>.local:5174` |

First-time Spotify connect must happen from the Mac browser (Spotify only accepts `127.0.0.1` for the redirect URI). After that, the saved refresh token works from any device on your LAN.

## Operational commands (Mac)

All of these live in [scripts/](scripts/) and are safe to re-run.

### `scripts/install-service.sh` — first-time install and updates

```bash
./scripts/install-service.sh
```

What it does:

1. `npm install && npm run build` inside `frontend/` — produces `frontend/dist/`, the bundle FastAPI will serve.
2. Creates `~/Library/Logs/cratedigger/` for stdout/stderr logs.
3. Copies [scripts/com.cratedigger.plist](scripts/com.cratedigger.plist) to `~/Library/LaunchAgents/com.cratedigger.plist`.
4. Unloads any previous version of the agent, then loads the new one with `launchctl load`.
5. Waits a beat, verifies the agent is listed, and prints the URLs.

Re-run it any time you change the plist itself, the Python dependencies (after activating the venv and `pip install -r requirements.txt`), or when you want a clean reinstall.

### `scripts/rebuild.sh` — rebuild and restart after a code change

```bash
./scripts/rebuild.sh
```

What it does:

1. `npm run build` inside `frontend/` — refreshes `frontend/dist/`.
2. `launchctl kickstart -k gui/$(id -u)/com.cratedigger` — sends SIGTERM to the running backend and restarts it.

Use this after a `git pull`, after editing any backend Python file, or after changing anything in the frontend source. It does **not** rebuild the venv or re-`npm install`. If you added Python or Node dependencies, handle those manually first (`pip install -r backend/requirements.txt`, `npm install` in frontend/).

### `scripts/uninstall-service.sh` — remove the agent

```bash
./scripts/uninstall-service.sh
```

What it does:

1. `launchctl unload ~/Library/LaunchAgents/com.cratedigger.plist` (ignored if already unloaded).
2. Deletes the plist file.

Safe to run even if the service isn't currently installed. Does not touch your `.env`, database, downloads, logs, or the code in this repo.

### `scripts/com.cratedigger.plist` — the launchd agent definition

This is the macOS service definition installed by `install-service.sh`. Key settings:

- **Label:** `com.cratedigger`
- **Program:** `backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 5174` — binds to all interfaces so devices on your LAN can reach it.
- **WorkingDirectory:** `backend/` — so uvicorn can find `main.py`.
- **RunAtLoad + KeepAlive (on crash):** starts immediately when loaded; restarts only if the process exits with a non-zero status (not on `launchctl unload`).
- **ThrottleInterval: 10s** — prevents fast crash loops.
- **EnvironmentVariables:** `PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` — so `yt-dlp` and `ffmpeg` resolve without a login shell.
- **StandardOutPath / StandardErrorPath:** `~/Library/Logs/cratedigger/stdout.log` and `stderr.log`.

Edit the plist if you want to change the port, bind to loopback only, or add environment variables; then re-run `./scripts/install-service.sh` to reload.

### Common `launchctl` commands

```bash
# Is it running?
launchctl list | grep cratedigger

# Tail logs
tail -f ~/Library/Logs/cratedigger/stderr.log
tail -f ~/Library/Logs/cratedigger/stdout.log

# Restart without rebuilding
launchctl kickstart -k gui/$(id -u)/com.cratedigger

# Temporarily stop (until next login or manual load)
launchctl unload ~/Library/LaunchAgents/com.cratedigger.plist

# Start again after an unload
launchctl load ~/Library/LaunchAgents/com.cratedigger.plist
```

### Caveats

- **LaunchAgent, not LaunchDaemon.** The service only runs while you're logged in. After reboot it starts once you log in. If you want it running even without login, convert to a LaunchDaemon (requires sudo and `/Library/LaunchDaemons/`).
- **Mac has to be awake** for the scheduled playlist monitor to keep ticking. Consider *Settings → Battery → Options → Prevent automatic sleeping on power adapter when the display is off*.
- **Homebrew PATH.** The plist assumes `/opt/homebrew/bin` (Apple Silicon). On Intel Macs, change it to `/usr/local/bin`.
- **Port 5174 must be free.** Check with `lsof -i :5174` if the service refuses to start.

## Where to read more

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Setup, env vars, troubleshooting, quick start with `npm run dev` |
| [CLAUDE.md](CLAUDE.md) | Architecture, routers, services, dev commands for contributors and tooling |

For API behavior and endpoints, use the interactive OpenAPI UI at `/docs` when the server is running.

## Historical note

Earlier long-form architecture write-ups targeted the Spotify-only stack before **Mixtape ID** lived in the same FastAPI app, and before **Lexicon ID** (a playlist-import tool) was replaced by **Genre ID** (a library-enrichment tool). The **README** and **CLAUDE.md** above are the maintained sources of truth.
