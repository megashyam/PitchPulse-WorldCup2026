"""
Real-time football momentum inference engine.

This module converts live match data into continuously updated momentum
predictions using online feature smoothing, logistic scoring, and event-based
adjustments.

Pipeline:

    Live MatchState
          |
    Feature Extraction
          |
    EWMA Smoothing
          |
    Logistic Probability Model
          |
    Event Impact Adjustment
          ↓
    Momentum Snapshot


Responsibilities:
    - Maintain per-fixture temporal feature state.
    - Smooth noisy live statistics.
    - Estimate short-term scoring probability.
    - Apply goal and red-card momentum effects.
    - Provide low-latency predictions for API and SSE consumers.


The model keeps lightweight in-memory state because momentum depends on match
history. State is cleared when fixtures become inactive to avoid stale feature
leakage.
"""

import json
import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from api.schemas.event_types import GOAL_TYPES, LIVE_STATUSES, RED_TYPES
from api.schemas.schema import MatchEvent, MatchState

log = logging.getLogger(__name__)

UPDATE_INTERVAL_S = 30
SLOTS_PER_MIN = 60 / UPDATE_INTERVAL_S
ALPHA = 0.3
WINDOW_SLOTS = 30
BUMP_DECAY = 0.2
BUMP_LOOKBACK_MIN = 10

DEFAULT_COEF: Dict[str, float] = {
    "intercept": -3.30,
    "pressure": 3.5,
    "possession": 0.6,
    "pass_acc": 1.00,
    "minute_norm": -0.3,
    "score_diff": 0.2,
}

BUMP_WEIGHTS: Dict[str, float] = {
    "goal_scored": 0.15,
    "goal_conceded": -0.08,
    "red_card": -0.22,
    "red_card_opp": 0.12,
}

COEF_PATH = Path(__file__).parent / "momentum_coef.json"

_MIN_USEFUL_FEATURE_COEF = 0.5


@dataclass
class TeamMomentumState:
    """
    Stores smoothed live features for one team's momentum model.

    EWMA values capture recent trends while reducing noise from individual
    match-stat updates.
    """

    ewma_poss: float = 50.0
    ewma_pass_acc: float = 75.0
    ewma_pressure: float = 0.1
    shot_window: deque = field(default_factory=lambda: deque(maxlen=WINDOW_SLOTS))
    last_shots_total: int = 0
    last_shots_on: int = 0


@dataclass
class MatchMomentumState:
    """
    Stores home and away inference state for one live fixture.
    """

    fixture_id: int
    home: TeamMomentumState = field(default_factory=TeamMomentumState)
    away: TeamMomentumState = field(default_factory=TeamMomentumState)


states: Dict[int, MatchMomentumState] = {}


def _coef_is_degenerate(c: Dict[str, float]) -> bool:
    feature_keys = [k for k in DEFAULT_COEF if k != "intercept"]
    if any(k not in c for k in feature_keys):
        return True
    return max(abs(c[k]) for k in feature_keys) < _MIN_USEFUL_FEATURE_COEF


def _load_coef() -> Dict[str, float]:
    """
    Load trained coefficients with fallback protection.

    Invalid or missing model artifacts use calibrated defaults so the
    inference pipeline remains operational.
    """
    if COEF_PATH.exists():
        try:
            with open(COEF_PATH) as f:
                coef = json.load(f)
        except Exception as exc:
            log.warning(f"momentum_coef.json unreadable ({exc}) — using defaults")
            return DEFAULT_COEF.copy()
        if _coef_is_degenerate(coef):
            log.warning(
                "momentum_coef.json is degenerate (all feature coefficients "
                "near zero — an under-trained artifact). Using calibrated "
                "defaults; retrain with ml/momentum_trainer.py."
            )
            return DEFAULT_COEF.copy()
        log.info(f"Loaded trained momentum coefficients from {COEF_PATH}")
        return coef
    log.info(
        "momentum_coef.json not found — using default coefficients. "
        "Run ml/momentum_trainer.py to improve accuracy."
    )
    return DEFAULT_COEF.copy()


coef = _load_coef()


def sigmoid(z: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-z))
    except OverflowError:
        return 0.0 if z < 0 else 1.0


def logistic_forward(
    pressure: float, possession: float, pass_acc: float, minute: int, score_diff: int
) -> float:
    """
    Convert live match features into scoring probability.

    Uses possession, pressure, passing quality, match time, and score
    difference as model inputs.
    """
    z = (
        coef["intercept"]
        + coef["pressure"] * pressure
        + coef["possession"] * (possession / 100.0)
        + coef["pass_acc"] * (pass_acc / 100.0)
        + coef["minute_norm"] * (min(minute, 90) / 90.0)
        + coef["score_diff"] * max(-1.0, min(1.0, score_diff / 3.0))
    )
    return sigmoid(z)


def compute_bump(
    events: List[MatchEvent],
    current_minute: int,
    team_id: int,
) -> float:
    """
    Calculate temporary momentum changes from recent match events.

    Goals and red cards create decaying positive or negative adjustments.
    """
    bump = 0.0
    for e in events:
        age_min = current_minute - e.elapsed
        if age_min < 0 or age_min > BUMP_LOOKBACK_MIN:
            continue

        age_intervals = age_min * SLOTS_PER_MIN
        decay = (1.0 - BUMP_DECAY) ** age_intervals
        is_curr_team = e.team_id == team_id

        if e.type in GOAL_TYPES:
            key = "goal_scored" if is_curr_team else "goal_conceded"
            bump += BUMP_WEIGHTS[key] * decay
        elif e.type in RED_TYPES:
            key = "red_card" if is_curr_team else "red_card_opp"
            bump += BUMP_WEIGHTS[key] * decay

    return bump


def _update_team(
    ts: TeamMomentumState,
    stats,  # TeamStats instance
    minute: int,
    score_diff: int,
) -> float:
    """Update EWMA state and return raw goal probability for this team.

    Shot pressure pipeline:
      delta_shots (this interval) → 15-min rolling window (deque)
        → shots_15min = sum(window)
        → raw_pressure = (shots_15min / 15.0) × on-target quality ratio
        → ewma_pressure = α × raw + (1-α) × prev
    The window removes single-interval noise; the EWMA smooths trend changes.
    """
    delta_shots = max(0, stats.shots_total - ts.last_shots_total)
    ts.last_shots_total = stats.shots_total

    ts.shot_window.append(delta_shots)
    shots_15min = sum(ts.shot_window)

    quality = (
        (stats.shots_on_goal / stats.shots_total) if stats.shots_total > 0 else 0.5
    )
    raw_pressure = (shots_15min / 15.0) * quality  # shots/min × on-target ratio
    ts.ewma_pressure = ALPHA * raw_pressure + (1.0 - ALPHA) * ts.ewma_pressure

    # Possession is slow-moving, so it acts as the long-run signal.
    poss = stats.possession if stats.possession > 0 else 50.0
    ts.ewma_poss = ALPHA * poss + (1.0 - ALPHA) * ts.ewma_poss

    # Hold early-pass noise until the sample is large enough to be useful.
    if stats.passes_total > 10:
        pass_acc = stats.pass_accuracy
    else:
        pass_acc = ts.ewma_pass_acc  # hold current value
    ts.ewma_pass_acc = ALPHA * pass_acc + (1.0 - ALPHA) * ts.ewma_pass_acc

    return logistic_forward(
        pressure=ts.ewma_pressure,
        possession=ts.ewma_poss,
        pass_acc=ts.ewma_pass_acc,
        minute=minute,
        score_diff=score_diff,
    )


def update(state: MatchState) -> Optional[dict]:
    """
    Generate the latest momentum snapshot for a live fixture.

    Combines statistical signals and event impacts into home/away momentum
    scores consumed by downstream API layers.
    """
    if state.status_short not in LIVE_STATUSES:
        return None

    fid = state.fixture_id
    minute = state.elapsed or 0

    if fid not in states:
        states[fid] = MatchMomentumState(fixture_id=fid)
    ms = states[fid]

    home_raw_prob = _update_team(
        ms.home,
        state.home_stats,
        minute,
        score_diff=state.home_score - state.away_score,
    )
    away_raw_prob = _update_team(
        ms.away,
        state.away_stats,
        minute,
        score_diff=state.away_score - state.home_score,
    )

    home_bump = compute_bump(state.events, minute, state.home_id)
    away_bump = compute_bump(state.events, minute, state.away_id)

    home_goal_prob = max(0.001, min(0.99, home_raw_prob + home_bump))
    away_goal_prob = max(0.001, min(0.99, away_raw_prob + away_bump))

    total = home_goal_prob + away_goal_prob
    home_momentum = home_goal_prob / total
    away_momentum = away_goal_prob / total

    return {
        "fixture_id": fid,
        "home_name": state.home_name,
        "away_name": state.away_name,
        "elapsed": minute,
        "stats_source": state.stats_source,  # provenance flows downstream
        "home": {
            "momentum_score": round(home_momentum, 4),
            "goal_prob_5min": round(home_goal_prob, 4),
            "ewma_possession": round(ms.home.ewma_poss, 2),
            "ewma_pressure": round(ms.home.ewma_pressure, 4),
            "ewma_pass_acc": round(ms.home.ewma_pass_acc, 2),
            "bump": round(home_bump, 4),
        },
        "away": {
            "momentum_score": round(away_momentum, 4),
            "goal_prob_5min": round(away_goal_prob, 4),
            "ewma_possession": round(ms.away.ewma_poss, 2),
            "ewma_pressure": round(ms.away.ewma_pressure, 4),
            "ewma_pass_acc": round(ms.away.ewma_pass_acc, 2),
            "bump": round(away_bump, 4),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def clear_state(fixture_id) -> None:
    """Remove in-memory EWMA state when a match finishes or goes inactive."""
    states.pop(fixture_id, None)
