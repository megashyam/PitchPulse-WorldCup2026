"""
Tactical fingerprint refresh worker.

This background worker maintains analytical tactical profiles for football
fixtures by periodically computing tactical fingerprints from canonical
MatchState data.

Unlike live event streams that require low-latency updates, tactical features
change gradually throughout a match. Therefore, this worker operates on a
slower cadence and focuses on consistency and cache convergence.

Pipeline:

    MatchState (Redis)
          ↓
    Tactical Feature Computation
          ↓
    Tactical Fingerprint Cache
          ↓
    API / Analytical Consumers


Responsibilities:
    - Refresh tactical fingerprints for active fixtures.
    - Backfill completed fixtures missing tactical analysis.
    - Coordinate asynchronous tactical computation.
    - Ensure Redis tactical caches converge as analytical indexes become
      available.

The worker separates expensive analytical enrichment from live match updates,
allowing real-time systems to remain responsive while deeper tactical analysis
runs independently.
"""

import asyncio
import logging

import redis.asyncio as aioredis

from api.routes.tactical import compute_and_cache
from api.schemas.schema import MatchState

log = logging.getLogger(__name__)
INTERVAL = 120.0


async def run(redis_client: aioredis.Redis) -> None:
    """
    Start the long-running tactical refresh worker.

    Periodically scans fixtures requiring tactical analysis and refreshes their
    tactical fingerprints.

    The worker runs independently from live event pipelines because tactical
    features are slower-moving analytical signals rather than real-time events.

    Failures are isolated per cycle so transient computation or storage issues
    do not terminate the background process.
    """
    log.info("Tactical worker started — refreshing every 120s")
    loop = asyncio.get_running_loop()
    while True:
        try:
            await _update_all(redis_client, loop)
        except asyncio.CancelledError:
            log.info("Tactical worker cancelled")
            return
        except Exception as exc:
            log.error(f"Tactical worker error: {exc}", exc_info=True)
        await asyncio.sleep(INTERVAL)


async def _update_all(r: aioredis.Redis, loop) -> None:
    """
    Identify fixtures requiring tactical computation and process them.

    Processes:
        - active fixtures requiring continuous tactical refreshes
        - completed fixtures missing tactical cache entries

    Completed fixtures are included only when no cached tactical fingerprint
    exists, allowing eventual consistency without repeatedly recomputing
    expensive analytical features.

    Fixtures are processed concurrently to support multiple simultaneous
    matches.
    """
    active_ids = set(await r.smembers("matches:active"))
    completed_ids = await r.smembers("matches:completed")

    fixtures_to_process = set(active_ids)
    for cid in completed_ids:
        if not await r.exists(f"match:{cid}:tactical"):
            fixtures_to_process.add(cid)

    fixture_ids = list(fixtures_to_process)
    if not fixture_ids:
        return

    results = await asyncio.gather(
        *[_update_fixture(r, fid, loop) for fid in fixture_ids],
        return_exceptions=True,
    )
    for fid, res in zip(fixture_ids, results):
        if isinstance(res, Exception):
            log.error(f"[{fid}] tactical update raised: {res}", exc_info=res)


async def _update_fixture(r: aioredis.Redis, fid: str, loop) -> None:
    """
    Compute and cache tactical features for a single fixture.

    Pipeline:
        1. Load canonical MatchState from Redis.
        2. Validate fixture state.
        3. Skip fixtures that have not started.
        4. Generate tactical fingerprint.
        5. Persist analytical results into cache.

    The function delegates feature generation to the tactical computation
    layer and focuses on orchestration, validation, and lifecycle management.
    """
    raw = await r.get(f"match:{fid}:state")
    if not raw:
        return

    try:
        state = MatchState.model_validate_json(raw)
    except Exception as exc:
        log.warning(f"[{fid}] tactical MatchState parse error: {exc}")
        return

    if state.status_short == "NS":
        return

    result = await compute_and_cache(r, fid, state, loop)
    if result.get("status") == "written":
        log.debug(f"[{fid}] tactical fingerprint refreshed")
