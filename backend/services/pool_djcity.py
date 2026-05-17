"""DJCity record-pool scraper.

Implements the :class:`pool_base.PoolScraper` protocol against djcity.com.
This is the first of three pools (zipDJ + BPM Supreme follow in step 4).

Network behaviour:

- A **persistent Playwright context** lives under
  ``backend/cache/pool-state/djcity/`` so cookies + localStorage survive
  process restarts. The plaintext ``storage_state.json`` Playwright reads
  is mirrored encrypted to ``pool_credentials.state_blob`` so it can move
  between machines and be cleared via ``DELETE /api/upscale/pools/djcity``.
- **First-time login is interactive**. We launch a *headed* Chromium
  window pointed at the DJCity login page; the founder logs in (Cloudflare,
  Captcha, 2FA — whatever the site asks). When the navigation lands back on
  the dashboard we capture storage state and shut the window. Subsequent
  scraping uses that state headlessly.
- **Search returns ``list[PoolHit]``**; bitrate + format are pulled per
  result. We deliberately do *not* call ``download()`` from this PR — that
  lands with the swap engine in step 6.

DOM selectors live in the :data:`SELECTORS` constant at the top. When
DJCity changes its markup, the fix is a one-PR edit to that dict and
nothing else in this file. Each scraper raises
:class:`PoolUnavailableError` if a *required* selector returns nothing,
which surfaces to the FE as a "scraper needs an update" banner with the
selector name attached so the next PR is easy to write.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import pool_base
from .pool_base import (
    DEFAULT_RATE_LIMIT_MS,
    PoolAuthError,
    PoolDisabledError,
    PoolDownload,
    PoolHit,
    PoolUnavailableError,
    _ScraperGuards,
    pool_state_dir,
    pool_state_file,
)

logger = logging.getLogger("cratedigger.upscale.pool.djcity")

SLUG = "djcity"
DISPLAY_NAME = "DJcity"
RATE_LIMIT_MS = DEFAULT_RATE_LIMIT_MS

# Single source of truth for site-specific URLs and DOM selectors.
# When djcity.com changes any of these, this dict is the only file that
# needs editing. Treat anything outside this block as site-agnostic.
SELECTORS: dict[str, str] = {
    # URLs
    "login_url": "https://www.djcity.com/login",
    "search_url_template": "https://www.djcity.com/search?q={query}",
    # Login completion: the URL Playwright watches for to know login finished.
    # If DJCity redirects somewhere different post-login, update this glob.
    "post_login_url_glob": "**/djcity.com/**",
    # Search results: container element + per-row sub-selectors. The container
    # selector returns N elements; each one is queried with the row-* keys.
    "results_container": "div.search-results, div[data-testid='search-results']",
    "result_row": "div.song-row, [data-testid='search-result-row']",
    "row_hit_id_attr": "data-song-id",
    "row_title": ".song-title, [data-testid='title']",
    "row_artist": ".artist-name, [data-testid='artist']",
    "row_bitrate": ".bitrate, [data-testid='bitrate']",
    "row_format": ".format, [data-testid='format']",
    "row_duration": ".duration, [data-testid='duration']",
    "row_preview_audio": "audio[src], a.preview[href]",
    # Logged-in indicator we look for to confirm session is fresh.
    "logged_in_indicator": ("a[href*='/account'], a[href*='/logout'], [data-testid='user-menu']"),
}


# Marker raised when SELECTORS clearly need updating because no required
# element matched. Kept distinct from a transient network failure.
class SelectorMissError(PoolUnavailableError):
    """A required SELECTORS entry returned no matches against the current DOM."""


@dataclass(frozen=True)
class _ParsedRow:
    hit_id: str
    title: str
    artist: str
    bitrate_kbps: int
    format: str
    duration_s: float | None
    preview_url: str | None


def _parse_bitrate(text: str) -> int:
    """``"320 kbps"`` → ``320``. Returns 0 if unparseable."""
    if not text:
        return 0
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


def _parse_duration(text: str) -> float | None:
    """``"3:24"`` → ``204.0`` seconds. Returns None on parse failure."""
    if not text:
        return None
    parts = text.strip().split(":")
    try:
        if len(parts) == 2:
            m, s = int(parts[0]), int(parts[1])
            return float(m * 60 + s)
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return float(h * 3600 + m * 60 + s)
    except ValueError:
        return None
    return None


class DJCityScraper:
    """Playwright-backed scraper. One instance per process is fine — the
    persistent context handles concurrency within a single browser.
    """

    slug = SLUG
    display_name = DISPLAY_NAME

    def __init__(self) -> None:
        self._guards = _ScraperGuards()
        self._guards.rate_limiter = pool_base.RateLimiter(RATE_LIMIT_MS)
        self._lock = asyncio.Lock()

    # --- Session helpers -----------------------------------------------------

    async def has_session(self) -> bool:
        """True if a storage_state.json exists on disk for this pool."""
        return pool_state_file(self.slug).exists()

    async def clear_session(self) -> None:
        # The router calls pool_base.clear_pool_state() which also wipes the
        # DB row. This method only handles the in-process side: nothing to do
        # here today because we don't hold a long-lived browser context.
        return None

    # --- Public scraper API --------------------------------------------------

    async def login_interactive(self) -> None:
        """Open a *headed* Chromium so the founder can log in by hand.

        Captures the resulting storage state to disk + DB. We don't try to
        automate the credential form: pools commonly add Cloudflare / Captcha
        and DJCity may roll 2FA. The cost of waiting for the founder once is
        much lower than the cost of an automated login that breaks silently.
        """
        if not pool_base.pools_enabled():
            raise PoolDisabledError(
                "UPSCALE_POOLS_ENABLED is off — set the env var to allow live scraping"
            )

        # Lazy import so module import doesn't try to find a browser when the
        # feature is disabled.
        from playwright.async_api import async_playwright

        state_dir = pool_state_dir(self.slug)

        async with self._lock:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                try:
                    page = await context.new_page()
                    await page.goto(SELECTORS["login_url"], wait_until="domcontentloaded")
                    # Wait until the URL settles on a logged-in path. We give
                    # the founder up to 5 minutes (Captcha + 2FA can be slow).
                    try:
                        await page.wait_for_url(SELECTORS["post_login_url_glob"], timeout=300_000)
                    except Exception as e:
                        raise PoolAuthError(f"login window closed without completing: {e}") from e

                    # Verify a logged-in indicator is visible before saving state.
                    try:
                        await page.wait_for_selector(
                            SELECTORS["logged_in_indicator"], timeout=15_000
                        )
                    except Exception as e:
                        raise PoolAuthError(
                            "login form completed but the logged-in indicator wasn't found "
                            "— update SELECTORS['logged_in_indicator']"
                        ) from e

                    storage_state = await context.storage_state(
                        path=str(state_dir / "storage_state.json")
                    )
                    # ``storage_state(path=...)`` writes the file already.
                    # We return so the router can mirror it encrypted to DB.
                    _ = storage_state  # silence unused-var lint
                finally:
                    await context.close()
                    await browser.close()

    async def search(self, query: str, *, limit: int = 25) -> list[PoolHit]:
        if not pool_base.pools_enabled():
            raise PoolDisabledError("UPSCALE_POOLS_ENABLED is off")
        if not query.strip():
            return []

        self._guards.breaker.guard()
        await self._guards.rate_limiter.acquire()

        state = pool_state_file(self.slug)
        if not state.exists():
            raise PoolAuthError("no DJCity session — call /api/upscale/pools/djcity/login first")

        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=str(state))
                try:
                    page = await context.new_page()
                    url = SELECTORS["search_url_template"].format(query=query)
                    await page.goto(url, wait_until="domcontentloaded")

                    container = await page.query_selector(SELECTORS["results_container"])
                    if container is None:
                        raise SelectorMissError(
                            "results_container missing — update SELECTORS['results_container']"
                        )

                    rows = await container.query_selector_all(SELECTORS["result_row"])
                    parsed: list[_ParsedRow] = []
                    for row in rows[:limit]:
                        try:
                            parsed.append(await self._parse_row(row))
                        except Exception as e:  # noqa: BLE001
                            logger.warning("djcity: row parse failed: %s", e)
                            continue

                    self._guards.breaker.record_success()
                    return [
                        PoolHit(
                            hit_id=r.hit_id,
                            title=r.title,
                            artist=r.artist,
                            bitrate_kbps=r.bitrate_kbps,
                            format=r.format,
                            duration_s=r.duration_s,
                            preview_url=r.preview_url,
                        )
                        for r in parsed
                    ]
                finally:
                    await context.close()
                    await browser.close()
        except (PoolAuthError, PoolDisabledError, SelectorMissError):
            self._guards.breaker.record_error()
            raise
        except Exception as e:  # noqa: BLE001
            self._guards.breaker.record_error()
            raise PoolUnavailableError(f"djcity search failed: {e}") from e

    async def download(self, hit_id: str, dest_path: Path) -> PoolDownload:
        """Download a single hit. Wired up in step 6 (swap engine) — placeholder here."""
        # We deliberately leave this unimplemented for the step-3 PR; the
        # swap engine PR will add it once the orchestrator + preview UI exist.
        # Raising a clear error is safer than returning a half-shape now.
        raise NotImplementedError(
            "DJCityScraper.download lands with the swap engine in step 6 of the Upscale slice"
        )

    # --- Row parsing helpers -------------------------------------------------

    async def _parse_row(self, row: Any) -> _ParsedRow:
        """Pull the five fields we care about out of one results row."""
        hit_id = await row.get_attribute(SELECTORS["row_hit_id_attr"])
        if not hit_id:
            raise SelectorMissError("row_hit_id_attr missing — update SELECTORS['row_hit_id_attr']")

        title = (await self._text(row, SELECTORS["row_title"])) or ""
        artist = (await self._text(row, SELECTORS["row_artist"])) or ""
        bitrate_text = (await self._text(row, SELECTORS["row_bitrate"])) or ""
        format_text = ((await self._text(row, SELECTORS["row_format"])) or "").lower().strip()
        duration_text = (await self._text(row, SELECTORS["row_duration"])) or ""

        preview_url: str | None = None
        preview_el = await row.query_selector(SELECTORS["row_preview_audio"])
        if preview_el is not None:
            preview_url = await preview_el.get_attribute("src") or await preview_el.get_attribute(
                "href"
            )

        return _ParsedRow(
            hit_id=hit_id.strip(),
            title=title.strip(),
            artist=artist.strip(),
            bitrate_kbps=_parse_bitrate(bitrate_text),
            format=format_text or "mp3",
            duration_s=_parse_duration(duration_text),
            preview_url=preview_url,
        )

    @staticmethod
    async def _text(row: Any, selector: str) -> str | None:
        el = await row.query_selector(selector)
        if el is None:
            return None
        return (await el.text_content()) or ""


# Register the singleton on import.
SCRAPER = DJCityScraper()
pool_base.register(SCRAPER)
