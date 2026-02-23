# SpotDownload

Monitor Spotify playlists for changes and download new songs automatically.

## Features

- Paste any Spotify playlist URL to track it
- Detect new songs added to monitored playlists
- Download songs to your computer via spotdl
- Real-time download progress
- Background monitoring with configurable intervals

## Setup

### 1. Spotify API Credentials

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Copy the **Client ID** and **Client Secret**
4. In your app settings, click **Edit Settings**, then under **Redirect URIs** add:
   `http://localhost:8000/api/auth/spotify/callback` and click **Add**, then **Save**.
5. Create a `.env` file in the project root (copy from `.env.example`):

```bash
cp .env.example .env
```

Then fill in your credentials (including `SPOTIFY_REDIRECT_URI=http://localhost:8000/api/auth/spotify/callback` if not already present).

### 2. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend runs at http://localhost:8000

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at http://localhost:5173

## How to Use

1. **Add a playlist** — Paste a Spotify playlist URL (e.g. `https://open.spotify.com/playlist/...`) into the input and click **Add Playlist**. The app fetches the track list and stores it locally.
2. **Monitor** — Playlists are checked in the background at the interval set in Settings. New tracks are marked as "New" in the UI.
3. **Download** — Click **Download All**, **Download New**, or the download icon on a track. Files are saved as MP3 with ID3 tags (title, artist, album, genre, cover art) from Spotify.
4. **Archive** — After downloads finish, the app can move successful tracks into a Spotify archive playlist and empty the source playlist. Connect your Spotify account in Settings and set the **Archive Playlist Name** to enable this.

**Settings** (gear icon): set download folder, monitor interval, archive playlist name, theme (dark/light/system), and connect Spotify for archive/empty features.

API documentation is available at **http://localhost:8000/docs** when the backend is running.

## Troubleshooting

| Issue | What to do |
|-------|------------|
| **Request failed / Connection refused** | Start the backend: `cd backend && source venv/bin/activate && uvicorn main:app --reload` |
| **Spotify: "Invalid redirect URI" or 400** | In the [Spotify Dashboard](https://developer.spotify.com/dashboard) → Your app → Edit Settings → Redirect URIs, add exactly: `http://localhost:8000/api/auth/spotify/callback` (no trailing slash). Copy the value from Settings in the app. |
| **Downloads fail or no audio** | Install **yt-dlp** and **ffmpeg**: `pip install yt-dlp` and `brew install ffmpeg` (macOS). Ensure the download path in Settings is writable. |
| **Genre missing on tracks** | Re-sync the playlist: open the playlist and click **Check for Changes**, or remove and re-add the playlist. |
| **Database schema changes** | Run migrations: `cd backend && alembic upgrade head`. For a fresh install, the first run creates tables automatically. |

## Requirements

- Python 3.11+
- Node.js 18+
- yt-dlp and ffmpeg for downloads: `pip install yt-dlp` and `brew install ffmpeg` (macOS)
