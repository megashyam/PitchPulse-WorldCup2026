"""Backtest for the Elo-to-W/D/L mapping used by the tournament simulator.

The script replays historical World Cup matches in chronological order,
scores the predicted outcome distribution against actual results, and reports
both aggregate and warmed-up calibration metrics.

Run from backend/:
     PYTHONPATH=. python ml/backtest_elo_wdl.py
     PYTHONPATH=. python ml/backtest_elo_wdl.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import math
from typing import Dict, List, Tuple

import httpx

from ml.prior_builder import elo_to_wdl

SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
COMPETITION_ID = 43
SEASON_IDS = [106, 3]

ELO_START = 1500.0
ELO_K = 40.0
HOME_ADV = 60.0

EPS = 1e-12


def load_matches() -> List[dict]:
    matches: List[dict] = []
    with httpx.Client(timeout=30.0) as client:
        for sid in SEASON_IDS:
            url = f"{SB_BASE}/matches/{COMPETITION_ID}/{sid}.json"
            r = client.get(url)
            r.raise_for_status()
            for m in r.json():
                if m.get("home_score") is None or m.get("away_score") is None:
                    continue
                matches.append(m)
    matches.sort(key=lambda m: (m.get("match_date", ""), m.get("kick_off", "")))
    return matches


# Elo online update


def _expected(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def _gd_multiplier(goal_diff: int) -> float:
    """FIFA-style goal-difference weighting of the Elo update."""
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11.0 + g) / 8.0


def update_elo(elo: Dict[str, float], home: str, away: str, hs: int, as_: int) -> None:
    ra = elo.get(home, ELO_START) + HOME_ADV
    rb = elo.get(away, ELO_START)
    exp_home = _expected(ra, rb)
    if hs > as_:
        score_home = 1.0
    elif hs == as_:
        score_home = 0.5
    else:
        score_home = 0.0
    mult = _gd_multiplier(hs - as_)
    delta = ELO_K * mult * (score_home - exp_home)
    elo[home] = elo.get(home, ELO_START) + delta
    elo[away] = elo.get(away, ELO_START) - delta


# Metrics


def outcome_index(hs: int, as_: int) -> int:
    """0 = home win, 1 = draw, 2 = away win (matches elo_to_wdl order)."""
    if hs > as_:
        return 0
    if hs == as_:
        return 1
    return 2


def log_loss(preds: List[Tuple[float, float, float]], actuals: List[int]) -> float:
    total = 0.0
    for p, y in zip(preds, actuals):
        total += -math.log(max(p[y], EPS))
    return total / len(preds)


def brier(preds: List[Tuple[float, float, float]], actuals: List[int]) -> float:
    total = 0.0
    for p, y in zip(preds, actuals):
        target = [0.0, 0.0, 0.0]
        target[y] = 1.0
        total += sum((p[k] - target[k]) ** 2 for k in range(3))
    return total / len(preds)


def base_rate(actuals: List[int]) -> Tuple[float, float, float]:
    n = len(actuals)
    c = [actuals.count(0), actuals.count(1), actuals.count(2)]
    return (c[0] / n, c[1] / n, c[2] / n)


def reliability_table(
    preds: List[Tuple[float, float, float]],
    actuals: List[int],
    n_bins: int = 10,
) -> List[dict]:
    """Bucket the predicted home-win probability and compare to the realised
    home-win frequency in each bucket. A well-calibrated model tracks the
    diagonal."""
    buckets: List[dict] = [
        {"lo": i / n_bins, "hi": (i + 1) / n_bins, "n": 0, "pred_sum": 0.0, "hits": 0}
        for i in range(n_bins)
    ]
    for p, y in zip(preds, actuals):
        ph = min(0.999999, max(0.0, p[0]))
        b = int(ph * n_bins)
        buckets[b]["n"] += 1
        buckets[b]["pred_sum"] += ph
        if y == 0:
            buckets[b]["hits"] += 1
    out = []
    for b in buckets:
        if b["n"] == 0:
            continue
        out.append(
            {
                "range": f"{b['lo']:.1f}-{b['hi']:.1f}",
                "n": b["n"],
                "mean_pred": round(b["pred_sum"] / b["n"], 3),
                "emp_freq": round(b["hits"] / b["n"], 3),
            }
        )
    return out


# Backtest driver


def run_backtest() -> dict:
    matches = load_matches()
    elo: Dict[str, float] = {}

    preds: List[Tuple[float, float, float]] = []
    actuals: List[int] = []

    for m in matches:
        home = m["home_team"]["home_team_name"]
        away = m["away_team"]["away_team_name"]
        hs = int(m["home_score"])
        as_ = int(m["away_score"])

        ra = elo.get(home, ELO_START) + HOME_ADV
        rb = elo.get(away, ELO_START)
        preds.append(elo_to_wdl(ra, rb))
        actuals.append(outcome_index(hs, as_))

        update_elo(elo, home, away, hs, as_)

    n = len(preds)
    half = n // 2

    base = base_rate(actuals)
    base_preds = [base] * n

    def block(p, a) -> dict:
        return {
            "n": len(p),
            "log_loss": round(log_loss(p, a), 4),
            "brier": round(brier(p, a), 4),
        }

    report = {
        "n_matches": n,
        "seasons": SEASON_IDS,
        "outcome_base_rates": {
            "home_win": round(base[0], 3),
            "draw": round(base[1], 3),
            "away_win": round(base[2], 3),
        },
        "overall": {
            "elo": block(preds, actuals),
            "baseline": block(base_preds, actuals),
        },
        "warmed_up_second_half": {
            "elo": block(preds[half:], actuals[half:]),
            "baseline": block([base] * (n - half), actuals[half:]),
        },
        "reliability_second_half": reliability_table(preds[half:], actuals[half:]),
    }
    return report


def _print(report: dict) -> None:
    print(
        f"\nElo→WDL calibration backtest — {report['n_matches']} WC matches "
        f"(seasons {report['seasons']})"
    )
    br = report["outcome_base_rates"]
    print(
        f"Base rates:  home {br['home_win']}  draw {br['draw']}  away {br['away_win']}"
    )

    for label, key in [
        ("Overall", "overall"),
        ("Second half (warmed up)", "warmed_up_second_half"),
    ]:
        e = report[key]["elo"]
        b = report[key]["baseline"]
        print(f"\n{label}  (n={e['n']})")
        print(
            f"  log loss   Elo {e['log_loss']:.4f}   baseline {b['log_loss']:.4f}   "
            f"{'BEATS' if e['log_loss'] < b['log_loss'] else 'loses to'} baseline"
        )
        print(f"  Brier      Elo {e['brier']:.4f}   baseline {b['brier']:.4f}")

    print("\nReliability (second half) — predicted home-win prob vs realised:")
    print(f"  {'bucket':>10} {'n':>4} {'mean_pred':>10} {'emp_freq':>9}")
    for row in report["reliability_second_half"]:
        print(
            f"  {row['range']:>10} {row['n']:>4} {row['mean_pred']:>10} {row['emp_freq']:>9}"
        )
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", help="write the full report to this path")
    args = ap.parse_args()

    report = run_backtest()
    _print(report)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Wrote {args.json}")


if __name__ == "__main__":
    main()
