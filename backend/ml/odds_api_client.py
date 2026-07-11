"""
Odds API integration layer for live market-based tournament priors.

This module provides asynchronous access to external football betting markets
and exposes normalized decimal odds consumed by downstream probability models.

The client preserves the existing Betfair-style interface while adding:
    - API-based odds retrieval
    - TTL caching
    - request coalescing
    - transient failure recovery
    - free-tier usage protection


Pipeline:

    External Odds Provider
            ↓
    Odds Normalization
            ↓
    Cached Market Snapshot
            ↓
    Probability Calibration
            ↓
    Tournament Simulation


Core responsibilities:
    - Retrieve live head-to-head market odds.
    - Aggregate bookmaker prices into consensus estimates.
    - Maintain cached odds snapshots.
    - Prevent excessive API requests.
    - Provide fallback behavior during provider failures.


Raw decimal odds are intentionally preserved at this layer so downstream
components can apply probability transformations such as de-vigging and
market calibration consistently.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, Optional, Tuple

import httpx

log = logging.getLogger(__name__)

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "soccer_fifa_world_cup"
CACHE_TTL = float(os.getenv("ODDS_CACHE_TTL", "900"))

# (home_name, away_name) -> (decimal_home, decimal_draw, decimal_away)
OddsMap = Dict[Tuple[str, str], Tuple[float, float, float]]


async def _fetch_odds() -> Optional[OddsMap]:
    """
    Fetch and normalize live football market odds from the external provider.

    Retrieves head-to-head markets across available bookmakers and aggregates
    multiple prices into a single consensus decimal odds estimate per fixture.

    The function distinguishes between:
        - empty markets: valid response with no available odds
        - failed requests: unavailable provider response

    This distinction allows the cache layer to decide whether stale data
    should be retained.

    Returns:
        OddsMap containing:

            {
                (home_team, away_team):
                    (
                        home_decimal_odds,
                        draw_decimal_odds,
                        away_decimal_odds
                    )
            }

        Returns:
            - Empty dictionary when odds are unavailable or API key is missing.
            - None when the provider request fails.
    """
    if not ODDS_API_KEY:
        log.debug("No ODDS_API_KEY set — Elo priors will be used for all matches")
        return {}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ODDS_API_BASE}/sports/{SPORT_KEY}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "us,eu",
                    "markets": "h2h",
                    "oddsFormat": "decimal",
                },
            )
            r.raise_for_status()
            events = r.json()
            log.info(
                "Odds API: %s used / %s remaining this month",
                r.headers.get("x-requests-used", "?"),
                r.headers.get("x-requests-remaining", "?"),
            )
    except httpx.HTTPStatusError as exc:
        log.warning(f"Odds API HTTP error {exc.response.status_code}: {exc}")
        return None
    except Exception as exc:
        log.warning(f"Odds API error: {exc}")
        return None

    odds_map: OddsMap = {}
    for event in events:
        home = (event.get("home_team") or "").strip()
        away = (event.get("away_team") or "").strip()
        if not home or not away:
            continue

        home_prices, draw_prices, away_prices = [], [], []
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                by_name = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                hp, dp, ap = by_name.get(home), by_name.get("Draw"), by_name.get(away)
                if hp and dp and ap and min(hp, dp, ap) > 1.0:  # decimal odds > 1.0
                    home_prices.append(hp)
                    draw_prices.append(dp)
                    away_prices.append(ap)

        if not home_prices:
            continue

        # Keep raw decimal odds here; de-vigging happens downstream.
        odds_map[(home, away)] = (
            round(sum(home_prices) / len(home_prices), 4),
            round(sum(draw_prices) / len(draw_prices), 4),
            round(sum(away_prices) / len(away_prices), 4),
        )

    log.info(f"Odds API: loaded {len(odds_map)} match odds")
    return odds_map


class _OddsApiClient:
    """
    Asynchronous TTL-cached client for external market odds.

    Provides a stable interface for downstream systems while abstracting
    provider-specific API communication and cache management.

    Design features:
        - In-memory TTL caching reduces API usage.
        - Async locking prevents duplicate concurrent refresh requests.
        - Previous successful snapshots remain available during outages.

    The client intentionally returns normalized raw odds rather than
    probabilities so downstream calibration layers remain independent.
    """

    def __init__(self) -> None:
        self._cache: Optional[OddsMap] = None
        self._cached_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_all_odds(self) -> OddsMap:
        """
        Retrieve the latest available odds snapshot.

        Uses a TTL-based cache strategy:

            1. Serve existing cache when still valid.
            2. Acquire refresh lock after expiration.
            3. Fetch updated market data.
            4. Replace cache only on successful retrieval.
            5. Serve stale data during transient provider failures.


        This approach minimizes API usage while maintaining availability for
        downstream prediction pipelines.

        Returns:
            Dictionary mapping fixtures to normalized decimal odds:

                {
                    (home_team, away_team):
                        (home_odds, draw_odds, away_odds)
                }
        """
        now = time.monotonic()
        if self._cache is not None and now - self._cached_at < CACHE_TTL:
            return self._cache

        async with self._lock:
            now = time.monotonic()
            if self._cache is not None and now - self._cached_at < CACHE_TTL:
                return self._cache

            fresh = await _fetch_odds()
            if fresh is not None:
                self._cache = fresh
                self._cached_at = now
            elif self._cache is not None:
                log.warning("Odds API fetch failed — serving stale cached odds")
            else:
                self._cache = {}
                self._cached_at = now
        return self._cache or {}


_singleton = _OddsApiClient()


def get_oddsapi_client() -> _OddsApiClient:
    """Drop-in replacement for the original get_betfair_client()."""
    return _singleton
