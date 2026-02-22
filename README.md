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

## Requirements

- Python 3.11+
- Node.js 18+
- ffmpeg (required by spotdl): `brew install ffmpeg`
