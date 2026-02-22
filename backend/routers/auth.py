import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from spotipy.oauth2 import SpotifyOAuth

from database import get_db
from models import AppSetting
from config import settings

# Exact redirect URI the app sends to Spotify (must match Spotify Dashboard exactly)
SPOTIFY_REDIRECT_URI_EXACT = "http://localhost:8000/api/auth/spotify/callback"

router = APIRouter(tags=["auth"])
logger = logging.getLogger("spotdownload.auth")

SCOPES = [
    "playlist-modify-public",
    "playlist-modify-private",
    "playlist-read-private",
]


def get_spotify_oauth():
    """Create SpotifyOAuth instance for user authorization."""
    redirect_uri = settings.SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI_EXACT
    return SpotifyOAuth(
        client_id=settings.SPOTIFY_CLIENT_ID,
        client_secret=settings.SPOTIFY_CLIENT_SECRET,
        redirect_uri=redirect_uri.strip(),
        scope=" ".join(SCOPES),
        cache_path=None,  # We'll store tokens in DB instead
    )


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def set_setting(db: Session, key: str, value: str):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


@router.get("/auth/spotify")
def spotify_login():
    """Redirect user to Spotify authorization page."""
    sp_oauth = get_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(url=auth_url)


@router.get("/auth/spotify/callback")
def spotify_callback(code: str = None, error: str = None, db: Session = Depends(get_db)):
    """Handle Spotify OAuth callback and store tokens."""
    if error:
        logger.error(f"Spotify auth error: {error}")
        return RedirectResponse(url="http://localhost:5173?auth=error")
    
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")
    
    try:
        sp_oauth = get_spotify_oauth()
        token_info = sp_oauth.get_access_token(code, as_dict=True, check_cache=False)
        
        # Store tokens in database
        set_setting(db, "spotify_access_token", token_info["access_token"])
        set_setting(db, "spotify_refresh_token", token_info["refresh_token"])
        set_setting(db, "spotify_token_expires_at", str(token_info["expires_at"]))
        
        logger.info("Spotify authentication successful")
        return RedirectResponse(url="http://localhost:5173?auth=success")
    
    except Exception as e:
        logger.error(f"Failed to exchange code for token: {e}")
        return RedirectResponse(url="http://localhost:5173?auth=error")


@router.get("/auth/spotify/status")
def spotify_auth_status(db: Session = Depends(get_db)):
    """Check if user has connected their Spotify account."""
    refresh_token = get_setting(db, "spotify_refresh_token", "")
    redirect_uri = (settings.SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI_EXACT).strip()
    return {
        "connected": bool(refresh_token),
        "has_token": bool(refresh_token),
        "redirect_uri": redirect_uri,
    }


@router.delete("/auth/spotify")
def spotify_disconnect(db: Session = Depends(get_db)):
    """Disconnect Spotify account by removing stored tokens."""
    set_setting(db, "spotify_access_token", "")
    set_setting(db, "spotify_refresh_token", "")
    set_setting(db, "spotify_token_expires_at", "")
    logger.info("Spotify account disconnected")
    return {"detail": "Spotify account disconnected"}
