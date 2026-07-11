"""Match state routes.

GET /matches/         list active and completed fixture IDs
GET /matches/summary  bulk fetch all active and recently completed states
GET /matches/{id}     fetch one fixture state

The summary endpoint exists so the match page can hydrate its full column set
in a single round trip instead of polling every fixture independently.
"""

import json

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/")
async def list_matches(request: Request):
    r = request.app.state.redis
    active = await r.smembers("matches:active")
    completed = await r.smembers("matches:completed")
    return {"fixtures": sorted(active | completed)}


@router.get("/summary")
async def match_summary(request: Request):
    """Return all active and recently completed fixtures in one response."""
    r = request.app.state.redis
    fixture_ids = await r.sunion("matches:active", "matches:completed")
    if not fixture_ids:
        return {"fixtures": []}

    keys = [f"match:{fid}:state" for fid in fixture_ids]
    raw_values = await r.mget(keys)

    fixtures = []
    for raw in raw_values:
        if raw is None:
            continue
        try:
            fixtures.append(json.loads(raw))
        except Exception:
            continue

    return {"fixtures": fixtures}


@router.get("/{fixture_id}")
async def get_match(fixture_id: str, request: Request):
    r = request.app.state.redis
    raw = await r.get(f"match:{fixture_id}:state")
    if not raw:
        raise HTTPException(
            status_code=404,
            detail=f"Fixture '{fixture_id}' not found. Is the hybrid producer running?",
        )

    return json.loads(raw)
