"""
Offline tactical intelligence indexing pipeline.

This module transforms raw StatsBomb event data into searchable tactical
fingerprints that power the live match intelligence system.

Pipeline:

    StatsBomb Events
            |
            |
    Tactical Feature Extraction
            |
            |
    Pressing Fingerprint
            |
            |
    Sentence Embedding Model
            |
            |
    Weaviate Vector Database
            |
            |
    Runtime Tactical Retrieval


Core responsibilities:
    - Extract team tactical characteristics from historical matches.
    - Compute pressing metrics such as PPDA and press intensity.
    - Capture spatial pressing behavior across pitch zones.
    - Generate natural-language tactical descriptions.
    - Embed and index tactical profiles for similarity search.


Feature engineering:

    PPDA:
        Measures defensive pressure by comparing opponent passes allowed
        against defensive actions performed.

    Spatial pressing:
        Analyzes where teams apply pressure using StatsBomb coordinates:

            Defensive Third | Middle Third | Attacking Third


The generated tactical fingerprints bridge offline historical analysis with
real-time match intelligence by allowing live team states to retrieve similar
historical tactical profiles.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict

import httpx
from sentence_transformers import SentenceTransformer

from agents.weaviate_client import (
    get_weaviate_client,
    TACTICAL_PROFILES,
)

log = logging.getLogger(__name__)

SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
COMPETITION_ID = 43  # FIFA World Cup
SEASON_IDS = [106, 3]  # 2022, 2018
MAX_MATCHES = 500

# Defensive-action event types that count toward PPDA denominator.
# StatsBomb: a Duel of sub-type Tackle, plus Interception / Block / Foul Committed.
DEF_ACTION_TYPES = {"Interception", "Block", "Foul Committed"}

# Pitch geometry
PITCH_X = 120.0
PRESS_LINE = 40.0  # standard PPDA boundary: actions/passes with x >= 40
MID_LINE = 40.0
ATT_LINE = 80.0


async def fetch_json(client: httpx.AsyncClient, url: str):
    r = await client.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def _zone(x: float) -> str:
    """
    Map StatsBomb pitch coordinates into tactical zones.

    The pitch is divided into three horizontal regions to capture where teams
    apply defensive pressure.

    Args:
        x:
            StatsBomb x-coordinate on a 120-unit pitch.

    Returns:
        Tactical zone label:
            - "def" : defensive third
            - "mid" : middle third
            - "att" : attacking third
    """
    if x < MID_LINE:
        return "def"
    if x < ATT_LINE:
        return "mid"
    return "att"


def _is_tackle(ev: dict) -> bool:
    """
    Determine whether a StatsBomb event represents a successful tackle.

    StatsBomb stores tackles as Duel events with a tackle subtype. This
    helper normalizes that representation for defensive-action counting.

    Args:
        ev:
            Raw StatsBomb event dictionary.

    Returns:
        True if the event is a tackle defensive action, otherwise False.
    """
    if (ev.get("type") or {}).get("name") != "Duel":
        return False
    dtype = (ev.get("duel") or {}).get("type") or {}
    return "Tackle" in (dtype.get("name") or "")


def _safe_ppda(passes: float, actions: float) -> float:
    """
    Compute PPDA while handling matches with no defensive actions.

    PPDA:
        opponent completed passes / defensive actions

    Lower PPDA values indicate more aggressive pressing.

    Args:
        passes:
            Number of opponent completed passes allowed inside the press zone.

        actions:
            Number of defensive actions performed inside the press zone.

    Returns:
        Calculated PPDA value capped at 50 for undefined cases.
    """
    if actions <= 0:
        return 50.0
    return round(passes / actions, 2)


def build_fingerprints(
    events: list,
    home: str,
    away: str,
    competition: str,
    season: str,
    match_id: str,
) -> list[dict]:
    """
    Generate tactical fingerprint documents for both teams in a match.

    Each fingerprint summarizes a team's tactical identity using:

        - PPDA pressing intensity
        - spatial pressing distribution
        - possession profile
        - shot volume
        - expected goals
        - pressure activity


    For each team:
        The opponent's completed passes in the team's pressing zones form the
        PPDA numerator, while defensive actions form the denominator.


    Args:
        events:
            Ordered StatsBomb event stream for a match.

        home:
            Home team name.

        away:
            Away team name.

        competition:
            Competition identifier.

        season:
            Season identifier.

        match_id:
            Unique match identifier.


    Returns:
        List of tactical fingerprint documents containing:

            properties:
                Metadata and numerical tactical features.

            embed_text:
                Natural-language representation used for vector embedding.
    """

    opp_passes = {home: defaultdict(float), away: defaultdict(float)}
    def_actions = {home: defaultdict(float), away: defaultdict(float)}

    poss_events = {home: 0, away: 0}
    shots = {home: 0, away: 0}
    xg = {home: 0.0, away: 0.0}

    pressures = {home: 0, away: 0}

    def opponent(t: str) -> str:
        return away if t == home else home

    for ev in events:
        team_name = (ev.get("team") or {}).get("name", "")
        if team_name not in (home, away):
            continue
        etype = (ev.get("type") or {}).get("name", "")
        loc = ev.get("location") or []
        x = float(loc[0]) if len(loc) >= 1 else None

        poss_events[team_name] += 1

        if etype == "Pass":
            completed = (ev.get("pass") or {}).get("outcome") is None
            if completed and x is not None:
                presser = opponent(team_name)

                x_press = PITCH_X - x
                if x_press >= PRESS_LINE:
                    opp_passes[presser][_zone(x_press)] += 1.0

        elif etype == "Shot":
            shots[team_name] += 1
            sx = (ev.get("shot") or {}).get("statsbomb_xg")
            if sx is not None:
                xg[team_name] += float(sx)

        is_def_action = etype in DEF_ACTION_TYPES or _is_tackle(ev)
        if is_def_action and x is not None and x >= PRESS_LINE:
            def_actions[team_name][_zone(x)] += 1.0

        if etype == "Pressure" and x is not None and x >= PRESS_LINE:
            pressures[team_name] += 1

    total_events = poss_events[home] + poss_events[away]

    docs = []
    for team in (home, away):
        opp = opponent(team)

        p_mid = opp_passes[team]["mid"]
        p_att = opp_passes[team]["att"]
        a_mid = def_actions[team]["mid"]
        a_att = def_actions[team]["att"]

        ppda_overall = _safe_ppda(p_mid + p_att, a_mid + a_att)
        ppda_mid = _safe_ppda(p_mid, a_mid)
        ppda_att = _safe_ppda(p_att, a_att)

        ppda_def = 50.0

        possession = (
            round(poss_events[team] / total_events * 100, 1) if total_events else 50.0
        )

        ppda_term = min(1.0, 8.0 / max(ppda_overall, 1.0))
        pressure_term = min(1.0, pressures[team] / 150.0)
        press_intensity = round(0.7 * ppda_term + 0.3 * pressure_term, 3)

        style = (
            "aggressive high press"
            if ppda_overall < 8
            else "selective mid-block" if ppda_overall < 13 else "passive low block"
        )
        where = "attacking third" if ppda_att <= ppda_mid else "middle third"

        content = (
            f"{competition} {season} · {team} vs {opp} · pressing fingerprint\n"
            f"Style: {style}, pressing primarily in the {where}.\n"
            f"PPDA overall {ppda_overall} (middle third {ppda_mid}, "
            f"attacking third {ppda_att}). "
            f"Lower PPDA means a more aggressive press.\n"
            f"Possession {possession:.0f}%, {shots[team]} shots, "
            f"{xg[team]:.2f} xG, {pressures[team]} pressing actions. "
            f"Press intensity index {press_intensity:.2f}."
        )

        docs.append(
            {
                "properties": {
                    "content": content,
                    "team": team,
                    "opponent": opp,
                    "match_id": match_id,
                    "competition": competition,
                    "season": season,
                    "ppda": ppda_overall,
                    "ppda_def_third": ppda_def,
                    "ppda_mid_third": ppda_mid,
                    "ppda_att_third": ppda_att,
                    "possession": possession,
                    "press_intensity": press_intensity,
                },
                # Text the embedding model sees. Keep it descriptive so the
                # runtime descriptor (also natural language) matches well.
                "embed_text": content,
            }
        )

    return docs


async def _index_all() -> int:
    """
    Execute the complete tactical indexing pipeline.

    Workflow:

        1. Load StatsBomb historical matches.
        2. Extract tactical fingerprints.
        3. Generate semantic embeddings.
        4. Insert vectors into Weaviate.


    Returns:
        Number of successfully inserted tactical profile documents.


    This function is reusable from:
        - CLI execution
        - application startup background indexing
    """
    wv = get_weaviate_client()
    if not wv.ready:
        log.error("Weaviate not ready — is the Docker container up on :8080?")
        return 0

    log.info("Loading all-MiniLM-L6-v2 embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    log.info("Embedding model ready")

    all_docs: list[dict] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": "wc2026-tactical-indexer/1.0"},
        follow_redirects=True,
    ) as http:
        matches = []
        for sid in SEASON_IDS:
            try:
                ms = await fetch_json(
                    http, f"{SB_BASE}/matches/{COMPETITION_ID}/{sid}.json"
                )
                matches.extend(ms)
                log.info(f"Season {sid}: {len(ms)} matches")
            except Exception as e:
                log.warning(f"Season {sid} failed: {e}")

        log.info(f"Processing up to {MAX_MATCHES} of {len(matches)} matches...")
        for i, m in enumerate(matches[:MAX_MATCHES]):
            match_id = str(m["match_id"])
            home = m["home_team"]["home_team_name"]
            away = m["away_team"]["away_team_name"]
            season = str(m.get("season", {}).get("season_name", ""))
            comp = m.get("competition", {}).get("competition_name", "WC")
            try:
                events = await fetch_json(http, f"{SB_BASE}/events/{match_id}.json")
                docs = build_fingerprints(events, home, away, comp, season, match_id)
                all_docs.extend(docs)
                log.info(f"  [{i+1:2d}] {home} vs {away}: {len(docs)} fingerprints")
            except Exception as e:
                log.warning(f"  [{i+1:2d}] {home} vs {away}: failed — {e}")

    log.info(f"\nTotal fingerprints to index: {len(all_docs)}")
    if not all_docs:
        log.warning("Nothing to index.")
        return 0

    log.info("Embedding and inserting into TacticalProfiles...")
    inserted = 0
    batch = 50
    for i in range(0, len(all_docs), batch):
        chunk = all_docs[i : i + batch]
        vectors = model.encode(
            [d["embed_text"] for d in chunk],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        for doc, vec in zip(chunk, vectors):
            ok = wv.insert_document(
                collection=TACTICAL_PROFILES,
                properties=doc["properties"],
                vector=vec.tolist(),
            )
            inserted += int(ok)
        log.info(f"  Inserted {inserted}/{len(all_docs)}")

    log.info(f"\nDone — {wv.get_count(TACTICAL_PROFILES)} fingerprints in Weaviate")
    return inserted


async def ensure_indexed() -> None:
    """
    Ensure tactical knowledge base availability.

    Performs a safe startup check:

        - Skip if Weaviate is unavailable.
        - Skip if tactical profiles already exist.
        - Automatically build the index when empty.


    Designed for production startup usage where missing historical vectors
    should recover automatically without crashing the application.
    """
    try:
        wv = get_weaviate_client()
        if not wv.ready:
            log.info(
                "Tactical auto-index: Weaviate not ready yet, skipping this attempt"
            )
            return
        existing = wv.get_count(TACTICAL_PROFILES)
        if existing > 0:
            log.info(
                f"Tactical auto-index: {existing} fingerprints already indexed, skipping"
            )
            return
        log.info(
            "Tactical auto-index: TacticalProfiles is empty — indexing now (this can take a few minutes)..."
        )
        count = await _index_all()
        log.info(f"Tactical auto-index: complete — {count} fingerprints inserted")
    except Exception:
        log.warning(
            "Tactical auto-index failed — will retry on next app restart", exc_info=True
        )


async def main(check_only: bool = False) -> None:
    """
    Command-line entry point for tactical profile indexing.

    Args:
        check_only:
            If True, reports existing Weaviate document count without
            modifying the collection.

    Supports:
        - manual indexing
        - collection inspection
        - controlled re-indexing
    """
    wv = get_weaviate_client()
    if not wv.ready:
        log.error("Weaviate not ready — is the Docker container up on :8080?")
        return

    if check_only:
        log.info(f"TacticalProfiles document count: {wv.get_count(TACTICAL_PROFILES)}")
        return

    existing = wv.get_count(TACTICAL_PROFILES)
    if existing > 0:
        ans = (
            input(f"TacticalProfiles already has {existing} docs. Re-index? (y/N): ")
            .strip()
            .lower()
        )
        if ans != "y":
            return

    await _index_all()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Report count only")
    args = parser.parse_args()
    asyncio.run(main(check_only=args.check))
