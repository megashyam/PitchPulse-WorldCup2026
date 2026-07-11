"""
Probability prior generation layer for tournament simulation.

This module converts team strength signals and market information into
calibrated win/draw/loss probability distributions used by the tournament
simulation engine.

The system combines:

    Team Strength Ratings
            +
    Market-Based Odds
            ↓
    Calibrated Match Probabilities
            ↓
    Group Stage & Knockout Simulation


Core responsibilities:
    - Convert Elo ratings into match outcome probabilities.
    - Transform bookmaker odds into fair probabilities.
    - Apply probability calibration and numerical safeguards.
    - Generate complete tournament prior tables.
    - Construct knockout advancement probability matrices.


Betting market inputs are used as fixture-specific priors when available,
while Elo remains the fallback signal for unseen matchups. All outputs are
normalized into valid probability distributions suitable for large-scale
Monte Carlo simulation.
"""

import numpy as np
from typing import Dict, Optional, Tuple

from ml.wc_2026_config import WC2026_TEAMS

MatchProb = Tuple[float, float, float]

MIN_PROB = 0.01


def elo_expected(rating_a: float, rating_b: float) -> float:
    """
    Calculate the expected Elo score for team A.

    Uses the standard Elo formulation to estimate the probability that team A
    achieves a positive result relative to team B.

    Args:
        rating_a:
            Elo rating of team A.

        rating_b:
            Elo rating of team B.

    Returns:
        Expected score probability for team A in the range [0, 1].
    """
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def elo_to_wdl(rating_a: float, rating_b: float) -> MatchProb:
    """
    Convert Elo ratings into calibrated win/draw/loss probabilities.

    Elo provides the competitive strength component while a dynamic draw
    model adjusts draw probability based on rating similarity. The remaining
    probability mass is distributed between win and loss outcomes.

    Args:
        rating_a:
            Elo rating of team A.

        rating_b:
            Elo rating of team B.

    Returns:
        Tuple containing:

            (
                probability_team_a_win,
                probability_draw,
                probability_team_b_win
            )

        Values are normalized and guaranteed to form a valid probability
        distribution.
    """
    e_a = elo_expected(rating_a, rating_b)

    elo_diff = abs(rating_a - rating_b)
    p_draw = 0.25 * np.exp(-elo_diff / 450.0) + 0.05
    p_draw = float(np.clip(p_draw, 0.10, 0.30))

    remaining = 1.0 - p_draw
    p_win = remaining * e_a
    p_loss = remaining * (1.0 - e_a)

    return _normalise(p_win, p_draw, p_loss)


def oddsapi_to_wdl(
    odds_home: float,
    odds_draw: float,
    odds_away: float,
) -> MatchProb:
    """
    Convert decimal bookmaker odds into fair outcome probabilities.

    Removes bookmaker margin (overround) using a Shin-style correction,
    producing calibrated probabilities suitable for simulation rather than
    raw market-implied probabilities.

    Args:
        odds_home:
            Decimal odds for the home team.

        odds_draw:
            Decimal odds for a draw.

        odds_away:
            Decimal odds for the away team.

    Returns:
        Normalized win/draw/loss probability tuple.
    """
    raw = np.array([1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away])
    overround = raw.sum() - 1.0

    z = overround / (overround + 2.0)

    fair = np.zeros(3)
    for i, p in enumerate(raw):
        disc = z**2 + 4.0 * (1.0 - z) * p**2
        fair[i] = (np.sqrt(disc) - z) / (2.0 * (1.0 - z))

    p_win, p_draw, p_loss = fair[0], fair[1], fair[2]
    return _normalise(p_win, p_draw, p_loss)


def _normalise(p_win: float, p_draw: float, p_loss: float) -> MatchProb:
    """
    Normalize probabilities into a valid probability simplex.

    Applies a minimum probability floor to prevent zero-probability outcomes
    from causing numerical issues during simulation sampling.

    Args:
        p_win:
            Raw win probability.

        p_draw:
            Raw draw probability.

        p_loss:
            Raw loss probability.

    Returns:
        Normalized probabilities where:

            p_win + p_draw + p_loss = 1.0
    """
    arr = np.array([p_win, p_draw, p_loss], dtype=np.float64)
    arr = np.clip(arr, MIN_PROB, None)
    arr /= arr.sum()
    return float(arr[0]), float(arr[1]), float(arr[2])


def build_prior_table(
    betfair_odds: Optional[Dict[Tuple[str, str], Tuple[float, float, float]]] = None,
    elo_overrides: Optional[Dict[str, float]] = None,
) -> Dict[Tuple[str, str], MatchProb]:
    """
    Build the complete tournament match probability prior table.

    Generates probabilities for every ordered team matchup. Market odds are
    preferred for known fixtures, while Elo-based probabilities provide
    coverage for unavailable markets.

    Elo overrides allow dynamic team-strength adjustments from live match
    context, enabling counterfactual simulations after momentum shifts,
    goals, or other match events.

    Args:
        betfair_odds:
            Optional mapping of fixtures to decimal market odds.

        elo_overrides:
            Optional team-level Elo adjustments applied before simulation.

    Returns:
        Dictionary mapping ordered team pairs to win/draw/loss probabilities.
    """
    teams = WC2026_TEAMS
    n = len(teams)
    ovr = elo_overrides or {}
    priors: Dict[Tuple[str, str], MatchProb] = {}

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            ta = teams[i]
            tb = teams[j]
            key = (ta.name, tb.name)
            conditioned = ta.name in ovr or tb.name in ovr

            if not conditioned and betfair_odds and key in betfair_odds:
                o_h, o_d, o_a = betfair_odds[key]
                priors[key] = oddsapi_to_wdl(o_h, o_d, o_a)
            elif (
                not conditioned and betfair_odds and (tb.name, ta.name) in betfair_odds
            ):
                o_h, o_d, o_a = betfair_odds[(tb.name, ta.name)]
                rev = oddsapi_to_wdl(o_h, o_d, o_a)
                priors[key] = (rev[2], rev[1], rev[0])  # flip perspective
            else:
                priors[key] = elo_to_wdl(
                    ta.elo + ovr.get(ta.name, 0.0),
                    tb.elo + ovr.get(tb.name, 0.0),
                )

    return priors


def ko_prob(p_win: float, p_draw: float, p_loss: float) -> Tuple[float, float]:
    """
    Convert match outcome probabilities into knockout advancement probabilities.

    Knockout matches do not contain draws, so draw probability is split
    equally between both teams to estimate advancement likelihood.

    Args:
        p_win:
            Probability of team A winning.

        p_draw:
            Probability of a draw after regulation.

        p_loss:
            Probability of team A losing.

    Returns:
        Tuple containing:

            (
                team_a_advancement_probability,
                team_b_advancement_probability
            )
    """
    p_a = p_win + 0.5 * p_draw
    p_b = p_loss + 0.5 * p_draw
    total = p_a + p_b
    return p_a / total, p_b / total


def build_ko_matrix(
    priors: Dict[Tuple[str, str], MatchProb],
    elo_overrides: Optional[Dict[str, float]] = None,
) -> np.ndarray:
    """
    Construct the knockout advancement probability matrix.

    Creates a vectorized representation where each matrix entry represents
    the probability of one team advancing against another team.

    The matrix format enables efficient tournament simulation by avoiding
    repeated probability calculations during large Monte Carlo runs.

    Args:
        priors:
            Match outcome probability table generated by build_prior_table.

        elo_overrides:
            Optional live Elo adjustments for counterfactual scenarios.

    Returns:
        NumPy matrix of shape:

            (number_of_teams, number_of_teams)

        where matrix[i, j] represents team i's advancement probability
        against team j.
    """
    teams = WC2026_TEAMS
    n = len(teams)
    matrix = np.zeros((n, n), dtype=np.float32)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            key = (teams[i].name, teams[j].name)
            if key in priors:
                p_w, p_d, p_l = priors[key]
            else:
                ovr = elo_overrides or {}
                p_w, p_d, p_l = elo_to_wdl(
                    teams[i].elo + ovr.get(teams[i].name, 0.0),
                    teams[j].elo + ovr.get(teams[j].name, 0.0),
                )
            matrix[i, j], matrix[j, i] = ko_prob(p_w, p_d, p_l)

    return matrix
