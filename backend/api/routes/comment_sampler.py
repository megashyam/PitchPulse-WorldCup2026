"""

Narrative comment sample storage and retrieval endpoints.

Provides worker-side storage utilities and a frontend polling endpoint for
recent social narrative samples associated with tracked topics.

Comment samples are stored in Redis as a rolling time window with TTL-based
expiration and bounded list size. This keeps the frontend focused on recent
live reactions while preventing unbounded storage growth.
"""

from __future__ import annotations
import json
import time
import logging

from fastapi import APIRouter, Request

router = APIRouter()
log = logging.getLogger(__name__)

SAMPLE_TTL = 600
SAMPLE_CAP = 19


async def store_comment_samples(redis_client, topic: str, samples: list[dict]) -> None:
    """
    Store recent narrative comment samples for a tracked topic.

    Intended to be called by social signal workers after collecting posts.
    Samples are appended to a Redis list, trimmed to a fixed maximum size,
    and given a short expiration window to maintain a live-reaction feed.

    Each sample should contain source metadata and optional timestamps.

    Args:
        redis_client: Async Redis client used for storage operations.
        topic: Narrative topic associated with the samples.
        samples: List of comment dictionaries containing fields such as
            text, source, author, permalink, and timestamp.

    Returns:
        None
    """
    key = f"narrative:{topic}:comments"
    for s in samples:
        s.setdefault("timestamp", time.time())
        await redis_client.lpush(key, json.dumps(s))
    await redis_client.ltrim(key, 0, SAMPLE_CAP)
    await redis_client.expire(key, SAMPLE_TTL)


@router.get("/{topic}/comments")
async def get_comment_samples(topic: str, request: Request):
    """
    Retrieve recent narrative comment samples for a topic.

    Returns the newest social samples stored in Redis. Used by the frontend
    to display live reaction bubbles and contextual narrative activity.

    Args:
        topic: Topic identifier whose comments should be retrieved.
        request: FastAPI request containing application state.

    Returns:
        dict: Topic metadata, sample count, and recent comment entries.
    """
    r = request.app.state.redis
    raw = await r.lrange(f"narrative:{topic}:comments", 0, SAMPLE_CAP)
    samples = [json.loads(s) for s in raw]
    return {"topic": topic, "count": len(samples), "samples": samples}
