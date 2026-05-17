"""zipDJ record-pool scraper.

Mirrors the structure of :mod:`pool_djcity` — same Protocol, same persistent
Playwright context layout under ``backend/cache/pool-state/zipdj/``, same
encrypted state mirror in ``pool_credentials``. The only intentional
divergence per pool is the :data:`SELECTORS` block; keep the rest in sync
with ``pool_djcity.py`` so a future refactor can DRY all three modules
behind a shared base without surprise behavioural drift.

Like DJCity, ``download()`` is a stub until the swap engine ships in step 6.
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

logger = logging.getLogger("cratedigger.upscale.pool.zipdj")

SLUG = "zipdj"
DISPLAY_NAME = "zipDJ"
RATE_LIMIT_MS = DEFAULT_RATE_LIMIT_MS

# Single source of truth for site-specific URLs and DOM selectors.
# zipDJ uses a slightly different layout from DJCity — these are best-effort
# starting points; first interactive login + search call will surface any
# selector misses with the selector key in the error message.
SELECTORS: dict[str, str] = {
    "login_url": "https://www.zipdj.com/login",
    "search_url_template": "https://www.zipdj.com/search?term={query}",
    "post_login_url_glob": "**/zipdj.com/**",
    "results_container": "div.search-results, table.tracks",
    "result_row": "tr.track-row, div.search-result",
    "row_hit_id_attr": "data-track-id",
    "row_title": ".track-title, td.title",
    "row_artist": ".track-artist, td.artist",
    "row_bitrate": ".bitrate, td.bitrate",
    "row_format": ".format, td.format",
    "row_duration": ".duration, td.length",
    "row_preview_audio": "audio[src], a.preview[href]",
    "logged_in_indicator": "a[href*='/account'], a[href*='/logout']",
}


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
    if not text:
        return 0
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


def _parse_duration(text: str) -> float | None:
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


class ZipDJScraper:
    slug = SLUG
    display_name = DISPLAY_NAME

    def __init__(self) -> None:
        self._guards = _ScraperGuards()
        self._guards.rate_limiter = pool_base.RateLimiter(RATE_LIMIT_MS)
        self._lock = asyncio.Lock()

    async def has_session(self) -> bool:
        return pool_state_file(self.slug).exists()

    async def clear_session(self) -> None:
        return None

    async def login_interactive(self) -> None:
        if not pool_base.pools_enabled():
            raise PoolDisabledError(
                "UPSCALE_POOLS_ENABLED is off — set the env var to allow live scraping"
            )

        from playwright.async_api import async_playwright

        state_dir = pool_state_dir(self.slug)

        async with self._lock:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                try:
                    page = await context.new_page()
                    await page.goto(SELECTORS["login_url"], wait_until="domcontentloaded")
                    try:
                        await page.wait_for_url(SELECTORS["post_login_url_glob"], timeout=300_000)
                    except Exception as e:
                        raise PoolAuthError(f"login window closed without completing: {e}") from e
                    try:
                        await page.wait_for_selector(
                            SELECTORS["logged_in_indicator"], timeout=15_000
                        )
                    except Exception as e:
                        raise PoolAuthError(
                            "login form completed but logged-in indicator wasn't found "
                            "— update SELECTORS['logged_in_indicator']"
                        ) from e
                    await context.storage_state(path=str(state_dir / "storage_state.json"))
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
            raise PoolAuthError("no zipDJ session — call /api/upscale/pools/zipdj/login first")

        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=str(state))
                try:
                    page = await context.new_page()
                    await page.goto(
                        SELECTORS["search_url_template"].format(query=query),
                        wait_until="domcontentloaded",
                    )

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
                            logger.warning("zipdj: row parse failed: %s", e)
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
            raise PoolUnavailableError(f"zipdj search failed: {e}") from e

    async def download(self, hit_id: str, dest_path: Path) -> PoolDownload:
        raise NotImplementedError(
            "ZipDJScraper.download lands with the swap engine in step 6 of the Upscale slice"
        )

    async def _parse_row(self, row: Any) -> _ParsedRow:
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


SCRAPER = ZipDJScraper()
pool_base.register(SCRAPER)
