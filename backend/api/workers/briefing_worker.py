"""
Briefing worker.

Background process responsible for automatically generating pre-match
briefings.

Flow:
    Redis match state
        ↓
    Check kickoff window + status
        ↓
    briefing_agent.generate()
        ↓
    Store result in Redis feed
        ↓
    HTTP briefing routes read the same data

This keeps automatic generation and manual API triggers consistent.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis

from agents import briefing_agent
from api.schemas.schema import MatchState

log = logging.getLogger(__name__)

INTERVAL = 300.0  # 5 min
KICKOFF_WINDOW = timedelta(hours=3)

# Keep in lockstep with api/routes/briefing_routes.py
FEED_CAP = 9
TTL_LIVE = 86_400


async def run(redis_client: aioredis.Redis) -> None:
    """Continuously scan active fixtures for briefing generation."""
    log.info("Briefing worker started — auto-trigger on NS + kickoff < 3h")
    while True:
        try:
            await _scan(redis_client)
        except asyncio.CancelledError:
            log.info("Briefing worker cancelled")
            return
        except Exception as exc:
            log.error(f"Briefing worker error: {exc}", exc_info=True)
        await asyncio.sleep(INTERVAL)


async def _scan(r: aioredis.Redis) -> None:
    """Inspect active fixtures and trigger briefings when they are due."""
    fixture_ids = await r.smembers("matches:active")
    if not fixture_ids:
        return
    for fid in fixture_ids:
        try:
            await _maybe_brief(r, fid)
        except Exception as exc:
            log.error(f"[{fid}] briefing auto-trigger error: {exc}", exc_info=True)


async def _maybe_brief(r: aioredis.Redis, fid: str) -> None:
    """Generate a briefing for one fixture if it is in the pre-match window."""
    state_raw = await r.get(f"match:{fid}:state")
    if not state_raw:
        return

    try:
        state = MatchState.model_validate_json(state_raw)
    except Exception as exc:
        log.warning(f"[{fid}] briefing worker parse error: {exc}")
        return

    if state.status_short != "NS":
        return
    if state.kickoff_time is None:
        return

    now = datetime.now(timezone.utc)
    ko = state.kickoff_time
    if ko.tzinfo is None:
        ko = ko.replace(tzinfo=timezone.utc)
    delta = ko - now
    if delta < timedelta(0) or delta > KICKOFF_WINDOW:
        return  # already kicked off, or too far out

    last_status = await r.get(f"match:{fid}:briefing:last_status")
    if last_status == "NS":
        return

    log.info(
        f"[{fid}] Auto-generating briefing — {state.home_name} vs "
        f"{state.away_name}, kickoff in {delta.total_seconds() / 60:.0f} min"
    )

    loop = asyncio.get_running_loop()
    text, model_label = await briefing_agent.generate(
        home_name=state.home_name,
        away_name=state.away_name,
        loop=loop,
    )

    entry = {
        "fixture_id": int(fid),
        "home_name": state.home_name,
        "away_name": state.away_name,
        "match_status": "NS",
        "briefing": text,
        "model": model_label,
        "source": ("Weaviate RAG + Groq 70B" if "RAG" in model_label else "Groq 70B"),
        "auto_triggered": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "generated",
    }

    pipe = r.pipeline(transaction=True)
    pipe.lpush(f"match:{fid}:briefing:feed", json.dumps(entry))
    pipe.ltrim(f"match:{fid}:briefing:feed", 0, FEED_CAP)
    pipe.expire(f"match:{fid}:briefing:feed", TTL_LIVE)
    pipe.setex(f"match:{fid}:briefing:last_status", TTL_LIVE, "NS")
    await pipe.execute()

    log.info(f"[{fid}] Auto briefing stored via {model_label} (feed key)")
