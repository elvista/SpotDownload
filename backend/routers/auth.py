import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import AppSetting
from security import decrypt_token, encrypt_token

TOKEN_KEYS = ("spotify_access_token", "spotify_refresh_token")

# Must match Spotify Dashboard (loopback: use 127.0.0.1, not localhost — Spotify rejects localhost)
SPOTIFY_REDIRECT_URI_EXACT = "http://127.0.0.1:8000/api/auth/spotify/callback"

router = APIRouter(tags=["auth"])
logger = logging.getLogger("spotdownload.auth")

SCOPES = [
    "playlist-modify-public",
    "playlist-modify-private",
    "playlist-read-private",
]

# state -> (code_verifier, created_ms); PKCE verifier must match token exchange
_spotify_pkce_states: dict[str, tuple[str, float]] = {}
_PKCE_STATE_TTL_MS = 600_000


def _prune_spotify_pkce_states() -> None:
    now = time.time() * 1000
    dead = [k for k, (_, t) in _spotify_pkce_states.items() if now - t > _PKCE_STATE_TTL_MS]
    for k in dead:
        _spotify_pkce_states.pop(k, None)


def _scope_param() -> str:
    return " ".join(SCOPES)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def spotify_redirect_uri_warnings(uri: str) -> list[str]:
    """Human hints when the configured URI is a common mistake (Dashboard must match .env)."""
    u = (uri or "").strip()
    if not u:
        return []
    out: list[str] = []
    if "127.0.01" in u and "127.0.0.1" not in u:
        out.append(
            "Typo: the loopback host must be 127.0.0.1 (four numbers: 127, 0, 0, 1), not 127.0.01. "
            "Fix the Spotify Dashboard and SPOTIFY_REDIRECT_URI in .env."
        )
    if "localhost" in u.lower():
        out.append(
            "Spotify rejects http://localhost for redirect URIs; use http://127.0.0.1:8000/... instead."
        )
    return out


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    value = row.value if row else default
    if key in TOKEN_KEYS and value:
        value = decrypt_token(value, getattr(settings, "ENCRYPTION_KEY", None) or "")
    return value


def set_setting(db: Session, key: str, value: str):
    if key in TOKEN_KEYS and value:
        value = encrypt_token(value, getattr(settings, "ENCRYPTION_KEY", None) or "")
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


@router.get("/auth/spotify")
def spotify_login():
    """Redirect user to Spotify authorization (Authorization Code + PKCE)."""
    cid = (settings.SPOTIFY_CLIENT_ID or "").strip()
    secret = (settings.SPOTIFY_CLIENT_SECRET or "").strip()
    if not cid or not secret or cid.startswith("your_") or secret.startswith("your_"):
        raise HTTPException(
            status_code=503,
            detail="Spotify app not configured: set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env.",
        )

    redirect_uri = (settings.SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI_EXACT).strip()
    _prune_spotify_pkce_states()
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _pkce_challenge(code_verifier)
    state = secrets.token_hex(16)
    _spotify_pkce_states[state] = (code_verifier, time.time() * 1000)

    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": _scope_param(),
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
        "state": state,
    }
    auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"
    return RedirectResponse(url=auth_url)


@router.get("/auth/spotify/callback")
def spotify_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """OAuth callback: exchange authorization code for tokens (PKCE)."""
    ui = settings.FRONTEND_ORIGIN.rstrip("/")
    if error:
        logger.error("Spotify auth error: %s", error)
        return RedirectResponse(url=f"{ui}?auth=error")

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")

    if not state:
        logger.error("Spotify callback missing state (PKCE)")
        return RedirectResponse(url=f"{ui}?auth=error")

    _prune_spotify_pkce_states()
    pkce = _spotify_pkce_states.pop(state, None)
    if not pkce:
        logger.error("Spotify callback invalid or expired state")
        return RedirectResponse(url=f"{ui}?auth=error")

    code_verifier, _ = pkce
    redirect_uri = (settings.SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI_EXACT).strip()
    cid = (settings.SPOTIFY_CLIENT_ID or "").strip()

    # PKCE token exchange (Spotify): client_id + code_verifier only — do not send client_secret here.
    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cid,
        "code_verifier": code_verifier,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post("https://accounts.spotify.com/api/token", data=token_data, headers=headers)
        if r.status_code != 200:
            logger.error("Spotify token exchange failed: %s %s", r.status_code, r.text[:500])
            return RedirectResponse(url=f"{ui}?auth=error")
        token_info = r.json()
    except Exception as e:
        logger.exception("Spotify token exchange: %s", e)
        return RedirectResponse(url=f"{ui}?auth=error")

    refresh = token_info.get("refresh_token")
    if not refresh:
        logger.error("Spotify token response missing refresh_token")
        return RedirectResponse(url=f"{ui}?auth=error")

    set_setting(db, "spotify_access_token", token_info["access_token"])
    set_setting(db, "spotify_refresh_token", refresh)
    expires_at = int(time.time()) + int(token_info.get("expires_in", 3600))
    set_setting(db, "spotify_token_expires_at", str(expires_at))

    logger.info("Spotify authentication successful")
    return RedirectResponse(url=f"{ui}?auth=success")


@router.get("/auth/spotify/status")
def spotify_auth_status(db: Session = Depends(get_db)):
    """Check if user has connected their Spotify account."""
    refresh_token = get_setting(db, "spotify_refresh_token", "")
    redirect_uri = (settings.SPOTIFY_REDIRECT_URI or SPOTIFY_REDIRECT_URI_EXACT).strip()
    return {
        "connected": bool(refresh_token),
        "has_token": bool(refresh_token),
        "redirect_uri": redirect_uri,
        "redirect_uri_warnings": spotify_redirect_uri_warnings(redirect_uri),
    }


@router.delete("/auth/spotify")
def spotify_disconnect(db: Session = Depends(get_db)):
    """Disconnect Spotify account by removing stored tokens."""
    set_setting(db, "spotify_access_token", "")
    set_setting(db, "spotify_refresh_token", "")
    set_setting(db, "spotify_token_expires_at", "")
    logger.info("Spotify account disconnected")
    return {"detail": "Spotify account disconnected"}
