"""
Shared pub/sub-backed SSE generator.

"""

import json
import logging
from typing import Awaitable, Callable, Optional

import redis.asyncio as aioredis

log = logging.getLogger(__name__)


async def pubsub_sse(
    *,
    redis_client: aioredis.Redis,
    channel: str,
    key: str,
    event_name: str,
    is_disconnected: Callable[[], Awaitable[bool]],
    match_fixture_id: Optional[str] = None,
    emit_ok: Optional[Callable[[str], Awaitable[bool]]] = None,
    fallback_poll_s: float = 10.0,
    ping_every: int = 15,
):
    """Yield SSE events from a Redis-backed pub/sub stream."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    last_raw: Optional[str] = None
    tick = 0

    try:
        raw = await redis_client.get(key)
        if raw is not None:
            if emit_ok is None or await emit_ok(raw):
                last_raw = raw
                yield {"event": event_name, "data": raw}
        else:
            yield {
                "event": "waiting",
                "data": json.dumps({"message": f"waiting for {event_name} data"}),
            }

        while True:
            if await is_disconnected():
                break

            try:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=fallback_poll_s
                )
            except Exception as exc:
                log.warning(f"pubsub_sse[{channel}] get_message error: {exc}")
                msg = None

            if msg is not None:
                if match_fixture_id is not None:
                    try:
                        payload = json.loads(msg["data"])
                        if str(payload.get("fixture_id")) != str(match_fixture_id):
                            continue
                    except Exception:
                        pass

            raw = await redis_client.get(key)
            if raw is not None and raw != last_raw:
                if emit_ok is None or await emit_ok(raw):
                    last_raw = raw
                    yield {"event": event_name, "data": raw}

            tick += 1
            if tick % max(1, int(ping_every // max(fallback_poll_s, 1))) == 0:
                yield {"event": "heartbeat", "data": "{}"}

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
