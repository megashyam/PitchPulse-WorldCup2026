"""Backtests the Poisson in-play model against real World Cup outcomes.

For each match, reconstructs the score and red-card state at fixed
checkpoints (15', 45', 75'), scores the resulting W/D/L distribution against
the actual result, and reports log-loss and Brier score per checkpoint
against the pre-match prior and base-rate baselines.

Uses StatsBomb Open Data
"""

from __future__ import annotations

import argparse
import json
import math
from typing import Dict, List, Tuple

import httpx

from ml.backtest_elo_wdl import (
    ELO_START,
    HOME_ADV,
    load_matches,
    outcome_index,
    update_elo,
)
from ml.in_play import inplay_wdl
from ml.prior_builder import elo_to_wdl
from ml.statsbomb import SB_BASE, card_from_event

CHECKPOINTS = [15, 45, 75]
EPS = 1e-12


def match_timeline(events: List[dict], home: str, away: str):
    """Extract (minute, is_home) goal list and red-card minutes per side."""
    goals: List[Tuple[int, bool]] = []
    reds: List[Tuple[int, bool]] = []
    for ev in events:
        team = ev.get("team", {}).get("name", "")
        if team not in (home, away):
            continue
        is_home = team == home
        minute = int(ev.get("minute", 0))
        etype = (ev.get("type") or {}).get("name", "")
        if (
            etype == "Shot"
            and (ev.get("shot", {}).get("outcome", {}) or {}).get("name") == "Goal"
        ):
            goals.append((minute, is_home))
        elif etype == "Own Goal For":
            goals.append((minute, is_home))
        if card_from_event(ev) == "red":
            reds.append((minute, is_home))
    return goals, reds


def state_at(goals, reds, minute: int) -> Tuple[int, int, int, int]:
    hs = sum(1 for m, h in goals if m <= minute and h)
    as_ = sum(1 for m, h in goals if m <= minute and not h)
    rh = sum(1 for m, h in reds if m <= minute and h)
    ra = sum(1 for m, h in reds if m <= minute and not h)
    return hs, as_, rh, ra


def log_loss(preds, actuals) -> float:
    return sum(-math.log(max(p[y], EPS)) for p, y in zip(preds, actuals)) / len(preds)


def brier(preds, actuals) -> float:
    total = 0.0
    for p, y in zip(preds, actuals):
        t = [0.0, 0.0, 0.0]
        t[y] = 1.0
        total += sum((p[k] - t[k]) ** 2 for k in range(3))
    return total / len(preds)


def run(max_matches: int) -> dict:
    matches = load_matches()
    elo: Dict[str, float] = {}

    # warm Elo on the first half
    half = len(matches) // 2
    for m in matches[:half]:
        update_elo(
            elo,
            m["home_team"]["home_team_name"],
            m["away_team"]["away_team_name"],
            int(m["home_score"]),
            int(m["away_score"]),
        )

    eval_matches = matches[half : half + max_matches]

    preds = {cp: [] for cp in CHECKPOINTS}
    prior_preds: List[Tuple[float, float, float]] = []
    actuals: List[int] = []

    with httpx.Client(timeout=30.0) as client:
        for m in eval_matches:
            home = m["home_team"]["home_team_name"]
            away = m["away_team"]["away_team_name"]
            hs_ft, as_ft = int(m["home_score"]), int(m["away_score"])

            try:
                r = client.get(f"{SB_BASE}/events/{m['match_id']}.json")
                r.raise_for_status()
                events = r.json()
            except Exception as exc:
                print(f"  skip {home} vs {away}: {exc}")
                continue

            goals, reds = match_timeline(events, home, away)
            pre = elo_to_wdl(
                elo.get(home, ELO_START) + HOME_ADV, elo.get(away, ELO_START)
            )
            prior_preds.append(pre)
            actuals.append(outcome_index(hs_ft, as_ft))

            for cp in CHECKPOINTS:
                hs, as_, rh, ra = state_at(goals, reds, cp)
                preds[cp].append(inplay_wdl(pre, cp, hs, as_, rh, ra))

            update_elo(elo, home, away, hs_ft, as_ft)

    n = len(actuals)
    if n == 0:
        raise SystemExit("No matches evaluated")
    base = (
        sum(1 for a in actuals if a == 0) / n,
        sum(1 for a in actuals if a == 1) / n,
        sum(1 for a in actuals if a == 2) / n,
    )
    report = {
        "n_matches": n,
        "baselines": {
            "pre_match_prior": {
                "log_loss": round(log_loss(prior_preds, actuals), 4),
                "brier": round(brier(prior_preds, actuals), 4),
            },
            "base_rate": {
                "log_loss": round(log_loss([base] * n, actuals), 4),
                "brier": round(brier([base] * n, actuals), 4),
            },
        },
        "in_play_by_checkpoint": {
            f"minute_{cp}": {
                "log_loss": round(log_loss(preds[cp], actuals), 4),
                "brier": round(brier(preds[cp], actuals), 4),
            }
            for cp in CHECKPOINTS
        },
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-matches", type=int, default=12)
    ap.add_argument("--json", help="write report to this path")
    args = ap.parse_args()

    report = run(args.max_matches)

    print(f"\nIn-play calibration — {report['n_matches']} warmed-up WC matches")
    pm = report["baselines"]["pre_match_prior"]
    br = report["baselines"]["base_rate"]
    print(f"  pre-match prior : log-loss {pm['log_loss']}  brier {pm['brier']}")
    print(f"  base rate       : log-loss {br['log_loss']}  brier {br['brier']}")
    for cp, m in report["in_play_by_checkpoint"].items():
        print(f"  in-play @{cp:>10}: log-loss {m['log_loss']}  brier {m['brier']}")
    print(
        "\nExpected: in-play log-loss should fall monotonically with the "
        "checkpoint minute and undercut the pre-match prior."
    )

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Wrote {args.json}")


if __name__ == "__main__":
    main()
