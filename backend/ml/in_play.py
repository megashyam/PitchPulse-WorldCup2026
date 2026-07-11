"""
In-play football outcome model and Elo adjustment engine.

This module converts a live football match state into updated outcome
probabilities and tournament simulation adjustments.

The model bridges the gap between:
    - pre-match strength estimates
    - current match context
    - future tournament projections


Pipeline:

    Pre-match W/D/L Prior
            +
    Live Match State
        (score, minute, red cards)
            ↓
    Remaining Goal Simulation
            ↓
    Updated W/D/L Distribution
            ↓
    Elo Adjustment
            ↓
    Tournament Simulation


Model components:
    - Poisson scoring model for remaining goals.
    - Elo-derived pre-match supremacy adjustment.
    - Red-card impact modifiers.
    - Expected-points based Elo movement.


Design goals:
    - Preserve interpretability over black-box prediction.
    - Produce calibrated probability updates during live matches.
    - Provide bounded adjustments suitable for downstream simulations.

The output is designed for counterfactual tournament simulations where a
team's current performance should influence future match probabilities.
"""

from __future__ import annotations

import math
from typing import Tuple

WDL = Tuple[float, float, float]  # (p_home_win, p_draw, p_away_win)

FULL_TIME = 90
# Expected total goals scored in a full 90-minute men's international football match.
# Used as the baseline Poisson scoring intensity before adjusting for:
#   - remaining match time
#   - pre-match team strength advantage
#   - red-card effects
# This represents the average combined scoring environment across both teams.
BASE_TOTAL_GOALS = 2.6

# Controls how strongly the pre-match probability advantage influences goal allocation.
# A value of 0 means goals are split evenly between teams regardless of strength.
# Higher values give the pre-match favorite a larger share of expected remaining goals.
# Tuned conservatively to avoid allowing pre-match strength to dominate live state.
SUPREMACY_TILT = 0.65

# Multiplicative penalty applied to a team's remaining scoring rate after receiving
# a red card. A value of 0.72 means the dismissed team's attacking output is reduced
# by approximately 28% for the remainder of the match.
RED_SELF = 0.72

# Multiplicative boost applied to the opponent's remaining scoring rate after the
# other team receives a red card. A value of 1.12 represents roughly a 12% increase
# in scoring expectation due to numerical advantage.
RED_OPP = 1.12

# Maximum number of goals considered when enumerating Poisson outcome probabilities.
# Since extremely high goal counts have negligible probability in football,
# truncating at 8 goals provides accurate W/D/L probabilities while keeping the
# computation lightweight for live inference.
MAX_GOALS = 8


def _poisson_pmf(lmbda: float, k: int) -> float:
    """
    Compute the Poisson probability mass function.

    Used to estimate the probability of scoring exactly k additional goals
    given an expected scoring rate λ.
    """
    return math.exp(-lmbda) * lmbda**k / math.factorial(k)


def inplay_wdl(
    pre_wdl: WDL,
    minute: int,
    home_score: int,
    away_score: int,
    red_home: int = 0,
    red_away: int = 0,
) -> WDL:
    """
    Estimate live win/draw/loss probabilities from the current match state.

    The model updates a pre-match probability prior using live context:

        - remaining match time
        - current scoreline
        - team strength advantage
        - red card effects

    Remaining goals are modeled as independent Poisson processes with rates
    adjusted by:
        - fraction of match remaining
        - pre-match supremacy
        - player advantage/disadvantage

    The final score distribution is enumerated to produce normalized:
        (home win probability, draw probability, away win probability)

    This provides an interpretable alternative to black-box live prediction
    models while remaining suitable for real-time simulation.
    """
    minute = max(0, min(int(minute), FULL_TIME))
    frac = max(0.0, (FULL_TIME - minute) / FULL_TIME)
    lead = int(home_score) - int(away_score)

    # Match effectively over → decide on current score.
    if frac <= 1e-6:
        if lead > 0:
            return (1.0, 0.0, 0.0)
        if lead < 0:
            return (0.0, 0.0, 1.0)
        return (0.0, 1.0, 0.0)

    p_hw0, _p_d0, p_aw0 = pre_wdl
    supremacy = max(-1.0, min(1.0, p_hw0 - p_aw0))
    base = (BASE_TOTAL_GOALS / 2.0) * frac
    lam_h = max(0.02, base * (1.0 + SUPREMACY_TILT * supremacy))
    lam_a = max(0.02, base * (1.0 - SUPREMACY_TILT * supremacy))

    for _ in range(max(0, int(red_home))):
        lam_h *= RED_SELF
        lam_a *= RED_OPP
    for _ in range(max(0, int(red_away))):
        lam_a *= RED_SELF
        lam_h *= RED_OPP

    ph = [_poisson_pmf(lam_h, k) for k in range(MAX_GOALS + 1)]
    pa = [_poisson_pmf(lam_a, k) for k in range(MAX_GOALS + 1)]

    p_hw = p_d = p_aw = 0.0
    for gh in range(MAX_GOALS + 1):
        for ga in range(MAX_GOALS + 1):
            prob = ph[gh] * pa[ga]
            final = lead + gh - ga
            if final > 0:
                p_hw += prob
            elif final == 0:
                p_d += prob
            else:
                p_aw += prob

    total = p_hw + p_d + p_aw or 1.0
    return (p_hw / total, p_d / total, p_aw / total)


def _expected_points(p_win: float, p_draw: float) -> float:
    """
    Convert win/draw probabilities into expected tournament points.

    Uses standard football scoring:
        win  = 3 points
        draw = 1 point

    This provides a comparable performance metric for translating probability
    shifts into Elo adjustments.
    """
    return 3.0 * p_win + 1.0 * p_draw


def elo_deltas(
    pre_wdl: WDL,
    state_wdl: WDL,
    k_elo: float = 40.0,
    cap: float = 80.0,
) -> Tuple[float, float]:
    """
    Convert live probability changes into bounded Elo adjustments.

    The adjustment represents how much a team's tournament strength estimate
    should move based on current match performance.

    Method:
        1. Convert pre-match and live probabilities into expected points.
        2. Measure the deviation from the original expectation.
        3. Scale the difference into Elo space.
        4. Apply bounds to prevent extreme simulation swings.

    Returns:
        (home_team_elo_delta, away_team_elo_delta)

    This allows live match context to influence future tournament simulations
    without permanently overreacting to a single event.
    """
    p_hw0, p_d0, p_aw0 = pre_wdl
    p_hw, p_d, p_aw = state_wdl
    dep_home = _expected_points(p_hw, p_d) - _expected_points(p_hw0, p_d0)
    dep_away = _expected_points(p_aw, p_d) - _expected_points(p_aw0, p_d0)

    def clamp(x: float) -> float:
        return max(-cap, min(cap, k_elo * x))

    return clamp(dep_home), clamp(dep_away)
