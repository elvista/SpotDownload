import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_DOWNLOAD_PATH = str(Path.home() / "Music" / "SpotDownload")


class Settings(BaseSettings):
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    SPOTIFY_REDIRECT_URI: str = "http://localhost:8000/api/auth/spotify/callback"
    DOWNLOAD_PATH: str = DEFAULT_DOWNLOAD_PATH
    DATABASE_URL: str = "sqlite:///./spotdownload.db"
    MONITOR_INTERVAL_MINUTES: int = 30

    class Config:
        env_file = ".env"


settings = Settings()

# Ensure download directory exists
os.makedirs(settings.DOWNLOAD_PATH, exist_ok=True)
