"""
Monte Carlo Tournament Simulator


Simulation engine for estimating FIFA World Cup 2026 outcomes using match
probability priors, vectorized Monte Carlo sampling, and bracket-based
knockout modeling.

Pipeline:

    Team Ratings / Market Odds
              |
              v
    Win-Draw-Loss Probability Priors
              |
              v
    ┌────────────────────────┐
    │ Group Stage Simulation │
    │                        │
    │ - Match sampling       │
    │ - Points calculation   │
    │ - Qualification        │
    └───────────┬────────────┘
                |
                v
    ┌────────────────────────┐
    │ Knockout Simulation    │
    │                        │
    │ - Bracket progression  │
    │ - Advancement sampling │
    └───────────┬────────────┘
                |
                v
    Tournament Outcome Distribution


The simulator uses NumPy vectorization to evaluate multiple tournament
scenarios simultaneously and reports stage advancement probabilities with
Monte Carlo confidence intervals.

Main Components:
    TournamentSimulator:
        Runs group and knockout stage simulations.

    SimResult:
        Stores aggregated team-level simulation results.

    run_simulation():
        Convenience entry point used by downstream API services.

"""

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from ml.wc_2026_config import WC2026_TEAMS, GROUPS, R32_BRACKET
from ml.prior_builder import build_prior_table, build_ko_matrix

logger = logging.getLogger(__name__)

STAGES = ["group_exit", "r32", "r16", "qf", "sf", "final", "champion"]
STAGE_IDX = {s: i for i, s in enumerate(STAGES)}


@dataclass
class TeamResult:
    """Per-team summary of simulated advancement probabilities."""

    name: str
    group: str
    elo: float
    fifa_rank: int
    probs: Dict[str, float]
    ci_95: Dict[str, Tuple[float, float]]


@dataclass
class SimResult:
    """Aggregate output for a tournament simulation batch."""

    n_sims: int
    elapsed_s: float
    teams: List[TeamResult]
    stage_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def team(self, name: str) -> Optional[TeamResult]:
        return next((t for t in self.teams if t.name == name), None)

    def sorted_by(self, stage: str = "champion") -> List[TeamResult]:
        return sorted(self.teams, key=lambda t: t.probs.get(stage, 0), reverse=True)


class TournamentSimulator:
    """Run vectorized group-stage and knockout simulations for WC 2026."""

    def __init__(
        self,
        betfair_odds=None,
        n_sims: int = 50_000,
        seed: Optional[int] = None,
        elo_overrides: Optional[Dict[str, float]] = None,
    ):
        self.teams = WC2026_TEAMS
        self.n_teams = len(self.teams)
        self.name_to_idx = {t.name: i for i, t in enumerate(self.teams)}
        self.n_sims = n_sims
        self.seed = seed

        self.elo_overrides = elo_overrides or {}
        self.priors = build_prior_table(betfair_odds, self.elo_overrides)
        self.ko_matrix = build_ko_matrix(self.priors, self.elo_overrides)

        self.group_names = sorted(GROUPS.keys())
        self.group_team_idxs: List[np.ndarray] = []
        for g in self.group_names:
            idxs = np.array(
                [self.name_to_idx[t.name] for t in GROUPS[g]], dtype=np.int32
            )
            self.group_team_idxs.append(idxs)

        self.group_matches: List[Tuple[int, int]] = []
        for idxs in self.group_team_idxs:
            for i in range(4):
                for j in range(i + 1, 4):
                    self.group_matches.append((int(idxs[i]), int(idxs[j])))

        self._match_home_idxs = np.array(
            [h for h, _ in self.group_matches], dtype=np.int64
        )
        self._match_away_idxs = np.array(
            [a for _, a in self.group_matches], dtype=np.int64
        )

        self.gs_probs = np.array(
            [self._get_wdl(h, a) for h, a in self.group_matches], dtype=np.float64
        )

        logger.info(
            f"TournamentSimulator ready: {self.n_teams} teams, "
            f"{len(self.group_matches)} group matches, n_sims={n_sims}"
        )

    def run(self) -> SimResult:
        """Run the full tournament simulation and return per-team probabilities."""
        t0 = time.perf_counter()
        rng = np.random.default_rng(self.seed)
        N = self.n_sims
        n_teams = self.n_teams
        n_matches = len(self.group_matches)

        cum_probs = np.cumsum(self.gs_probs[:, :2], axis=1)
        u = rng.random((N, n_matches), dtype=np.float32)

        outcome = (
            (u[:, :, np.newaxis] >= cum_probs[np.newaxis, :, :].astype(np.float32))
            .sum(axis=2)
            .astype(np.int8)
        )

        home_pts_lut = np.array([3, 1, 0], dtype=np.int16)
        away_pts_lut = np.array([0, 1, 3], dtype=np.int16)
        home_pts = home_pts_lut[outcome]
        away_pts = away_pts_lut[outcome]

        pts = np.zeros((N, n_teams), dtype=np.int16)
        sim_idx_repeated = np.repeat(np.arange(N), n_matches)
        home_idx_tiled = np.tile(self._match_home_idxs, N)
        away_idx_tiled = np.tile(self._match_away_idxs, N)

        np.add.at(pts, (sim_idx_repeated, home_idx_tiled), home_pts.ravel())
        np.add.at(pts, (sim_idx_repeated, away_idx_tiled), away_pts.ravel())

        noise = rng.random((N, n_teams), dtype=np.float32)
        composite = pts.astype(np.float32) * 1000.0 + noise

        winners = np.zeros((N, 12), dtype=np.int32)
        runners = np.zeros((N, 12), dtype=np.int32)
        thirds = np.zeros((N, 12), dtype=np.int32)
        fourths = np.zeros((N, 12), dtype=np.int32)

        for g_i, t_idxs in enumerate(self.group_team_idxs):
            g_comp = composite[:, t_idxs]
            rank = np.argsort(-g_comp, axis=1)
            winners[:, g_i] = t_idxs[rank[:, 0]]
            runners[:, g_i] = t_idxs[rank[:, 1]]
            thirds[:, g_i] = t_idxs[rank[:, 2]]
            fourths[:, g_i] = t_idxs[rank[:, 3]]

        group_first_cnt = np.bincount(winners.ravel(), minlength=n_teams)
        group_second_cnt = np.bincount(runners.ravel(), minlength=n_teams)
        group_third_cnt = np.bincount(thirds.ravel(), minlength=n_teams)
        group_fourth_cnt = np.bincount(fourths.ravel(), minlength=n_teams)

        thirds_comp = composite[np.arange(N)[:, None], thirds]
        thirds_rank = np.argsort(-thirds_comp, axis=1)
        best8_local = thirds_rank[:, :8]
        best8_thirds = thirds[np.arange(N)[:, None], best8_local]

        r32_field = np.concatenate([winners, runners, best8_thirds], axis=1)

        reach = np.zeros((N, n_teams), dtype=np.int8)

        np.maximum.at(reach, (np.repeat(np.arange(N), 32), r32_field.ravel()), 1)

        bracket_home_pos = np.array([p[0] for p in R32_BRACKET], dtype=np.int32)
        bracket_away_pos = np.array([p[1] for p in R32_BRACKET], dtype=np.int32)

        r32_home = r32_field[:, bracket_home_pos]
        r32_away = r32_field[:, bracket_away_pos]

        current_field = self._run_ko_round(
            rng, N, r32_home, r32_away, reach, STAGE_IDX["r16"]
        )

        r16_home, r16_away = self._split_field(current_field)
        current_field = self._run_ko_round(
            rng, N, r16_home, r16_away, reach, STAGE_IDX["qf"]
        )

        qf_home, qf_away = self._split_field(current_field)
        current_field = self._run_ko_round(
            rng, N, qf_home, qf_away, reach, STAGE_IDX["sf"]
        )

        sf_home = current_field[:, 0:2]
        sf_away = current_field[:, 2:4]
        sf_winners = self._run_ko_round(
            rng, N, sf_home, sf_away, reach, STAGE_IDX["final"]
        )

        f_home = sf_winners[:, 0:1]
        f_away = sf_winners[:, 1:2]
        self._run_ko_round(rng, N, f_home, f_away, reach, STAGE_IDX["champion"])

        stage_counts_raw: Dict[str, Dict[str, int]] = {}
        teams_out: List[TeamResult] = []

        for t_idx, team in enumerate(self.teams):
            team_reach = reach[:, t_idx]
            probs: Dict[str, float] = {}
            ci_95: Dict[str, Tuple[float, float]] = {}
            counts: Dict[str, int] = {}

            for stage_name, s_idx in STAGE_IDX.items():
                if stage_name == "group_exit":
                    count = int((team_reach == 0).sum())
                else:
                    count = int((team_reach >= s_idx).sum())
                p = count / N
                margin = 1.96 * np.sqrt(p * (1.0 - p) / N)
                probs[stage_name] = round(p, 6)
                ci_95[stage_name] = (
                    round(max(0.0, p - margin), 6),
                    round(min(1.0, p + margin), 6),
                )
                counts[stage_name] = count

            for key, cnt_arr in [
                ("group_first", group_first_cnt),
                ("group_second", group_second_cnt),
                ("group_third", group_third_cnt),
                ("group_fourth", group_fourth_cnt),
            ]:
                p = float(cnt_arr[t_idx]) / N
                margin = 1.96 * np.sqrt(p * (1.0 - p) / N)
                probs[key] = round(p, 6)
                ci_95[key] = (
                    round(max(0.0, p - margin), 6),
                    round(min(1.0, p + margin), 6),
                )
                counts[key] = int(cnt_arr[t_idx])

            teams_out.append(
                TeamResult(
                    name=team.name,
                    group=team.group,
                    elo=team.elo,
                    fifa_rank=team.fifa_rank,
                    probs=probs,
                    ci_95=ci_95,
                )
            )
            stage_counts_raw[team.name] = counts

        elapsed = time.perf_counter() - t0
        logger.info(f"Simulation complete: {N} runs in {elapsed:.2f}s")

        return SimResult(
            n_sims=N,
            elapsed_s=round(elapsed, 3),
            teams=teams_out,
            stage_counts=stage_counts_raw,
        )

    def _get_wdl(self, home_idx: int, away_idx: int) -> Tuple[float, float, float]:
        """Lookup W/D/L prob for a match, falling back to Elo."""
        home_name = self.teams[home_idx].name
        away_name = self.teams[away_idx].name
        return self.priors.get(
            (home_name, away_name),
            self.priors.get((away_name, home_name), (0.40, 0.25, 0.35)),
        )

    def _run_ko_round(
        self,
        rng: np.random.Generator,
        N: int,
        home: np.ndarray,
        away: np.ndarray,
        reach: np.ndarray,
        winner_stage: int,
    ) -> np.ndarray:
        """
        Run one knockout round for all N sims simultaneously.

        Uses fancy numpy indexing into the precomputed ko_matrix:
            win_probs = ko_matrix[home, away]   # (N, n_matches) in one shot

        Returns: (N, n_matches) array of advancing team indices.
        """
        n_matches = home.shape[1]

        win_probs = self.ko_matrix[home, away]

        u = rng.random((N, n_matches), dtype=np.float32)
        home_wins = u < win_probs

        winners = np.where(home_wins, home, away)

        np.maximum.at(
            reach,
            (np.repeat(np.arange(N), n_matches), winners.ravel()),
            winner_stage,
        )

        return winners

    def _split_field(self, field: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Split a (N, 2k) field into (N, k) home and (N, k) away arrays for
        the next knockout round. Pairs positions 0&1, 2&3, etc."""
        return field[:, 0::2], field[:, 1::2]


# Convenience factory


def run_simulation(
    betfair_odds=None,
    n_sims: int = 50_000,
    seed: Optional[int] = None,
    elo_overrides: Optional[Dict[str, float]] = None,
) -> SimResult:
    """
    Build and run the WC 2026 tournament simulation.
    This is the main entry point for the API route.

    Args:
        betfair_odds: optional OddsTable from BetfairClient — overrides Elo priors
        n_sims:       default 50_000 (≈8s on CPU)
        seed:         optional int for reproducibility

    Returns:
        SimResult with per-team stage probabilities and 95% CIs.
    """
    sim = TournamentSimulator(
        betfair_odds=betfair_odds,
        n_sims=n_sims,
        seed=seed,
        elo_overrides=elo_overrides,
    )
    return sim.run()
