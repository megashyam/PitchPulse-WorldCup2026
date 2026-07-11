"""
Tournament prediction routes.

The prediction API is deliberately split into a trigger endpoint, a status
endpoint, and cache-backed read endpoints. That separation keeps the heavy
Monte Carlo simulation off the request path and makes cross-worker coordination
safe by storing the simulation state in Redis rather than process memory.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from api.schemas.predict import (
    SimStatus,
    SimTriggerResponse,
    TeamPrediction,
    TournamentPrediction,
)
from ml.executors import SIM_EXECUTOR
from ml.odds_api_client import get_oddsapi_client
from ml.tournament_sim import SimResult, run_simulation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/predict", tags=["predict"])

REDIS_KEY = "predict:tournament:latest"
REDIS_TTL = 86_400

STATUS_KEY = "predict:sim:status"
STATUS_TTL = 900


_latest_result: Optional[TournamentPrediction] = None


async def _get_status(r) -> SimStatus:
    raw = await r.get(STATUS_KEY)
    if not raw:
        return SimStatus(status="idle")
    return SimStatus(**json.loads(raw))


async def _set_status(r, status: SimStatus) -> None:
    await r.setex(STATUS_KEY, STATUS_TTL, status.model_dump_json())


@router.post("/simulate", response_model=SimTriggerResponse)
async def trigger_simulation(request: Request, n_sims: int = 50_000):
    """Kick off a full tournament simulation and return a tracking id."""
    r = request.app.state.redis
    current = await _get_status(r)

    if current.status == "running":
        raise HTTPException(status_code=409, detail="Simulation already running")

    n_sims = max(1_000, min(100_000, n_sims))
    sim_id = str(uuid.uuid4())[:8]

    await _set_status(
        r,
        SimStatus(
            status="running", sim_id=sim_id, started_at=datetime.now(timezone.utc)
        ),
    )
    logger.info(f"Simulation triggered: sim_id={sim_id}, n_sims={n_sims}")

    asyncio.create_task(_run_and_store(r, sim_id, n_sims))

    return SimTriggerResponse(
        accepted=True,
        message=f"Simulation started ({n_sims:,} runs). Poll /predict/status.",
        sim_id=sim_id,
    )


@router.get("/status", response_model=SimStatus)
async def get_status(request: Request):
    """Return the current simulation status."""
    return await _get_status(request.app.state.redis)


@router.get("/tournament", response_model=TournamentPrediction)
async def get_tournament(request: Request):
    """Return the latest tournament prediction, auto-triggering if empty."""
    global _latest_result

    if _latest_result is not None:
        return _latest_result

    r = request.app.state.redis
    raw = await r.get(REDIS_KEY)
    if raw:
        data = json.loads(raw)
        _latest_result = TournamentPrediction(**data)
        return _latest_result

    current = await _get_status(r)
    if current.status != "running":
        sim_id = str(uuid.uuid4())[:8]
        await _set_status(
            r,
            SimStatus(
                status="running", sim_id=sim_id, started_at=datetime.now(timezone.utc)
            ),
        )
        asyncio.create_task(_run_and_store(r, sim_id, 50_000))

    raise HTTPException(
        status_code=202,
        detail="No simulation results yet. Simulation started — poll /predict/status.",
    )


@router.get("/team/{name}", response_model=TeamPrediction)
async def get_team(name: str, request: Request):
    """Return the prediction entry for a single team name."""
    pred = await get_tournament(request)
    team = next((t for t in pred.teams if t.name.lower() == name.lower()), None)
    if team is None:
        raise HTTPException(status_code=404, detail=f"Team '{name}' not found")
    return team


async def _run_and_store(redis, sim_id: str, n_sims: int) -> None:
    """Run the simulation, persist the result, and refresh the cache."""
    global _latest_result

    try:
        betfair = get_oddsapi_client()
        betfair_odds = await betfair.get_all_odds()

        loop = asyncio.get_running_loop()
        result: SimResult = await loop.run_in_executor(
            SIM_EXECUTOR,
            lambda: run_simulation(betfair_odds=betfair_odds, n_sims=n_sims),
        )

        pred = TournamentPrediction(
            sim_id=sim_id,
            n_sims=result.n_sims,
            elapsed_s=result.elapsed_s,
            run_at=datetime.now(timezone.utc),
            teams=[TeamPrediction.from_result(t) for t in result.teams],
            status="complete",
        )

        await redis.setex(REDIS_KEY, REDIS_TTL, pred.model_dump_json())
        _latest_result = pred
        await _set_status(redis, SimStatus(status="complete", sim_id=sim_id))
        logger.info(
            f"Simulation complete: sim_id={sim_id}, elapsed={result.elapsed_s}s"
        )

        await _push_sse_update(redis, sim_id, result.elapsed_s)

    except Exception as exc:
        logger.exception(f"Simulation failed: {exc}")
        await _set_status(
            redis, SimStatus(status="error", sim_id=sim_id, error=str(exc))
        )


async def _push_sse_update(redis, sim_id: str, elapsed_s: float) -> None:
    payload = json.dumps(
        {
            "type": "prediction_update",
            "sim_id": sim_id,
            "elapsed_s": elapsed_s,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    await redis.publish("prediction_update", payload)
