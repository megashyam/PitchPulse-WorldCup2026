"""Offline evaluation of the narrative spike detector's IsolationForest
configuration (contamination=0.05, threshold=-0.10, 72h window).

Generates synthetic four-source signal streams matching the detector's mock
generator, injects labeled spikes of varying magnitude, and sweeps the
decision threshold to report precision, recall, and F1 per threshold.

"""

from __future__ import annotations

import argparse
import json

import numpy as np
from sklearn.ensemble import IsolationForest

CONTAMINATION = 0.05
N_ESTIMATORS = 100
PROD_THRESHOLD = -0.10


def synth_stream(rng, n_ticks: int, spike_rate: float, spike_mag: float):
    """4-dim activity stream (mastodon, bluesky, trends, wikipedia) with
    labeled injected spikes. Returns (X, y)."""
    t = np.arange(n_ticks)
    X = np.column_stack(
        [
            5 + 2 * np.sin(t / 37) + rng.normal(0, 0.5, n_ticks),
            3 + 1.5 * np.sin(t / 23 + 1.1) + rng.normal(0, 0.4, n_ticks),
            40 + 8 * np.sin(t / 61 + 2.3) + rng.normal(0, 2.0, n_ticks),
            2 + 0.8 * np.sin(t / 47 + 0.6) + rng.normal(0, 0.3, n_ticks),
        ]
    )
    y = np.zeros(n_ticks, dtype=bool)
    spikes = rng.random(n_ticks) < spike_rate
    n_sources_moved = rng.integers(2, 5, size=n_ticks)
    for i in np.where(spikes)[0]:
        idx = rng.choice(4, size=n_sources_moved[i], replace=False)
        X[i, idx] *= spike_mag * (0.8 + 0.4 * rng.random())
        y[i] = True
    return X, y


def run(seeds: int, threshold_grid: list[float]) -> dict:
    rows = {f"{th:+.2f}": {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for th in threshold_grid}

    for s in range(seeds):
        rng = np.random.default_rng(s)
        train_X, _ = synth_stream(rng, 4320, spike_rate=0.0, spike_mag=1.0)  # 72h clean
        test_X, test_y = synth_stream(rng, 1440, spike_rate=0.02, spike_mag=4.0)

        model = IsolationForest(
            contamination=CONTAMINATION, n_estimators=N_ESTIMATORS, random_state=42
        ).fit(train_X)
        scores = model.decision_function(test_X)

        for th in threshold_grid:
            pred = scores < th
            r = rows[f"{th:+.2f}"]
            r["tp"] += int((pred & test_y).sum())
            r["fp"] += int((pred & ~test_y).sum())
            r["fn"] += int((~pred & test_y).sum())
            r["tn"] += int((~pred & ~test_y).sum())

    report = {}
    for th, r in rows.items():
        p = r["tp"] / max(r["tp"] + r["fp"], 1)
        rec = r["tp"] / max(r["tp"] + r["fn"], 1)
        f1 = 2 * p * rec / max(p + rec, 1e-12)
        fp_per_day = r["fp"] / (seeds * 1440 / 1440)  # test window = 1 day
        report[th] = {
            "precision": round(p, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "false_alarms_per_topic_day": round(fp_per_day / seeds, 2),
        }
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--json", help="write report to this path")
    args = ap.parse_args()

    grid = [-0.20, -0.15, -0.10, -0.05, 0.00, 0.05]
    report = run(args.seeds, grid)

    print(
        f"\nIsolationForest threshold sweep — contamination={CONTAMINATION}, "
        f"{args.seeds} seeds, spikes move 2-4 sources at ~4x baseline\n"
    )
    print(
        f"{'threshold':>10} {'precision':>10} {'recall':>8} {'F1':>8} {'FA/topic-day':>13}"
    )
    for th, m in report.items():
        marker = "  ← production" if float(th) == PROD_THRESHOLD else ""
        print(
            f"{th:>10} {m['precision']:>10} {m['recall']:>8} {m['f1']:>8} "
            f"{m['false_alarms_per_topic_day']:>13}{marker}"
        )

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
