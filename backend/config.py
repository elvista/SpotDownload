"""Application configuration loaded from environment and .env."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_DOWNLOAD_PATH = str(Path.home() / "Music" / "SpotDownload")


class Settings(BaseSettings):
    """Pydantic settings for SpotDownload (env and .env)."""

    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    # Spotify requires loopback as 127.0.0.1 (not "localhost") — see README / Spotify redirect URI docs.
    SPOTIFY_REDIRECT_URI: str = "http://127.0.0.1:8000/api/auth/spotify/callback"
    # Browser redirect after Spotify ID OAuth (Spotify does not validate this URI).
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    DOWNLOAD_PATH: str = DEFAULT_DOWNLOAD_PATH
    DATABASE_URL: str = "sqlite:///./spotdownload.db"
    MONITOR_INTERVAL_MINUTES: int = 30
    DOWNLOAD_CONCURRENCY: int = Field(default=3, ge=1, le=8)
    ENCRYPTION_KEY: str = ""  # Optional. If set, Spotify tokens are encrypted at rest.

    @field_validator("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", mode="before")
    @classmethod
    def strip_spotify_creds(cls, v: str | None) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
            s = s[1:-1].strip()
        return s

    @field_validator("SPOTIFY_REDIRECT_URI")
    @classmethod
    def spotify_redirect_uri_sanity(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            return s
        # Common typo: 127.0.01 instead of 127.0.0.1 (four dotted decimals).
        if "127.0.01" in s and "127.0.0.1" not in s:
            raise ValueError(
                "SPOTIFY_REDIRECT_URI looks wrong: use 127.0.0.1 (127 dot 0 dot 0 dot 1), "
                "not 127.0.01. Update .env and the Spotify Dashboard to match exactly."
            )
        return s

    class Config:
        env_file = ".env"


settings = Settings()

# Ensure download directory exists
os.makedirs(settings.DOWNLOAD_PATH, exist_ok=True)
