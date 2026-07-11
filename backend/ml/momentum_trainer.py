"""
Offline training pipeline for the live match momentum prediction model.

This module trains the lightweight probabilistic model used by the runtime
momentum engine. It reconstructs live match conditions from historical
StatsBomb event data, generates time-dependent features, trains a logistic
regression model, and exports calibrated coefficients for production inference.

Training pipeline:

    Historical Event Data
            ↓
    Match State Reconstruction
            ↓
    Temporal Feature Engineering
            ↓
    EWMA Momentum Features
            ↓
    Logistic Regression Optimization
            ↓
    Holdout Evaluation
            ↓
    Runtime Model Export


Core responsibilities:
    - Load historical match and event data.
    - Generate momentum features consistent with live inference.
    - Train an interpretable probabilistic scoring model.
    - Validate performance against a baseline predictor.
    - Export runtime-compatible model coefficients.

The training pipeline intentionally mirrors the online inference feature
generation process to prevent training-serving skew and ensure consistency
between offline evaluation and live predictions.
"""

import asyncio
import json
import logging
import math
import random
from collections import defaultdict, deque
from pathlib import Path

import httpx

from ml.statsbomb import (
    COMPETITION_ID,
    SB_BASE,
    SEASON_IDS,
    shot_is_on_target,
    sort_events,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ALPHA = 0.3
WINDOW_SLOTS = 15
COEF_PATH = Path(__file__).parent / "momentum_coef.json"
MAX_MATCHES = 40
FEATURE_KEYS = ["pressure", "possession", "pass_acc", "minute_norm", "score_diff"]

LR = 0.5
EPOCHS = 3000
HOLDOUT_FRAC = 0.2
SEED = 42


async def fetch_json(client: httpx.AsyncClient, url: str):
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def load_matches(client: httpx.AsyncClient) -> list:
    """
    Load historical match metadata used for model training.

    Retrieves match identifiers across configured competitions and seasons.
    These identifiers are later used to fetch event-level data for feature
    reconstruction.

    Args:
        client:
            Async HTTP client used for API requests.

    Returns:
        List of match metadata dictionaries containing information required
        for downstream event extraction.
    """
    all_matches = []
    for sid in SEASON_IDS:
        url = f"{SB_BASE}/matches/{COMPETITION_ID}/{sid}.json"
        try:
            matches = await fetch_json(client, url)
            all_matches.extend(matches)
            log.info(f"Season {sid}: {len(matches)} matches")
        except Exception as e:
            log.warning(f"Season {sid} unavailable: {e}")
    return all_matches


def build_samples(events: list, home_name: str, away_name: str) -> list:
    """
    Convert a historical event stream into supervised learning samples.

    Reconstructs match state at one-minute intervals and generates temporal
    momentum features that mirror the production inference pipeline.

    Generated features include:
        - rolling shot pressure
        - shot quality
        - possession proxy
        - passing efficiency
        - score differential
        - EWMA-smoothed signals

    Each sample predicts whether a team will score within the next five
    minutes of match time.

    Args:
        events:
            Raw StatsBomb event stream for a single match.

        home_name:
            Name of the home team.

        away_name:
            Name of the away team.

    Returns:
        List of tuples:
            (
                feature_dictionary,
                binary_scoring_label
            )

        The label is 1 when the team scores within the following five minutes,
        otherwise 0.
    """
    evs = sort_events(events)

    h = defaultdict(float)
    a = defaultdict(float)
    goals_by_minute = defaultdict(list)
    h_shots_at: dict[int, int] = {}
    a_shots_at: dict[int, int] = {}

    for ev in evs:
        team_name = (ev.get("team") or {}).get("name", "")
        etype = (ev.get("type") or {}).get("name", "")
        minute = ev.get("minute", 0)

        if team_name not in (home_name, away_name):
            continue

        s = h if team_name == home_name else a
        s["ev_total"] += 1

        if etype == "Pass":
            s["passes"] += 1
            if ev.get("pass", {}).get("outcome") is None:
                s["passes_acc"] += 1

        elif etype == "Shot":
            s["shots"] += 1
            outcome = (ev.get("shot", {}).get("outcome") or {}).get("name", "")
            if shot_is_on_target(outcome):
                s["shots_on"] += 1
            if outcome == "Goal":
                goals_by_minute[minute].append(team_name)

        h_shots_at[minute] = int(h["shots"])
        a_shots_at[minute] = int(a["shots"])

    if not h_shots_at:
        return []

    max_minute = max(h_shots_at.keys())
    samples = []

    h_shot_win = deque(maxlen=WINDOW_SLOTS)
    a_shot_win = deque(maxlen=WINDOW_SLOTS)
    prev_h = prev_a = 0
    home_score = away_score = 0
    h_ewma_press = a_ewma_press = 0.0
    h_ewma_poss = a_ewma_poss = 50.0
    h_ewma_pass = a_ewma_pass = 80.0

    for minute in range(1, max_minute + 1):
        for scorer in goals_by_minute.get(minute, []):
            if scorer == home_name:
                home_score += 1
            else:
                away_score += 1

        h_now = h_shots_at.get(minute, prev_h)
        a_now = a_shots_at.get(minute, prev_a)
        dh = max(0, h_now - prev_h)
        da = max(0, a_now - prev_a)
        prev_h, prev_a = h_now, a_now

        h_shot_win.append(dh)
        a_shot_win.append(da)

        h_qual = (h["shots_on"] / h["shots"]) if h["shots"] > 0 else 0.5
        a_qual = (a["shots_on"] / a["shots"]) if a["shots"] > 0 else 0.5

        h_press_raw = (sum(h_shot_win) / WINDOW_SLOTS) * h_qual
        a_press_raw = (sum(a_shot_win) / WINDOW_SLOTS) * a_qual

        total_ev = h["ev_total"] + a["ev_total"]
        h_poss = (h["ev_total"] / total_ev * 100) if total_ev > 0 else 50.0
        a_poss = 100.0 - h_poss

        h_pass = (h["passes_acc"] / h["passes"] * 100) if h["passes"] > 5 else 80.0
        a_pass = (a["passes_acc"] / a["passes"] * 100) if a["passes"] > 5 else 80.0

        h_ewma_press = ALPHA * h_press_raw + (1 - ALPHA) * h_ewma_press
        a_ewma_press = ALPHA * a_press_raw + (1 - ALPHA) * a_ewma_press
        h_ewma_poss = ALPHA * h_poss + (1 - ALPHA) * h_ewma_poss
        a_ewma_poss = ALPHA * a_poss + (1 - ALPHA) * a_ewma_poss
        h_ewma_pass = ALPHA * h_pass + (1 - ALPHA) * h_ewma_pass
        a_ewma_pass = ALPHA * a_pass + (1 - ALPHA) * a_ewma_pass

        min_norm = min(minute, 90) / 90.0

        home_y = int(
            any(
                home_name in goals_by_minute.get(m, [])
                for m in range(minute + 1, minute + 6)
            )
        )
        away_y = int(
            any(
                away_name in goals_by_minute.get(m, [])
                for m in range(minute + 1, minute + 6)
            )
        )

        samples.append(
            (
                {
                    "pressure": h_ewma_press,
                    "possession": h_ewma_poss / 100.0,
                    "pass_acc": h_ewma_pass / 100.0,
                    "minute_norm": min_norm,
                    "score_diff": max(-1.0, min(1.0, (home_score - away_score) / 3.0)),
                },
                home_y,
            )
        )
        samples.append(
            (
                {
                    "pressure": a_ewma_press,
                    "possession": a_ewma_poss / 100.0,
                    "pass_acc": a_ewma_pass / 100.0,
                    "minute_norm": min_norm,
                    "score_diff": max(-1.0, min(1.0, (away_score - home_score) / 3.0)),
                },
                away_y,
            )
        )

    return samples


def _sigmoid(z: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-z))
    except OverflowError:
        return 0.0 if z < 0 else 1.0


def _predict(x: dict, coef: dict) -> float:
    z = coef["intercept"]
    for k, v in x.items():
        z += coef.get(k, 0.0) * v
    return _sigmoid(z)


def _log_loss(samples: list, coef: dict) -> float:
    total = 0.0
    for x, y in samples:
        p = min(1 - 1e-9, max(1e-9, _predict(x, coef)))
        total -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return total / len(samples)


def train(samples: list, lr: float = LR, epochs: int = EPOCHS) -> dict:
    """
    Train the momentum prediction model using gradient descent.

    The training process standardizes features for optimization stability,
    learns logistic regression parameters, and converts the resulting model
    back into raw feature space for runtime inference.

    This ensures the deployed application can perform low-latency prediction
    without requiring training-time preprocessing.

    Args:
        samples:
            Training dataset containing feature dictionaries and binary labels.

        lr:
            Gradient descent learning rate.

        epochs:
            Number of optimization iterations.

    Returns:
        Dictionary containing runtime-compatible model coefficients.
    """
    n = len(samples)
    mu = {k: sum(x[k] for x, _ in samples) / n for k in FEATURE_KEYS}
    var = {k: sum((x[k] - mu[k]) ** 2 for x, _ in samples) / n for k in FEATURE_KEYS}
    sd = {k: max(1e-6, math.sqrt(var[k])) for k in FEATURE_KEYS}

    Z = [({k: (x[k] - mu[k]) / sd[k] for k in FEATURE_KEYS}, y) for x, y in samples]

    pos_rate = sum(y for _, y in Z) / n
    coef = {"intercept": math.log(pos_rate / max(1e-9, 1 - pos_rate))}
    coef.update({k: 0.0 for k in FEATURE_KEYS})

    log.info(f"Training: n={n}  positive_rate={pos_rate:.3f}  lr={lr}  epochs={epochs}")

    for epoch in range(epochs):
        grads = {k: 0.0 for k in coef}
        for x, y in Z:
            err = _predict(x, coef) - y
            grads["intercept"] += err
            for k in FEATURE_KEYS:
                grads[k] += err * x[k]
        for k in coef:
            coef[k] -= lr * grads[k] / n

        if epoch % 500 == 0 or epoch == epochs - 1:
            log.info(
                f"  Epoch {epoch:4d}  loss={_log_loss(Z, coef):.4f}  "
                f"pressure(z)={coef['pressure']:.3f}  "
                f"possession(z)={coef['possession']:.3f}"
            )

    raw = {k: coef[k] / sd[k] for k in FEATURE_KEYS}
    raw["intercept"] = coef["intercept"] - sum(
        coef[k] * mu[k] / sd[k] for k in FEATURE_KEYS
    )
    return raw


async def main() -> None:
    """
    Execute the complete momentum model training workflow.

    Pipeline:

        Historical Matches
              ↓
        Event Extraction
              ↓
        Feature Engineering
              ↓
        Model Training
              ↓
        Holdout Evaluation
              ↓
        Coefficient Export


    The trained model is exported only when it outperforms a baseline
    predictor on unseen validation data, reducing the risk of deploying
    overfit or unstable model artifacts.

    Returns:
        None.
    """
    log.info("=== Momentum model training ===")

    async with httpx.AsyncClient(
        headers={"User-Agent": "wc2026-trainer/1.0"},
        follow_redirects=True,
    ) as client:
        all_matches = await load_matches(client)
        log.info(f"Total matches available: {len(all_matches)}")

        rng = random.Random(SEED)
        rng.shuffle(all_matches)
        use = all_matches[:MAX_MATCHES]
        n_holdout = max(1, int(len(use) * HOLDOUT_FRAC))
        holdout_matches, train_matches = use[:n_holdout], use[n_holdout:]

        async def collect(matches: list) -> list:
            out = []
            for i, m in enumerate(matches):
                home = m["home_team"]["home_team_name"]
                away = m["away_team"]["away_team_name"]
                try:
                    events = await fetch_json(
                        client, f"{SB_BASE}/events/{m['match_id']}.json"
                    )
                    s = build_samples(events, home, away)
                    out.extend(s)
                    log.info(
                        f"  [{i + 1:2d}/{len(matches)}]  {home} vs {away}: {len(s)} samples"
                    )
                except Exception as e:
                    log.warning(f"  {home} vs {away}: failed — {e}")
            return out

        train_samples = await collect(train_matches)
        holdout_samples = await collect(holdout_matches)

    if not train_samples or not holdout_samples:
        log.error("Not enough data collected — aborting without writing coefficients")
        return

    coef = train(train_samples)

    log.info("\nFinal raw-space coefficients:")
    for k, v in coef.items():
        log.info(f"  {k:15s}: {v:+.4f}")

    base_rate = sum(y for _, y in train_samples) / len(train_samples)
    baseline = {"intercept": math.log(base_rate / (1 - base_rate))}
    baseline.update({k: 0.0 for k in FEATURE_KEYS})

    model_ll = _log_loss(holdout_samples, coef)
    base_ll = _log_loss(holdout_samples, baseline)
    log.info(
        f"\nHeld-out ({len(holdout_matches)} matches, {len(holdout_samples)} samples): "
        f"model log-loss={model_ll:.4f}  base-rate log-loss={base_ll:.4f}  "
        f"improvement={base_ll - model_ll:+.4f}"
    )

    if model_ll >= base_ll:
        log.error(
            "Trained model does NOT beat the base-rate baseline on held-out "
            "data — refusing to write momentum_coef.json. The runtime will "
            "keep using the calibrated defaults."
        )
        return

    with open(COEF_PATH, "w") as f:
        json.dump(coef, f, indent=2)
    log.info(f"\nSaved → {COEF_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
