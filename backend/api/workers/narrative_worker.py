"""
Real-time narrative intelligence worker.

This background worker transforms statistical anomalies from live match data
into higher-level narrative insights using a hybrid ML + LLM pipeline.

The worker combines:
    - anomaly detection for identifying unusual match/tournament patterns
    - comment sample aggregation for contextual signals
    - LLM-based narrative arc generation
    - Redis-backed caching and pub/sub distribution

Pipeline:

    Live Data Sources
          ↓
    Narrative Spike Detector
          ↓
    Trending / Spike Detection
          ↓
    Narrative Arc Agent
          ↓
    Redis Narrative Cache
          ↓
    API / Streaming Consumers


Responsibilities:
    - Periodically execute narrative anomaly detection.
    - Maintain tournament-wide trending snapshots.
    - Generate human-readable narrative explanations.
    - Persist spike histories and latest insights.
    - Broadcast new narrative events through Redis pub/sub.

Redis storage:
    narrative:trending:latest
        Current tournament-wide narrative ranking.

    narrative:spike:{id}
        Individual anomaly-driven narrative.

    narrative:spikes:feed
        Rolling historical narrative stream.

    narrative:stream:latest
        Most recent narrative event.

Designed for continuous async operation with independent failure handling
between detection, generation, and persistence stages.
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from agents import narrative_arc_agent
from agents.narrative_spike_detector import NarrativeSpike, get_detector
from api.routes.narrative_comments import store_comment_samples

log = logging.getLogger(__name__)
INTERVAL = 60.0
ARC_TOP_N = 6


async def run(redis_client: aioredis.Redis) -> None:
    """
    Start the long-running narrative intelligence worker.

    Executes the narrative detection pipeline at a fixed interval and maintains
    the detector lifecycle for the lifetime of the application.

    Each cycle:
        1. Detects emerging narrative spikes.
        2. Refreshes trending narratives.
        3. Generates AI narrative explanations.
        4. Updates Redis caches and notifications.

    Individual failures are isolated so one failed generation or storage
    operation does not terminate the worker.
    """
    log.info("Narrative worker started — IsolationForest spike detection every 60s")
    loop = asyncio.get_running_loop()
    detector = get_detector()

    while True:
        try:
            await _tick(redis_client, loop, detector)
        except asyncio.CancelledError:
            log.info("Narrative worker cancelled")
            return
        except Exception as exc:
            log.error(f"Narrative worker error: {exc}", exc_info=True)
        await asyncio.sleep(INTERVAL)


async def _store_comment_samples_for_all_topics(r: aioredis.Redis, detector) -> None:
    """
    Persist recent contextual samples collected by the narrative detector.

    Stores representative source comments associated with tracked topics so
    downstream APIs can provide evidence and context behind detected trends.

    Failures for individual topics are ignored to prevent one unavailable
    source from affecting the complete narrative pipeline.
    """
    stored_count = 0
    for topic in detector.topics:
        try:
            samples = detector.get_last_samples(topic)
            if samples:
                await store_comment_samples(r, topic, samples)
                stored_count += len(samples)
        except Exception as e:
            log.debug(f"Comment sample storage failed for '{topic}': {e}")

    if stored_count:
        log.info(
            f"Narrative worker: stored {stored_count} comment samples across topics"
        )


async def _add_arcs_to_top_trending(
    snapshot: list, loop: asyncio.AbstractEventLoop
) -> None:
    """
    Generate narrative explanations for the highest-priority trending topics.

    Converts detector-generated trending rows into NarrativeSpike objects and
    enriches them using the narrative arc agent.

    Only the top-ranked topics are processed to control LLM inference cost
    while keeping the UI focused on the most significant stories.
    """
    for row in snapshot[:ARC_TOP_N]:
        try:
            spike = NarrativeSpike(
                spike_id=row["spike_id"],
                topic=row["topic"],
                tick=row["tick"],
                severity=row["severity"],
                sources=row["sources"],
                source_names=row["source_names"],
                summary=row["summary"],
                timestamp=row["timestamp"],
            )
            row["arc"] = await narrative_arc_agent.synthesise(spike, loop)
        except Exception as exc:
            topic_name = row.get("topic")
            log.debug(f"trending arc synthesis failed for {topic_name}: {exc}")


async def _tick(r: aioredis.Redis, loop: asyncio.AbstractEventLoop, detector) -> None:
    """
    Execute one complete narrative intelligence refresh cycle.

    Processing stages:

        1. Run anomaly detection over tracked topics.
        2. Persist supporting comment samples.
        3. Refresh tournament trending rankings.
        4. Generate narrative arcs for important trends.
        5. Store detected spikes and notify subscribers.

    The pipeline separates:
        - detection (ML anomaly scoring)
        - interpretation (LLM narrative generation)
        - delivery (Redis cache and pub/sub)

    This allows each layer to fail independently while maintaining partial
    system availability.
    """
    spikes = await detector.tick(loop)

    await _store_comment_samples_for_all_topics(r, detector)

    try:
        snapshot = detector.trending(top_n=12)
        await _add_arcs_to_top_trending(snapshot, loop)
        await r.setex("narrative:trending:latest", 3_600, json.dumps(snapshot))
    except Exception as exc:
        log.debug(f"trending snapshot failed: {exc}")

    if not spikes:
        return

    for spike in spikes:
        try:
            arc = await narrative_arc_agent.synthesise(spike, loop)
            spike.arc = arc
        except Exception as e:
            log.warning(f"Arc synthesis failed for {spike.spike_id}: {e}")
            spike.arc = None

        spike_dict = spike.to_dict()
        spike_json = json.dumps(spike_dict)

        await r.setex(f"narrative:spike:{spike.spike_id}", 86_400, spike_json)
        await r.lpush("narrative:spikes:feed", spike_json)
        await r.ltrim("narrative:spikes:feed", 0, 49)
        await r.expire("narrative:spikes:feed", 86_400)
        await r.setex("narrative:stream:latest", 3_600, spike_json)

        notif = json.dumps(
            {
                "spike_id": spike.spike_id,
                "topic": spike.topic,
                "severity": spike.severity,
            }
        )
        await r.publish("narrative_spike", notif)

        log.info(
            f"Narrative spike stored: {spike.topic} id={spike.spike_id} "
            f"severity={spike.severity:.2f}"
        )
