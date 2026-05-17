"""Pool orchestrator — DJCity-first fallback chain across registered scrapers.

When a candidate library file needs an upscale, the orchestrator queries
pools in priority order (DJCity → zipDJ → BPM Supreme by default) and
returns the **first pool** that yields ≥ 1 hit. Subsequent pools in the
chain aren't queried — saves time and respects per-site rate limits.

What this module owns:

- Pool priority order. Configurable via the ``upscale_pool_priority``
  AppSetting (comma-separated slugs); defaults to the plan's order.
- Per-pool failure isolation. A scraper raising ``PoolUnavailableError``
  / ``PoolAuthError`` is recorded as a `tried` entry with an `error`
  string but does NOT short-circuit the chain — we keep falling forward
  to the next pool.
- ``OrchestratorResult`` with ``tried[]`` + ``served_by`` fields. The
  frontend uses these to render the "DJCity ▸ zipDJ ▸ BPM Supreme"
  fallback chevron on the search row.

What this module does NOT own (lives elsewhere):

- Phase 3 confidence scoring + ranking — that's the AI slice's
  ``services.matching.decide.evaluate_swap`` hook in step 6.3. The
  orchestrator surfaces every hit from the winning pool unranked;
  the AI slice plugs in later.
- Choosing *which* hit to act on. The router stores all returned hits
  as ``upscale_matches`` rows with ``status='candidate'``; the founder
  confirms one through the UI in Phase 1, the AI slice auto-confirms
  high-confidence ones in Phase 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from models import AppSetting

# Import concrete scrapers so each one registers on module load. The router
# already imports them too, but importing them here as well makes this module
# usable standalone (e.g. from tests) without a roundabout import chain.
from . import (
    pool_base,
    pool_bpmsupreme,  # noqa: F401
    pool_djcity,  # noqa: F401
    pool_zipdj,  # noqa: F401
)
from .pool_base import (
    PoolAuthError,
    PoolDisabledError,
    PoolHit,
    PoolUnavailableError,
)

logger = logging.getLogger("cratedigger.upscale.orchestrator")

# Default order. Phase-1 chooses DJCity first because the founder reports
# the most accurate metadata there for the kind of tracks they work with.
DEFAULT_PRIORITY = ("djcity", "zipdj", "bpmsupreme")
SETTING_PRIORITY = "upscale_pool_priority"


@dataclass(frozen=True)
class TriedPool:
    """One row in :class:`OrchestratorResult.tried`. ``error`` is empty on
    a clean attempt (hits returned or empty list); set to the exception
    string when the pool raised."""

    slug: str
    hits_count: int
    error: str = ""


@dataclass
class OrchestratorResult:
    tried: list[TriedPool] = field(default_factory=list)
    served_by: str = ""  # slug of the pool whose hits we're returning, "" if none
    hits: list[PoolHit] = field(default_factory=list)


def _priority(db: Session) -> tuple[str, ...]:
    """Pool slugs in fallback order. Stored as a comma-separated AppSetting
    so the founder can re-rank without a deploy."""
    row = db.query(AppSetting).filter(AppSetting.key == SETTING_PRIORITY).first()
    if row and row.value:
        slugs = tuple(s.strip() for s in row.value.split(",") if s.strip())
        if slugs:
            return slugs
    return DEFAULT_PRIORITY


async def search(db: Session, query: str, *, limit: int = 25) -> OrchestratorResult:
    """Walk the priority chain, return the first non-empty hit list.

    Each pool that errors contributes a ``TriedPool`` row but does not
    abort the chain — we keep trying until we find hits or exhaust the
    list. If every pool errors *or* every pool returns empty, the
    response has ``served_by=""`` and ``hits=[]``; the FE renders a
    "no results" state with the per-pool error summary.
    """
    result = OrchestratorResult()
    if not query.strip():
        return result

    for slug in _priority(db):
        scraper = pool_base.get_scraper(slug)
        if scraper is None:
            logger.warning("orchestrator: unknown pool slug in priority: %s", slug)
            result.tried.append(TriedPool(slug=slug, hits_count=0, error="unknown pool"))
            continue

        try:
            hits = await scraper.search(query, limit=limit)
        except PoolDisabledError as e:
            # Feature flag off — every pool will fail the same way; surface
            # the message on the first one and stop (no point hammering).
            result.tried.append(TriedPool(slug=slug, hits_count=0, error=str(e)))
            logger.info("orchestrator: pools disabled — stopping chain at %s", slug)
            break
        except (PoolAuthError, PoolUnavailableError) as e:
            # Skip this pool, keep falling forward.
            result.tried.append(TriedPool(slug=slug, hits_count=0, error=str(e)))
            logger.info("orchestrator: %s failed (%s) — falling through", slug, e)
            continue
        except Exception as e:  # noqa: BLE001 — defensive: don't let a single pool kill the chain
            logger.exception("orchestrator: %s raised unexpectedly", slug)
            result.tried.append(TriedPool(slug=slug, hits_count=0, error=str(e)))
            continue

        result.tried.append(TriedPool(slug=slug, hits_count=len(hits), error=""))
        if hits:
            result.served_by = slug
            result.hits = hits
            return result

    return result
