"""ACRCloud and AudD audio identification for Mixtape ID."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from config import settings as app_settings

logger = logging.getLogger("cratedigger.fingerprinter")

ACR_SKIP_AUDD_MIN_RAW_SCORE = 0.8

BACKEND_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = BACKEND_ROOT / "cache"
CACHE_FILE = CACHE_DIR / "fingerprint-cache.json"

# Placeholder / tutorial values — treated as "not configured"
_PLACEHOLDER_SUBSTRINGS = (
    "your_acrcloud",
    "your_audd",
    "xxx",
    "changeme",
    "placeholder",
)


def _env_trim(key: str) -> str:
    return (os.environ.get(key) or "").strip()


def _looks_configured(value: str) -> bool:
    if not value:
        return False
    low = value.lower()
    if value.startswith("your_"):
        return False
    return not any(s in low for s in _PLACEHOLDER_SUBSTRINGS)


class Fingerprinter:
    def __init__(self) -> None:
        self.cache: dict[str, dict[str, Any]] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.spotify_token: str | None = None
        self.spotify_token_expires_at = 0.0
        self.spotify_user_token: str | None = None
        self.spotify_user_token_expires_at = 0.0
        self.service_reliability: dict[str, dict[str, Any]] = {
            "ACRCloud": {"weight": 1.0, "baseConfidence": 0.85, "successCount": 0, "totalCount": 0},
            "AudD": {"weight": 0.85, "baseConfidence": 0.75, "successCount": 0, "totalCount": 0},
        }
        self.learning_metrics: dict[str, Any] = {
            "successfulStrategies": {},
            "genrePatterns": {},
        }
        self._http: httpx.AsyncClient | None = None
        self._http_lock = asyncio.Lock()
        self.load_persistent_cache()

    async def _http_client(self) -> httpx.AsyncClient:
        async with self._http_lock:
            if self._http is None or self._http.is_closed:
                self._http = httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, connect=15.0),
                    limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
                )
            return self._http

    async def aclose(self) -> None:
        async with self._http_lock:
            client = self._http
            self._http = None
        if client is not None and not client.is_closed:
            await client.aclose()

    def fingerprint_env_status(self) -> dict[str, Any]:
        """Non-secret diagnostics for Mixtape ID setup (env from repo-root .env)."""
        host = _env_trim("ACRCLOUD_HOST")
        ak = _env_trim("ACRCLOUD_ACCESS_KEY")
        sec = _env_trim("ACRCLOUD_ACCESS_SECRET")
        audd = _env_trim("AUDD_API_TOKEN")

        host_sane = bool(host) and "://" not in host and "." in host
        acr_ok = (
            host_sane
            and _looks_configured(ak)
            and _looks_configured(sec)
            and _looks_configured(host)
        )
        audd_ok = _looks_configured(audd)

        hints: list[str] = []
        if not acr_ok and not audd_ok:
            hints.append(
                "Add real ACRCloud credentials (ACRCLOUD_HOST, ACRCLOUD_ACCESS_KEY, "
                "ACRCLOUD_ACCESS_SECRET) and/or AUDD_API_TOKEN to the repo-root .env, then restart the API."
            )
        elif not acr_ok and audd_ok:
            hints.append(
                "ACRCloud not set; using AudD fallback only (slower / less reliable for DJ mixes)."
            )
        if host and ("://" in host or "http" in host.lower()):
            hints.append(
                "ACRCLOUD_HOST should be the hostname only, e.g. identify-us-west-2.acrcloud.com (no https://)."
            )

        return {
            "canIdentify": acr_ok or audd_ok,
            "acrcloud": {
                "configured": acr_ok,
                "hostSet": bool(host),
                "accessKeySet": bool(ak),
                "accessSecretSet": bool(sec),
            },
            "audd": {"configured": audd_ok, "tokenSet": bool(audd)},
            "hints": hints,
        }

    def load_persistent_cache(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not CACHE_FILE.exists():
            return
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            entries = data.get("cache") or []
            self.cache = {k: v for k, v in entries}
            logger.info("Loaded %s cached fingerprints from disk", len(self.cache))
        except Exception as e:
            logger.warning("Could not load fingerprint cache: %s", e)

    def save_persistent_cache(self) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "cache": list(self.cache.items()),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Could not save fingerprint cache: %s", e)

    @staticmethod
    def get_cache_key(audio_bytes: bytes) -> str:
        return hashlib.md5(audio_bytes).hexdigest()

    def clear_cache(self) -> None:
        self.cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0

    def get_cache_stats(self) -> dict[str, Any]:
        total = self.cache_hits + self.cache_misses
        hit_rate = f"{100 * self.cache_hits / total:.1f}%" if total else "0%"
        return {
            "size": len(self.cache),
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hitRate": hit_rate,
        }

    async def identify_with_confidence(
        self, audio_file_path: str, timeout: float = 15.0
    ) -> dict[str, Any] | None:
        if not os.path.isfile(audio_file_path):
            raise FileNotFoundError("Audio file not found")
        audio_bytes = Path(audio_file_path).read_bytes()
        key = self.get_cache_key(audio_bytes)
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key]
        self.cache_misses += 1

        result = await self.identify_with_acr_audd_merge(audio_bytes, timeout=timeout)
        if result:
            self.cache[key] = result
            if len(self.cache) % 10 == 0:
                await asyncio.to_thread(self.save_persistent_cache)
        return result

    async def identify_with_acr_audd_merge(
        self, audio_buffer: bytes, timeout: float = 15.0
    ) -> dict[str, Any] | None:
        async def _with_timeout(coro, name: str):
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except TimeoutError:
                logger.warning("%s: identify timed out after %ss", name, timeout)
                return None
            except ValueError as e:
                logger.warning("%s: %s", name, e)
                return None
            except Exception as e:
                logger.warning("%s failed: %s", name, e)

        acr = await _with_timeout(self.identify_with_acr_cloud(audio_buffer), "ACRCloud")
        if not acr:
            audd = await _with_timeout(self.identify_with_audd(audio_buffer), "AudD")
            if audd:
                return {**audd, "serviceName": "AudD"}
            logger.debug("No match from ACRCloud or AudD for %s-byte sample", len(audio_buffer))
            return None

        raw = acr.get("acrScore")
        skip_audd = raw is not None and raw >= ACR_SKIP_AUDD_MIN_RAW_SCORE
        if skip_audd:
            return {**acr, "serviceName": "ACRCloud"}

        audd = await _with_timeout(self.identify_with_audd(audio_buffer), "AudD")
        if not audd:
            return {**acr, "serviceName": "ACRCloud"}

        if self.is_same_song(acr, audd):
            acr_conf = acr.get("confidence") or 0
            audd_conf = audd.get("confidence") or 0
            boosted = min(1.0, max(acr_conf, audd_conf) * 1.15)
            return {
                **acr,
                "service": "ACRCloud",
                "confidence": boosted,
                "consensusWithAudD": True,
                "serviceName": "ACRCloud",
            }
        return {**acr, "serviceName": "ACRCloud"}

    @staticmethod
    def is_same_song(a: dict[str, Any], b: dict[str, Any]) -> bool:
        def norm(s: str) -> str:
            if not s:
                return ""
            s = s.lower()
            s = re.sub(r"\(.*?\)", "", s)
            s = re.sub(r"\[.*?\]", "", s)
            s = re.sub(r"feat\.|ft\.|featuring", "", s, flags=re.I)
            s = s.replace("&", "and")
            s = re.sub(r"[^a-z0-9]", "", s)
            return s.strip()

        return norm(a.get("artist", "")) == norm(b.get("artist", "")) and norm(
            a.get("title", "")
        ) == norm(b.get("title", ""))

    def calibrate_confidence(self, result: dict[str, Any]) -> dict[str, Any]:
        if not result or not result.get("service"):
            return result
        rel = self.service_reliability.get(result["service"])
        if not rel:
            return result
        raw_conf = result.get("confidence") or 0.5
        total = rel["totalCount"]
        success_rate = rel["successCount"] / total if total > 0 else 0.75
        calibrated = (raw_conf * rel["weight"] * success_rate) + (
            (1 - raw_conf) * (1 - rel["baseConfidence"])
        )
        conf = max(0.1, min(float(calibrated), 1.0))
        return {**result, "confidence": conf, "rawConfidence": raw_conf, "calibrated": True}

    def record_identification_result(
        self,
        service: str,
        success: bool,
        confidence: float,
        context: dict[str, Any] | None = None,
    ) -> None:
        if not service or service not in self.service_reliability:
            return
        self.service_reliability[service]["totalCount"] += 1
        if success:
            self.service_reliability[service]["successCount"] += 1

    def adjust_confidence_by_context(
        self, result: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        adj = result.get("confidence") or 0.5
        adjustments: list[str] = []
        if context.get("nearbyArtistMatch"):
            adj *= 1.15
            adjustments.append("nearby-artist +15%")
        if context.get("albumContinuity"):
            adj *= 1.10
            adjustments.append("album-continuity +10%")
        if context.get("genreConsistency"):
            adj *= 1.08
            adjustments.append("genre-consistency +8%")
        if context.get("repetitionDetected"):
            adj *= 0.90
            adjustments.append("repetition-detected -10%")
        if context.get("suspiciouslyShort"):
            adj *= 0.85
            adjustments.append("suspicious-duration -15%")
        conf = max(0.1, min(adj, 1.0))
        out = {**result, "confidence": conf}
        if adjustments:
            out["confidenceAdjustments"] = adjustments
            out["contextAdjusted"] = True
        return out

    async def identify_with_acr_cloud(self, audio_buffer: bytes) -> dict[str, Any] | None:
        host = os.environ.get("ACRCLOUD_HOST", "").strip()
        access_key = os.environ.get("ACRCLOUD_ACCESS_KEY", "").strip()
        access_secret = os.environ.get("ACRCLOUD_ACCESS_SECRET", "").strip()
        if not host or not access_key or not access_secret:
            raise ValueError("ACRCloud credentials not configured")

        ts = int(time.time())
        string_to_sign = f"POST\n/v1/identify\n{access_key}\naudio\n1\n{ts}"
        sig = base64.b64encode(
            hmac.new(
                access_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1
            ).digest()
        ).decode("ascii")

        client = await self._http_client()
        files = {"sample": ("audio.mp3", audio_buffer, "audio/mpeg")}
        data = {
            "access_key": access_key,
            "data_type": "audio",
            "signature_version": "1",
            "signature": sig,
            "sample_bytes": str(len(audio_buffer)),
            "timestamp": str(ts),
        }
        try:
            r = await client.post(f"https://{host}/v1/identify", data=data, files=files)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(
                "ACRCloud HTTP %s: %s",
                e.response.status_code,
                (e.response.text or "")[:800],
            )
            return None
        except httpx.RequestError as e:
            logger.warning("ACRCloud request failed: %s", e)
            return None
        body = r.json()

        st = body.get("status") or {}
        if st.get("code") != 0:
            logger.warning(
                "ACRCloud no match or error: code=%s msg=%s",
                st.get("code"),
                st.get("msg"),
            )
            return None
        music = (body.get("metadata") or {}).get("music") or []
        if not music:
            return None
        track = music[0]
        artist = (track.get("artists") or [{}])[0].get("name") or "Unknown Artist"
        title = track.get("title") or "Unknown Title"
        score = track.get("score")
        acr_score = float(score) / 100.0 if score is not None else None
        confidence = acr_score if acr_score is not None else 0.5
        spotify_link = await self.get_spotify_link(artist, title)
        return {
            "artist": artist,
            "title": title,
            "service": "ACRCloud",
            "spotifyLink": spotify_link,
            "album": (track.get("album") or {}).get("name"),
            "confidence": confidence,
            "acrScore": acr_score,
            "genre": (track.get("genres") or [{}])[0].get("name") if track.get("genres") else None,
            "bpm": None,
            "key": None,
        }

    async def identify_with_audd(self, audio_buffer: bytes) -> dict[str, Any] | None:
        token = os.environ.get("AUDD_API_TOKEN", "").strip()
        if not token:
            raise ValueError("AudD API token not configured")
        client = await self._http_client()
        files = {"file": ("audio.mp3", audio_buffer, "audio/mpeg")}
        try:
            r = await client.post(
                "https://api.audd.io/",
                data={"return": "spotify", "api_token": token},
                files=files,
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(
                "AudD HTTP %s: %s",
                e.response.status_code,
                (e.response.text or "")[:800],
            )
            return None
        except httpx.RequestError as e:
            logger.warning("AudD request failed: %s", e)
            return None
        body = r.json()
        if body.get("status") != "success" or not body.get("result"):
            err = body.get("error") or body.get("message")
            if err:
                logger.warning("AudD response: %s", err)
            return None
        res = body["result"]
        sp = res.get("spotify") or {}
        return {
            "artist": res.get("artist") or "Unknown Artist",
            "title": res.get("title") or "Unknown Title",
            "service": "AudD",
            "spotifyLink": (sp.get("external_urls") or {}).get("spotify"),
            "album": res.get("album"),
            "confidence": 0.7,
            "genre": (sp.get("genres") or [None])[0] if sp.get("genres") else None,
            "bpm": sp.get("tempo") or res.get("timecode_bpm"),
            "key": sp.get("key"),
        }

    async def get_spotify_link(self, artist: str, title: str) -> str | None:
        cid = getattr(app_settings, "SPOTIFY_CLIENT_ID", "") or os.environ.get(
            "SPOTIFY_CLIENT_ID", ""
        )
        secret = getattr(app_settings, "SPOTIFY_CLIENT_SECRET", "") or os.environ.get(
            "SPOTIFY_CLIENT_SECRET", ""
        )
        if not cid or not secret:
            return None
        token = await self.get_spotify_token()
        if not token:
            return None
        q = f"{artist} {title}"
        client = await self._http_client()
        r = await client.get(
            "https://api.spotify.com/v1/search",
            params={"q": q, "type": "track", "limit": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code == 401:
            self.spotify_token = None
            self.spotify_token_expires_at = 0
            return None
        if r.status_code != 200:
            return None
        data = r.json()
        items = (data.get("tracks") or {}).get("items") or []
        if not items:
            return None
        return (items[0].get("external_urls") or {}).get("spotify")

    async def get_spotify_token(self) -> str | None:
        cid = getattr(app_settings, "SPOTIFY_CLIENT_ID", "") or os.environ.get(
            "SPOTIFY_CLIENT_ID", ""
        )
        secret = getattr(app_settings, "SPOTIFY_CLIENT_SECRET", "") or os.environ.get(
            "SPOTIFY_CLIENT_SECRET", ""
        )
        if not cid or not secret:
            return None
        now = time.time() * 1000
        if self.spotify_token and now < self.spotify_token_expires_at:
            return self.spotify_token
        import base64 as b64

        creds = b64.b64encode(f"{cid}:{secret}".encode()).decode()
        client = await self._http_client()
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if r.status_code != 200:
            return None
        data = r.json()
        self.spotify_token = data["access_token"]
        self.spotify_token_expires_at = now + (data.get("expires_in", 3600) - 60) * 1000
        return self.spotify_token

    def spotify_user_token_path(self) -> Path:
        return CACHE_DIR / "spotify-user-token.json"

    def get_spotify_refresh_token(self) -> str | None:
        env = (os.environ.get("SPOTIFY_REFRESH_TOKEN") or "").strip()
        if env and env != "your_spotify_refresh_token":
            return env
        try:
            from database import SessionLocal
            from models import AppSetting
            from security import decrypt_token

            enc_key = getattr(app_settings, "ENCRYPTION_KEY", None) or ""
            db = SessionLocal()
            try:
                row = (
                    db.query(AppSetting)
                    .filter(AppSetting.key == "spotify_refresh_token")
                    .first()
                )
                if row and row.value:
                    raw = row.value.strip()
                    if raw:
                        val = decrypt_token(raw, enc_key)
                        if val and val.strip():
                            return val.strip()
            finally:
                db.close()
        except Exception:
            pass
        p = self.spotify_user_token_path()
        if p.exists():
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
                t = j.get("refresh_token")
                if isinstance(t, str) and t.strip():
                    return t.strip()
            except Exception:
                pass
        return None

    def _get_db_access_token(self) -> str | None:
        """Read the access token stored in DB by the auth callback, if still valid."""
        try:
            from database import SessionLocal
            from models import AppSetting
            from security import decrypt_token

            enc_key = getattr(app_settings, "ENCRYPTION_KEY", None) or ""
            db = SessionLocal()
            try:
                token_row = db.query(AppSetting).filter(AppSetting.key == "spotify_access_token").first()
                expires_row = db.query(AppSetting).filter(AppSetting.key == "spotify_token_expires_at").first()
                if not token_row or not token_row.value:
                    return None
                token = decrypt_token(token_row.value.strip(), enc_key)
                if not token or not token.strip():
                    return None
                if expires_row and expires_row.value:
                    expires_at = int(expires_row.value)
                    if time.time() > expires_at:
                        return None
                return token.strip()
            finally:
                db.close()
        except Exception:
            return None

    async def get_spotify_user_access_token(self) -> str | None:
        refresh = self.get_spotify_refresh_token()
        cid = getattr(app_settings, "SPOTIFY_CLIENT_ID", "") or os.environ.get(
            "SPOTIFY_CLIENT_ID", ""
        )
        secret = getattr(app_settings, "SPOTIFY_CLIENT_SECRET", "") or os.environ.get(
            "SPOTIFY_CLIENT_SECRET", ""
        )
        if not refresh or not cid or not secret:
            return None
        now = time.time() * 1000
        if self.spotify_user_token and now < self.spotify_user_token_expires_at:
            return self.spotify_user_token
        import base64 as b64

        creds = b64.b64encode(f"{cid}:{secret}".encode()).decode()
        client = await self._http_client()
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh},
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if r.status_code != 200:
            self.spotify_user_token = None
            self.spotify_user_token_expires_at = 0
            # Refresh failed — fall back to access token stored in DB by auth callback
            return self._get_db_access_token()
        data = r.json()
        self.spotify_user_token = data["access_token"]
        ttl = (data.get("expires_in", 3600) - 60) * 1000
        self.spotify_user_token_expires_at = now + max(60000, ttl)
        if data.get("refresh_token"):
            try:
                p = self.spotify_user_token_path()
                stored = {}
                if p.exists():
                    stored = json.loads(p.read_text(encoding="utf-8"))
                stored["refresh_token"] = data["refresh_token"]
                p.write_text(json.dumps(stored, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to persist rotated refresh token: %s", e)
        return self.spotify_user_token


fingerprinter = Fingerprinter()
