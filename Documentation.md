# Music Studio — product notes

**Music Studio** (repo name often **SpotDownload**) is a self-hosted app that combines:

1. **Spotify ID** — Track Spotify playlists, diff new tracks, download audio locally using **yt-dlp** and **ffmpeg**, with metadata from Spotify.
2. **Mixtape ID** — Analyze long mixes (file or streaming URL), fingerprint samples via **ACRCloud** / **AudD**, produce a timestamped list, and optionally push tracks through the same download path or to a Spotify playlist.

Everything runs locally: **FastAPI** + **SQLite** + **React (Vite)**. One **repo-root `.env`** configures Spotify, fingerprinting, and paths.

**Spotify OAuth redirect:** use **`http://127.0.0.1:8000/...`** in the Developer Dashboard, not `localhost` (Spotify treats `localhost` as insecure for redirect URIs).

**Spotify playlist export from Mixtape ID** reuses the same user session as **Spotify ID → Settings** (one browser connect). A separate Mixtape OAuth URL exists only if you skip Settings.

**Spotify ID downloads:** audio comes from **YouTube search**, tags from **Spotify** — the two can disagree (wrong upload, cover, live version; worse odds for **indie** tracks). The app does **not** try to verify the match automatically; that is **by design** (no easy robust solution). See **README → Known limitation** and use **source link / title** in the download UI when in doubt.

## Where to read more

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Setup, env vars, troubleshooting, quick start with `npm run dev` |
| [CLAUDE.md](CLAUDE.md) | Architecture, routers, services, dev commands for contributors and tooling |

For API behavior and endpoints, use the interactive OpenAPI UI at `/docs` when the server is running.

## Historical note

Earlier long-form architecture write-ups targeted the Spotify-only stack before **Mixtape ID** lived in the same FastAPI app. The **README** and **CLAUDE.md** above are the maintained sources of truth.
