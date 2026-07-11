"""
Counterfactual tournament simulation engine.

Estimates how live match events change tournament outcomes by comparing two
Monte Carlo tournament simulations:

1. Baseline simulation:
   Tournament state before the event.

2. Counterfactual simulation:
   Tournament state after adjusting team strength using the observed match
   state (score, minute, cards, and in-play win probabilities).

The system uses Common Random Numbers (CRN), keeping simulation randomness
identical between both runs. This isolates the effect of the event itself,
allowing championship probability changes to be interpreted as the event's
causal impact rather than Monte Carlo noise.

Architecture:
- Match events are converted into bounded Elo adjustments through in-play W/D/L
  modeling.
- Redis-backed event signatures ensure idempotent processing across restarts.
- Deterministic CRC32 seeds guarantee reproducible simulations.
- Dedicated simulation workers prevent counterfactual workloads from blocking
  larger tournament simulations.
- Async execution allows baseline and counterfactual simulations to run
  concurrently.

The simulator conditions through team strength changes rather than modifying
the exact tournament fixture tree, making this a strength-based counterfactual
analysis rather than a complete bracket intervention.
"""

import asyncio
import logging
import os
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple

from agents.ollama_client import generate
from api.schemas.event_types import RED_TYPES, TRIGGER_TYPES
from api.schemas.schema import MatchEvent, MatchState
from ml.executors import CF_SIM_EXECUTOR
from ml.in_play import elo_deltas, inplay_wdl
from ml.odds_api_client import get_oddsapi_client
from ml.prior_builder import oddsapi_to_wdl, elo_to_wdl
from ml.team_names import SIM_NAMES, to_sim
from ml.tournament_sim import run_simulation
from ml.wc_2026_config import WC2026_TEAMS

log = logging.getLogger(__name__)

DELTA_THRESHOLD = 0.003
CF_SIMS = int(os.getenv("CF_SIMS", "20000"))

_ELO: Dict[str, float] = {t.name: t.elo for t in WC2026_TEAMS}


@dataclass
class CfState:
    covered: Set[str] = field(default_factory=set)
    last_time: float = 0.0
    MIN_GAP: float = 45.0


_states: Dict[int, CfState] = {}


def _sig(ev: MatchEvent) -> str:

    return f"{ev.elapsed}:{ev.type}:{ev.team_id}"


def event_sig(elapsed: int, ev_type: str, team_id: int) -> str:
    """
    Create a deterministic event identifier used for deduplication.

    Event signatures allow previously analyzed match events to be restored from
    persistent feeds after worker restarts, preventing duplicate simulations.

    Args:
        elapsed: Match minute when the event occurred.
        ev_type: Event category (goal, red card, penalty, etc.).
        team_id: Team associated with the event.

    Returns:
        Stable event signature string.
    """
    return f"{elapsed}:{ev_type}:{team_id}"


def seed_covered(fixture_id: int, sigs: Set[str]) -> None:
    """
    Restore previously processed event signatures.

    Used during worker recovery to rebuild in-memory state from persisted feed
    data and maintain idempotent counterfactual processing.

    Args:
        fixture_id: Match identifier.
        sigs: Previously analyzed event signatures.
    """
    cf = _states.setdefault(fixture_id, CfState())
    cf.covered |= sigs


def clear_state(fixture_id: int) -> None:
    _states.pop(fixture_id, None)


def _maybe_reset_on_replay(cf: CfState, current_elapsed: int) -> None:
    if not cf.covered or current_elapsed > 20:
        return
    covered_minutes = []
    for sig in cf.covered:
        try:
            covered_minutes.append(int(sig.split(":")[0]))
        except (ValueError, IndexError):
            pass
    if covered_minutes and max(covered_minutes) > current_elapsed + 20:
        log.info(
            f"Replay restart — covered up to {max(covered_minutes)}', "
            f"now at {current_elapsed}'. Resetting."
        )
        cf.covered.clear()
        cf.last_time = 0.0


def _find_trigger(state: MatchState, cf: CfState) -> Optional[MatchEvent]:
    current_elapsed = state.elapsed or 0
    _maybe_reset_on_replay(cf, current_elapsed)

    for ev in reversed(state.events):
        if ev.type not in TRIGGER_TYPES:
            continue
        if ev.elapsed > current_elapsed:
            continue
        if _sig(ev) in cf.covered:
            continue
        return ev
    return None


def _find_all_triggers(state: MatchState, cf: CfState) -> List[MatchEvent]:

    current_elapsed = state.elapsed or 0
    _maybe_reset_on_replay(cf, current_elapsed)

    out: List[MatchEvent] = []
    seen: Set[str] = set()
    for ev in sorted(state.events, key=lambda e: e.elapsed):
        if ev.type not in TRIGGER_TYPES:
            continue
        if ev.elapsed > current_elapsed:
            continue
        sig = _sig(ev)
        if sig in cf.covered or sig in seen:
            continue
        seen.add(sig)
        out.append(ev)
    return out


def _pre_match_wdl(home: str, away: str, betfair_odds) -> Tuple[float, float, float]:
    """
    Estimate baseline match win probabilities.

    Uses de-vigged market odds when available, otherwise falls back to Elo-based
    probabilities.

    Returns:
        Tuple containing home win, draw, and away win probabilities.
    """
    if betfair_odds:
        if (home, away) in betfair_odds:
            return oddsapi_to_wdl(*betfair_odds[(home, away)])
        if (away, home) in betfair_odds:
            r = oddsapi_to_wdl(*betfair_odds[(away, home)])
            return (r[2], r[1], r[0])
    eh, ea = _ELO.get(home), _ELO.get(away)
    if eh is None or ea is None:
        return (0.40, 0.25, 0.35)
    return elo_to_wdl(eh, ea)


def _red_counts(state: MatchState) -> Tuple[int, int]:
    rh = ra = 0
    for ev in state.events:
        if ev.type in RED_TYPES:
            if ev.team_name == state.home_name:
                rh += 1
            elif ev.team_name == state.away_name:
                ra += 1
    return rh, ra


def _pre_event_state(
    state: MatchState, trigger: MatchEvent, red_h: int, red_a: int
) -> Tuple[int, int, int, int]:
    """
    Reconstruct match state immediately before an event occurred.

    The counterfactual engine compares the tournament impact before and after
    the event. Scoring events and red cards are reversed to recover the prior
    match state.

    Non-impactful events naturally produce identical states, resulting in zero
    tournament probability movement.

    Returns:
        Home score, away score, home red cards, away red cards before event.
    """
    hb, ab, rhb, rab = state.home_score, state.away_score, red_h, red_a
    is_home = trigger.team_name == state.home_name
    t = trigger.type
    if t in ("goal", "penalty_goal"):
        if is_home:
            hb -= 1
        else:
            ab -= 1
    elif t == "own_goal":
        if is_home:
            ab -= 1
        else:
            hb -= 1
    elif t in RED_TYPES:
        if is_home:
            rhb -= 1
        else:
            rab -= 1
    return max(0, hb), max(0, ab), max(0, rhb), max(0, rab)


def _divergence(
    before_teams, after_teams
) -> Tuple[List[Tuple[str, float, float, float]], float]:
    """
    Calculate tournament probability redistribution caused by an event.

    Compares champion probabilities from baseline and counterfactual
    simulations and identifies teams whose title probabilities changed.

    Returns:
        Ranked probability changes and total championship probability mass
        transferred across the bracket.
    """
    before = {t.name: t.probs["champion"] for t in before_teams}
    after = {t.name: t.probs["champion"] for t in after_teams}
    changes: List[Tuple[str, float, float, float]] = []
    total_abs = 0.0
    for name, pb in before.items():
        pa = after.get(name, pb)
        d = pa - pb
        total_abs += abs(d)
        if abs(d) >= DELTA_THRESHOLD:
            changes.append((name, pb, pa, d))
    changes.sort(key=lambda x: abs(x[3]), reverse=True)

    path_shift = min(1.0, total_abs / 2.0)
    return changes, path_shift


def _build_prompt(state, trigger, changes, path_shift, after_teams, swing) -> str:
    ev_desc = trigger.type.replace("_", " ")
    score = f"{state.home_score}\u2013{state.away_score}"
    swing_line = (
        f"In-play win probability for {trigger.team_name} moved "
        f"{swing[0]:.0%} \u2192 {swing[1]:.0%} on this event.\n"
        if swing
        else ""
    )
    proxy_note = (
        "NOTE: team statistics for this fixture are historical proxies, not "
        "live totals — do not cite xG/possession as this match's real data.\n"
        if state.stats_source == "statsbomb_proxy"
        else ""
    )
    if changes:
        lines = "\n".join(
            f"  {name}: {pb:.1%} \u2192 {pa:.1%}  ({'+' if d > 0 else ''}{d:.1%})"
            for name, pb, pa, d in changes[:3]
        )
        bracket_context = (
            f"CHAMPION PROBABILITY SHIFTS "
            f"(two {CF_SIMS:,}-sim brackets, common random numbers):\n{lines}\n\n"
            f"Champion-probability mass relocated: {path_shift:.1%}."
        )
    else:
        top_now = sorted(after_teams, key=lambda t: t.probs["champion"], reverse=True)[
            :3
        ]
        lines = "\n".join(
            f"  {t.name}: {t.probs['champion']:.1%} champion probability"
            for t in top_now
        )
        bracket_context = (
            f"CURRENT CHAMPION PROBABILITIES ({CF_SIMS:,} simulated tournaments):\n"
            f"{lines}\n\nThis event did not move the bracket."
        )

    return (
        f"[INST] You are the lead tournament analyst for a live World Cup 2026 "
        f"intelligence desk. Your job is to explain, vividly and specifically, "
        f"how one match event reshapes the ENTIRE tournament bracket — the kind "
        f"of insight a smart fan couldn't get just from watching the game.\n\n"
        f"MATCH: {state.home_name} {score} {state.away_name} "
        f"\u00b7 Minute {trigger.elapsed}' \u00b7 {state.status_short}\n"
        f"EVENT: {trigger.team_name} \u2014 {ev_desc}\n"
        f"{swing_line}{proxy_note}\n"
        f"{bracket_context}\n\n"
        f"Write 3-4 sentences that capture the absolute shockwave of this event:\n"
        f"1. The Earthquake: Open with the single most striking percentage shift from the numbers above. Frame it as an immediate consequence.\n"
        f"2. The Fallout: Name exactly which teams saw their title equity shattered or skyrocketed. Connect this to their new path through the bracket (who they dodge, who they now face).\n"
        f"3. Add one sharp, non-obvious consequence: a rival whose odds moved "
        f"even though they weren't playing, a group-stage knock-on, or a "
        f"favourite quietly benefiting.\n\n"
        f"Be concrete and confident. Use the actual percentages. Avoid the words "
        f"'significant', 'crucial', 'notable', 'pivotal'. Do not hedge with "
        f"'could' or 'might' more than once. Sound like someone who finds this "
        f"genuinely fascinating. [/INST]"
    )


def _ordinal_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _template(state, trigger, changes, path_shift, after_teams, swing) -> str:
    """Rich, specific fallback used only when no LLM is reachable. Deliberately
    multi-sentence and number-dense so a keyless deployment still reads like
    analysis rather than a stub. (Bug fix: the old one-line template was what
    produced the bland/empty-looking narratives when Ollama+Groq were both
    unavailable.)"""
    ev_desc = trigger.type.replace("_", " ")
    score = f"{state.home_score}\u2013{state.away_score}"

    # Swing line (this team's in-match win prob before/after the event).
    swing_txt = ""
    if swing and abs(swing[1] - swing[0]) > 0.005:
        swing_txt = (
            f" The event swung {trigger.team_name}'s in-match win probability "
            f"from {_ordinal_pct(swing[0])} to {_ordinal_pct(swing[1])}."
        )

    if changes:
        # Biggest riser and biggest faller across the whole bracket.
        risers = [c for c in changes if c[3] > 0]
        fallers = [c for c in changes if c[3] < 0]
        top = changes[0]
        name, pb, pa, delta = top
        direction = "climbs" if delta > 0 else "slips"

        lead = (
            f"{path_shift * 100:.1f}% of the tournament's title probability just "
            f"relocated across the bracket. {name} {direction} from "
            f"{_ordinal_pct(pb)} to {_ordinal_pct(pa)} to lift the World Cup "
            f"({'+' if delta > 0 else ''}{delta * 100:.1f} points)"
        )

        second = ""
        if delta > 0 and fallers:
            fn, fpb, fpa, fd = fallers[0]
            second = (
                f", while {fn} pays for it, sliding {fpb * 100:.1f}% → "
                f"{fpa * 100:.1f}%"
            )
        elif delta < 0 and risers:
            rn, rpb, rpa, rd = risers[0]
            second = (
                f", while {rn} is the quiet beneficiary, rising {rpb * 100:.1f}% "
                f"→ {rpa * 100:.1f}%"
            )
        elif len(changes) > 1:
            n2, pb2, pa2, d2 = changes[1]
            second = (
                f", and {n2} moves {pb2 * 100:.1f}% → {pa2 * 100:.1f}% "
                f"in the ripple"
            )

        return (
            f"{lead}{second}. The {ev_desc} in {state.home_name} {score} "
            f"{state.away_name} at {trigger.elapsed}' didn't just change this "
            f"result — it reweighted the whole draw.{swing_txt}"
        )

    # No material bracket change.
    top = sorted(after_teams, key=lambda t: t.probs["champion"], reverse=True)[:2]
    leaders = (
        ", ".join(f"{t.name} ({_ordinal_pct(t.probs['champion'])})" for t in top)
        if top
        else "the field"
    )
    return (
        f"{trigger.team_name}'s {ev_desc} at {trigger.elapsed}' barely moved the "
        f"title picture — under {max(0.1, path_shift * 100):.1f}% of championship "
        f"probability shifted. The favourites are unchanged at the top: {leaders}."
        f"{swing_txt}"
    )


def _stable_seed(fid: int, trigger: MatchEvent) -> int:
    """
    Generate a reproducible simulation seed.

    CRC32 is used instead of Python's hash() because hash values are randomized
    between processes, which would break reproducibility across deployments.

    Returns:
        Deterministic integer seed for Monte Carlo simulations.
    """
    raw = f"{fid}:{trigger.elapsed}:{trigger.type}:{trigger.team_id}".encode()
    return zlib.crc32(raw) % 2_147_483_646 + 1


async def update(
    state: MatchState,
    loop: asyncio.AbstractEventLoop,
    on_start: Optional[Callable[[dict], Awaitable[None]]] = None,
) -> Optional[dict]:
    """
    Analyze the latest uncovered match event.

    This is the live inference path. It processes the newest trigger event while
    applying throttling to control simulation cost during active matches.

    The workflow:
    1. Detect new match event.
    2. Convert event impact into strength adjustment.
    3. Run counterfactual tournament simulations.
    4. Generate analyst-style narrative explanation.

    Returns:
        Counterfactual analysis result or None when no new event exists.
    """
    fid = state.fixture_id
    cf = _states.setdefault(fid, CfState())

    if time.time() - cf.last_time < cf.MIN_GAP:
        return None

    trigger = _find_trigger(state, cf)
    if not trigger:
        return None

    cf.last_time = time.time()
    return await _analyze_trigger(state, cf, trigger, loop, on_start=on_start)


async def update_all(
    state: MatchState,
    loop: asyncio.AbstractEventLoop,
    on_start: Optional[Callable[[dict], Awaitable[None]]] = None,
    max_events: int = 20,
) -> List[dict]:
    """
    Backfill all uncovered counterfactual events for a match.

    Unlike the live update path, this processes historical events in bulk,
    allowing completed matches to display their full causal event history.

    Events are processed chronologically with a configurable cap to avoid
    monopolizing simulation resources.
    """
    fid = state.fixture_id
    cf = _states.setdefault(fid, CfState())

    triggers = _find_all_triggers(state, cf)[:max_events]
    if not triggers:
        return []

    results: List[dict] = []
    for trigger in triggers:
        result = await _analyze_trigger(state, cf, trigger, loop, on_start=on_start)
        if result is not None:
            results.append(result)
    cf.last_time = time.time()
    return results


async def _analyze_trigger(
    state: MatchState,
    cf: "CfState",
    trigger: MatchEvent,
    loop: asyncio.AbstractEventLoop,
    on_start: Optional[Callable[[dict], Awaitable[None]]] = None,
) -> Optional[dict]:
    """
    Execute the complete counterfactual analysis pipeline for one event.

    Pipeline:
    1. Restore match state before the event.
    2. Compute pre/post in-play win probabilities.
    3. Convert probability changes into Elo adjustments.
    4. Run baseline and counterfactual tournament simulations.
    5. Measure championship probability shifts.
    6. Generate natural-language explanation.

    Shared by both live updates and historical backfill processing.
    """
    fid = state.fixture_id

    if on_start is not None:
        try:
            await on_start(
                {
                    "minute": trigger.elapsed,
                    "event_type": trigger.type,
                    "event_team": trigger.team_name,
                }
            )
        except Exception:
            log.warning(f"[{fid}] on_start callback failed", exc_info=True)

    betfair = get_oddsapi_client()
    betfair_odds = await betfair.get_all_odds()

    cf.covered.add(_sig(trigger))

    home_c, away_c = to_sim(state.home_name), to_sim(state.away_name)
    conditioned = home_c in SIM_NAMES or away_c in SIM_NAMES
    pre_wdl = _pre_match_wdl(home_c, away_c, betfair_odds)

    red_h, red_a = _red_counts(state)
    hb, ab, rhb, rab = _pre_event_state(state, trigger, red_h, red_a)
    minute = trigger.elapsed

    after_wdl = inplay_wdl(
        pre_wdl, minute, state.home_score, state.away_score, red_h, red_a
    )
    before_wdl = inplay_wdl(pre_wdl, minute, hb, ab, rhb, rab)

    ad_h, ad_a = elo_deltas(pre_wdl, after_wdl)
    bd_h, bd_a = elo_deltas(pre_wdl, before_wdl)
    after_ovr = {home_c: ad_h, away_c: ad_a}
    before_ovr = {home_c: bd_h, away_c: bd_a}

    acted_home = trigger.team_name == state.home_name
    swing = (
        (before_wdl[0], after_wdl[0]) if acted_home else (before_wdl[2], after_wdl[2])
    )

    seed = _stable_seed(fid, trigger)

    negligible = not conditioned or (
        abs(ad_h - bd_h) < 1e-9 and abs(ad_a - bd_a) < 1e-9
    )

    try:
        if negligible:
            after_result = await loop.run_in_executor(
                CF_SIM_EXECUTOR,
                lambda: run_simulation(
                    betfair_odds=betfair_odds,
                    n_sims=CF_SIMS,
                    seed=seed,
                    elo_overrides=after_ovr,
                ),
            )
            before_result = after_result
        else:
            after_result, before_result = await asyncio.gather(
                loop.run_in_executor(
                    CF_SIM_EXECUTOR,
                    lambda: run_simulation(
                        betfair_odds=betfair_odds,
                        n_sims=CF_SIMS,
                        seed=seed,
                        elo_overrides=after_ovr,
                    ),
                ),
                loop.run_in_executor(
                    CF_SIM_EXECUTOR,
                    lambda: run_simulation(
                        betfair_odds=betfair_odds,
                        n_sims=CF_SIMS,
                        seed=seed,
                        elo_overrides=before_ovr,
                    ),
                ),
            )
    except Exception as exc:
        log.error(f"[{fid}] CF sim failed: {exc}")
        cf.covered.discard(_sig(trigger))
        return None

    changes, path_shift = _divergence(before_result.teams, after_result.teams)

    prompt = _build_prompt(
        state,
        trigger,
        changes,
        path_shift,
        after_result.teams,
        None if negligible else swing,
    )
    narrative = await generate(prompt, timeout=20.0)
    if not narrative:
        narrative = _template(
            state, trigger, changes, path_shift, after_result.teams, swing
        )

    log.info(
        f"[{fid}] CF v4: {trigger.type}@{trigger.elapsed}' "
        f"conditioned={conditioned} negligible={negligible} "
        f"path_shift={path_shift:.2%} changes={len(changes)}"
    )

    return {
        "fixture_id": fid,
        "minute": trigger.elapsed,
        "event_type": trigger.type,
        "event_team": trigger.team_name,
        "event_team_id": trigger.team_id,
        "path_shift_pct": round(path_shift, 3),
        "top_changes": [
            {
                "team": name,
                "before": round(pb, 4),
                "after": round(pa, 4),
                "delta": round(d, 4),
            }
            for name, pb, pa, d in changes[:4]
        ],
        "narrative": narrative,
        "conditioned": conditioned,
        "match_win_prob_before": round(swing[0], 4),
        "match_win_prob_after": round(swing[1], 4),
        "elo_shift": {"home": round(ad_h, 1), "away": round(ad_a, 1)},
        "n_sims": after_result.n_sims,
        "elapsed_s": after_result.elapsed_s,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
