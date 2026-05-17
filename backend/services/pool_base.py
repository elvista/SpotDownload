"""Shared scaffolding for record-pool scrapers (DJCity, zipDJ, BPM Supreme).

A "pool" is one of the subscription record-pool sites a DJ uses to source
higher-bitrate replacements for low-bitrate library files. Each pool has its
own DOM, login flow, and download semantics, so every pool lives in its own
module (``pool_djcity.py``, etc.) and implements the :class:`PoolScraper`
protocol defined here.

This module owns the framework all scrapers share:

  - Public dataclasses (``PoolHit``, ``PoolDownload``, ``PoolStatus``).
  - Exceptions (``PoolAuthError``, ``PoolUnavailableError``,
    ``PoolDisabledError``).
  - Rate-limit gate (``RateLimiter``) and consecutive-error circuit breaker
    (``CircuitBreaker``).
  - State persistence: encrypted Playwright storage state, stored on disk
    plus a record in ``pool_credentials`` so we can show "connected? when?"
    from the API.
  - Feature flag (``UPSCALE_POOLS_ENABLED``) that gates *all* live network
    calls — the section can ship to ``main`` with this off so tests don't
    need a real browser.

Concrete scrapers must keep their per-site CSS / XPath / URL strings in a
single module-level ``SELECTORS`` constant so a DOM change becomes a
one-file PR.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from config import settings as app_config
from models import PoolCredential
from security import decrypt_token, encrypt_token

logger = logging.getLogger("cratedigger.upscale.pool")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
POOL_STATE_DIR = BACKEND_ROOT / "cache" / "pool-state"

# Per-pool minimum delay between scraper requests. The plan calls for 750 ms;
# concrete scrapers may override via ``RATE_LIMIT_MS`` on their class.
DEFAULT_RATE_LIMIT_MS = 750

# Trip the circuit breaker after this many consecutive errors on one scraper.
CIRCUIT_BREAKER_THRESHOLD = 3

# Cooldown before a tripped breaker accepts traffic again.
CIRCUIT_BREAKER_COOLDOWN_S = 60.0


# --- Feature flag ------------------------------------------------------------


def pools_enabled() -> bool:
    """Master switch for live pool scraping. Off by default in this PR.

    Wrap any code path that would actually launch Playwright in this check so
    CI never tries to spin up a browser.
    """
    raw = (os.environ.get("UPSCALE_POOLS_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# --- Exceptions --------------------------------------------------------------


class PoolError(RuntimeError):
    """Base for all pool-scraper errors."""


class PoolAuthError(PoolError):
    """Login is expired or never happened. The FE prompts re-login."""


class PoolUnavailableError(PoolError):
    """Pool DOM/network is broken right now. Retryable; not user-fixable."""


class PoolDisabledError(PoolError):
    """``UPSCALE_POOLS_ENABLED`` is off — refuse to make network calls."""


# --- Public dataclasses ------------------------------------------------------


@dataclass(frozen=True)
class PoolHit:
    """One search result from a record pool."""

    hit_id: str
    title: str
    artist: str
    bitrate_kbps: int
    format: str  # "mp3" | "aiff" | "wav" | "flac" | ...
    duration_s: float | None = None
    preview_url: str | None = None


@dataclass(frozen=True)
class PoolDownload:
    """Result of a successful pool download."""

    path: str
    bitrate_kbps: int
    sha256: str
    source_url: str


@dataclass
class PoolStatus:
    """JSON-serialisable status row exposed by ``GET /api/upscale/pools``."""

    slug: str
    display_name: str
    connected: bool
    last_login: str | None
    last_error: str
    rate_limited_until: str | None = None
    circuit_breaker_open: bool = False


# --- PoolScraper protocol ----------------------------------------------------

# A scraper is identified by its module-level ``slug`` and ``display_name``
# constants plus the async methods below. We use a Protocol (not an abstract
# base class) so each scraper can be a plain module function set if it wants
# to be — no inheritance required.


@runtime_checkable
class PoolScraper(Protocol):
    slug: str
    display_name: str

    async def login_interactive(self) -> None: ...
    async def search(self, query: str, *, limit: int = 25) -> list[PoolHit]: ...
    async def download(self, hit_id: str, dest_path: Path) -> PoolDownload: ...
    async def has_session(self) -> bool: ...
    async def clear_session(self) -> None: ...


# --- Rate limiter ------------------------------------------------------------


class RateLimiter:
    """Per-instance gate: ``await acquire()`` blocks until ``min_interval`` ms
    have elapsed since the previous call returned. Thread-safe via asyncio.Lock.
    """

    def __init__(self, min_interval_ms: int) -> None:
        self.min_interval_s = max(0, min_interval_ms) / 1000.0
        self._lock = asyncio.Lock()
        self._last_release: float = 0.0

    @property
    def next_available_at(self) -> float:
        """``time.monotonic`` value at which the gate is next open. Useful
        for status reporting."""
        return self._last_release + self.min_interval_s

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = (self._last_release + self.min_interval_s) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_release = time.monotonic()


# --- Circuit breaker ---------------------------------------------------------


class CircuitBreaker:
    """Open after :data:`CIRCUIT_BREAKER_THRESHOLD` consecutive errors;
    refuse traffic for :data:`CIRCUIT_BREAKER_COOLDOWN_S` seconds, then
    half-open (one trial call allowed)."""

    def __init__(
        self,
        threshold: int = CIRCUIT_BREAKER_THRESHOLD,
        cooldown_s: float = CIRCUIT_BREAKER_COOLDOWN_S,
    ) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._consecutive_errors = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if (time.monotonic() - self._opened_at) >= self.cooldown_s:
            # Half-open: let one call through.
            return False
        return True

    def record_success(self) -> None:
        self._consecutive_errors = 0
        self._opened_at = None

    def record_error(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.threshold:
            self._opened_at = time.monotonic()

    def guard(self) -> None:
        if self.is_open:
            raise PoolUnavailableError(
                f"circuit breaker open after {self._consecutive_errors} consecutive errors"
            )


# --- State persistence -------------------------------------------------------

# Playwright "storage state" is a JSON blob with cookies + localStorage. We
# keep one per pool. The blob is encrypted with Fernet using
# ``settings.ENCRYPTION_KEY``; the encrypted form is mirrored to the
# ``pool_credentials.state_blob`` column so the founder can wipe state via
# ``DELETE /api/upscale/pools/{slug}``. The on-disk copy is what Playwright
# actually loads at scrape time.


def pool_state_dir(slug: str) -> Path:
    d = POOL_STATE_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def pool_state_file(slug: str) -> Path:
    """Path to the decrypted storage_state.json Playwright reads from."""
    return pool_state_dir(slug) / "storage_state.json"


def write_pool_state(db: Session, slug: str, storage_state: dict[str, Any] | str) -> None:
    """Persist Playwright storage state for ``slug`` (encrypted on disk + DB)."""
    raw = (
        storage_state
        if isinstance(storage_state, str)
        else json.dumps(storage_state, separators=(",", ":"))
    )
    # On-disk: Playwright needs plaintext JSON to load it. We keep it under
    # ``backend/cache/pool-state/<slug>/`` so it's outside any frontend bundle
    # and gitignored by virtue of the cache directory.
    pool_state_file(slug).write_text(raw, encoding="utf-8")

    # DB: the encrypted form is the source of truth across machine moves and
    # the channel ``DELETE /pools/{slug}`` clears.
    encrypted = encrypt_token(raw, app_config.ENCRYPTION_KEY)
    row = db.query(PoolCredential).filter(PoolCredential.pool_slug == slug).first()
    if row is None:
        db.add(
            PoolCredential(
                pool_slug=slug,
                state_blob=encrypted,
                last_login=datetime.now(UTC),
                last_error="",
            )
        )
    else:
        row.state_blob = encrypted
        row.last_login = datetime.now(UTC)
        row.last_error = ""
    db.commit()


def restore_pool_state_to_disk(db: Session, slug: str) -> Path | None:
    """If the DB has a state row but the on-disk file is missing, decrypt
    and write it back. Returns the file path if state exists, else ``None``.

    This lets the founder move the install between machines: the DB carries
    the cookies, the disk cache is rehydrated on first run.
    """
    target = pool_state_file(slug)
    if target.exists():
        return target
    row = db.query(PoolCredential).filter(PoolCredential.pool_slug == slug).first()
    if row is None or not row.state_blob:
        return None
    raw = decrypt_token(row.state_blob, app_config.ENCRYPTION_KEY)
    if not raw:
        return None
    target.write_text(raw, encoding="utf-8")
    return target


def clear_pool_state(db: Session, slug: str) -> bool:
    """Wipe disk cache + DB row for ``slug``. Returns True if anything existed."""
    existed = False
    f = pool_state_file(slug)
    if f.exists():
        try:
            f.unlink()
            existed = True
        except OSError as e:
            logger.warning("clear_pool_state: failed to unlink %s: %s", f, e)
    row = db.query(PoolCredential).filter(PoolCredential.pool_slug == slug).first()
    if row is not None:
        db.delete(row)
        db.commit()
        existed = True
    return existed


def record_pool_error(db: Session, slug: str, error: str) -> None:
    row = db.query(PoolCredential).filter(PoolCredential.pool_slug == slug).first()
    if row is None:
        # No login row yet — surface the error but don't write a phantom credential row.
        return
    row.last_error = (error or "")[:500]
    db.commit()


# --- Registry ----------------------------------------------------------------

# Concrete scrapers register themselves on import (typically at the bottom of
# their module). The router queries this dict.

_REGISTRY: dict[str, PoolScraper] = {}


def register(scraper: PoolScraper) -> None:
    if not getattr(scraper, "slug", ""):
        raise ValueError("scraper has no slug")
    if scraper.slug in _REGISTRY:
        logger.debug("pool scraper %s already registered", scraper.slug)
        return
    _REGISTRY[scraper.slug] = scraper
    logger.info("registered pool scraper: %s", scraper.slug)


def get_scraper(slug: str) -> PoolScraper | None:
    return _REGISTRY.get(slug)


def all_scrapers() -> Iterable[PoolScraper]:
    return list(_REGISTRY.values())


# --- Helpers exposed to concrete scrapers ------------------------------------


@dataclass
class _ScraperGuards:
    """Per-instance state that concrete scrapers compose."""

    rate_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(DEFAULT_RATE_LIMIT_MS))
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)


def hit_to_dict(hit: PoolHit) -> dict[str, Any]:
    return asdict(hit)
