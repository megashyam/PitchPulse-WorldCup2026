"""
Tactical fingerprint routes.

These endpoints expose the cached match for a fixture and a token-gated
manual refresh path. The tactical fingerprint is slow-moving and backed by
Weaviate, so the route reads from Redis first and only recomputes when a
worker or explicit trigger asks for a refresh.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from agents import tactical_agent
from agents.weaviate_client import get_weaviate_client, TACTICAL_PROFILES
from api.routes._security import require_trigger_token
from api.schemas.event_types import COMPLETED_STATUSES, LIVE_STATUSES
from api.schemas.schema import MatchState

router = APIRouter()
log = logging.getLogger(__name__)

CACHE_TTL = 600


async def compute_and_cache(r, fixture_id: str, state: MatchState, loop) -> dict:
    """Compute fresh tactical matches for both teams and cache the result."""
    home_match, away_match = await asyncio.gather(
        tactical_agent.match_team(state, "home", loop),
        tactical_agent.match_team(state, "away", loop),
    )

    if home_match is None and away_match is None:
        wv = get_weaviate_client()
        indexed_count = wv.get_count(TACTICAL_PROFILES) if wv.ready else 0
        reason = (
            "weaviate_unavailable"
            if not wv.ready
            else (
                "indexing_in_progress"
                if indexed_count == 0
                else "no_match_above_threshold"
            )
        )
        return {
            "status": "skipped",
            "reason": reason,
            "indexed_count": indexed_count,
        }

    result = {
        "fixture_id": int(fixture_id),
        "home_name": state.home_name,
        "away_name": state.away_name,
        "home": home_match,
        "away": away_match,
        "source": "TacticalProfiles · cosine match",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    await r.setex(f"match:{fixture_id}:tactical", CACHE_TTL, json.dumps(result))
    log.info(f"[{fixture_id}] Tactical fingerprint cached")
    return {"status": "written", "result": result}


@router.get("/{fixture_id}/tactical")
async def get_tactical(fixture_id: str, request: Request):
    """Return the cached tactical fingerprint for a fixture."""
    r = request.app.state.redis
    raw = await r.get(f"match:{fixture_id}:tactical")
    if not raw:
        state_raw = await r.get(f"match:{fixture_id}:state")
        if state_raw:
            try:
                state = MatchState.model_validate_json(state_raw)
                if (
                    state.status_short not in LIVE_STATUSES
                    and state.status_short not in COMPLETED_STATUSES
                ):
                    return {
                        "fixture_id": int(fixture_id),
                        "status": "not_started",
                        "message": "Tactical fingerprints begin at kickoff.",
                    }
            except Exception:
                pass
        wv = get_weaviate_client()
        indexed_count = wv.get_count(TACTICAL_PROFILES) if wv.ready else 0
        message = (
            "TacticalProfiles is still being indexed in the background "
            "(this takes a few minutes on first run) — check back shortly."
            if indexed_count == 0
            else "No tactical fingerprint yet — the background worker refreshes "
            "this every ~2 minutes."
        )
        return {
            "fixture_id": int(fixture_id),
            "status": "pending",
            "message": message,
        }
    return json.loads(raw)


@router.api_route(
    "/{fixture_id}/tactical/trigger",
    methods=["GET", "POST"],
    dependencies=[Depends(require_trigger_token)],
)
async def trigger_tactical(fixture_id: str, request: Request):
    """Force an immediate tactical refresh for a fixture."""
    r = request.app.state.redis
    state_raw = await r.get(f"match:{fixture_id}:state")
    if not state_raw:
        raise HTTPException(
            404, f"No match state for fixture {fixture_id}. Is the producer running?"
        )

    state = MatchState.model_validate_json(state_raw)
    loop = asyncio.get_running_loop()
    return await compute_and_cache(r, fixture_id, state, loop)
