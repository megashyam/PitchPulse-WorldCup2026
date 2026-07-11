"""
Real-time match momentum refresh worker.

This background worker continuously computes live momentum signals for active
fixtures by combining canonical MatchState objects with the momentum model.

The worker provides a low-latency feature pipeline:

    Live Match Producer
            ↓
    Redis MatchState
            ↓
    Momentum Worker
            ↓
    Momentum Model
            ↓
    Redis Feature Cache + Pub/Sub
            ↓
    SSE / Frontend Consumers


Responsibilities:
    - Load active fixture states from Redis.
    - Maintain stateful momentum calculations across polling cycles.
    - Generate short-horizon goal probability estimates.
    - Persist momentum snapshots for downstream consumers.
    - Broadcast lightweight updates through Redis pub/sub.

Redis storage:
    match:{fixture_id}:momentum
        Latest momentum feature snapshot.

Pub/Sub:
    momentum_update
        Lightweight real-time update payload for streaming clients.

The worker is designed for continuous async execution with:
    - concurrent fixture processing
    - automatic stale-state cleanup
    - failure isolation between fixtures
    - lightweight model inference suitable for live systems
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from api.schemas.schema import MatchState
from ml import momentum_model

log = logging.getLogger(__name__)
INTERVAL = 30.0


async def run(redis_client: aioredis.Redis) -> None:
    """Entry point. Called once from lifespan, runs for the process lifetime."""
    log.info("Momentum worker started — updating every 30s")
    while True:
        try:
            await _update_all(redis_client)
        except asyncio.CancelledError:
            log.info("Momentum worker cancelled — shutting down")
            return
        except Exception as exc:
            log.error(f"Momentum worker error: {exc}", exc_info=True)
        await asyncio.sleep(INTERVAL)


async def _update_all(r: aioredis.Redis) -> None:
    """Process all fixtures currently in the matches:active set."""
    fixture_ids = list(await r.smembers("matches:active"))

    active = {str(fid) for fid in fixture_ids}
    for known in [k for k in list(momentum_model.states) if str(k) not in active]:
        momentum_model.clear_state(known)

    if not fixture_ids:
        return

    results = await asyncio.gather(
        *[_update_fixture(r, fid) for fid in fixture_ids],
        return_exceptions=True,
    )
    for fid, res in zip(fixture_ids, results):
        if isinstance(res, Exception):
            log.error(f"[{fid}] _update_fixture raised: {res}", exc_info=res)


async def _update_fixture(r: aioredis.Redis, fid_str: str) -> None:
    """Read MatchState → momentum_model.update() (pure CPU, <1ms) → write +
    publish."""
    raw = await r.get(f"match:{fid_str}:state")
    if not raw:
        return

    try:
        state = MatchState.model_validate_json(raw)
    except Exception as exc:
        log.warning(f"[{fid_str}] MatchState parse error: {exc}")
        return

    result = momentum_model.update(state)
    if result is None:
        momentum_model.clear_state(state.fixture_id)
        return

    result_json = json.dumps(result)
    await r.setex(f"match:{fid_str}:momentum", 3600, result_json)

    notif = json.dumps(
        {
            "fixture_id": result["fixture_id"],
            "home_momentum": result["home"]["momentum_score"],
            "away_momentum": result["away"]["momentum_score"],
            "home_goal_prob": result["home"]["goal_prob_5min"],
            "away_goal_prob": result["away"]["goal_prob_5min"],
            "elapsed": result["elapsed"],
        }
    )
    await r.publish("momentum_update", notif)

    log.debug(
        f"[{fid_str}] {result['home_name'][:10]:10s} "
        f"M={result['home']['momentum_score']:.2f} "
        f"G={result['home']['goal_prob_5min']:.3f} | "
        f"{result['away_name'][:10]:10s} "
        f"M={result['away']['momentum_score']:.2f} "
        f"G={result['away']['goal_prob_5min']:.3f}"
    )
