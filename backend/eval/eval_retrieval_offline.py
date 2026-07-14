"""Offline evaluation of the hybrid (dense + BM25) retrieval path.

Builds a synthetic labeled corpus in the `rag_indexer.py` document format
(goal, red-card, and momentum-shift narratives plus distractors), then
computes Recall@K, Precision@K, MRR, and NDCG@K across a dense/BM25 alpha
sweep, including an ablation of the `event_type` filter.

Uses `sentence-transformers/all-MiniLM-L6-v2` when available, else TF-IDF.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field

import numpy as np

TEAMS = [
    ("Spain", "Germany"),
    ("Brazil", "France"),
    ("Argentina", "Netherlands"),
    ("England", "Croatia"),
    ("Portugal", "Morocco"),
    ("Japan", "Mexico"),
    ("USA", "Senegal"),
    ("Uruguay", "Ghana"),
    ("Belgium", "Canada"),
    ("Poland", "Australia"),
    ("Switzerland", "Serbia"),
    ("Korea", "Ecuador"),
]


def goal_doc(home, away, minute, hs, as_, dom, poss) -> str:
    return (
        f"World Cup 2022 · {home} vs {away} · Minute {minute} · Goal\n"
        f"Situation: Score was {hs - 1}-{as_}, {home} scored to make it {hs}-{as_}.\n"
        f"Tactical context: {dom} dominated with {poss}% possession. "
        f"{home} shots: {minute // 8}, xG: {minute / 60:.2f}. "
        f"{away} shots: {minute // 11}, xG: {minute / 90:.2f}.\n"
        f"Pattern: Goal came during sustained {dom} pressure phase."
    )


def red_doc(home, away, minute, hs, as_, offender) -> str:
    other = away if offender == home else home
    return (
        f"World Cup 2022 · {home} vs {away} · Minute {minute} · Red Card\n"
        f"Situation: Score {hs}-{as_}, {offender} reduced to 10 men.\n"
        f"Tactical context: {home} possession 52%, {away} 48%. "
        f"{other} gained numerical advantage with {90 - minute} minutes remaining.\n"
        f"Pattern: Man disadvantage mid-match typically shifts momentum and bracket implications."
    )


def momentum_doc(home, away, m0, m1, team, p0, p1) -> str:
    return (
        f"World Cup 2022 · {home} vs {away} · Minutes {m0}-{m1} · Momentum Shift\n"
        f"Situation: Score 1-1, {team} momentum shift.\n"
        f"Tactical context: {team} possession moved from {p0}% to {p1}% — "
        f"a {p1 - p0}-point swing over {m1 - m0} minutes.\n"
        f"Pattern: Sustained territorial gain suggesting tactical or fatigue-driven phase change."
    )


def distractor(i: int) -> str:
    subjects = [
        "stadium capacity and turf maintenance schedules",
        "broadcast rights allocation across regional networks",
        "team travel logistics and hotel arrangements",
        "referee appointment committee procedures",
        "ticket pricing tiers for group stage fixtures",
        "merchandising revenue for the host federation",
    ]
    return (
        f"World Cup 2026 administrative note {i} · "
        f"Discussion of {subjects[i % len(subjects)]}. No match events occurred."
    )


@dataclass
class Corpus:
    docs: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)  # goal / red_card / momentum / noise
    teams: list[tuple[str, str]] = field(default_factory=list)


def build_corpus() -> Corpus:
    """Adversarial corpus: every team appears in SEVERAL pairings and several
    event types, so team-name overlap alone cannot solve a query. Relevance is
    (pairing AND event type AND situation)."""
    c = Corpus()
    pool = [t for pair in TEAMS for t in pair]

    def add(doc, kind, teams):
        c.docs.append(doc)
        c.kinds.append(kind)
        c.teams.append(teams)

    for i, (h, a) in enumerate(TEAMS):
        add(goal_doc(h, a, 20 + 3 * i, 1, 0, h, 55 + i % 10), "goal", (h, a))
        add(red_doc(h, a, 35 + i, 1, 1, a), "red_card", (h, a))
        add(momentum_doc(h, a, 50 + i, 65 + i, h, 42, 61), "momentum", (h, a))
        alt = pool[(2 * i + 5) % len(pool)]
        if alt not in (h, a):
            add(goal_doc(h, alt, 70 + i, 2, 2, alt, 60), "goal", (h, alt))
            add(red_doc(alt, h, 15 + i, 0, 0, h), "red_card", (alt, h))
        add(momentum_doc(a, h, 10 + i, 25 + i, a, 55, 39), "momentum", (a, h))
    for i in range(24):
        add(distractor(i), "noise", ("", ""))
    return c


PARAPHRASE_GOAL = [
    "{h} strike to break the deadlock versus {a}, sustained attacking spell",
    "opener for {h} while pinning {a} back in their own half",
    "{h} finding the net against {a} amid heavy territorial dominance",
]
PARAPHRASE_RED = [
    "{off} man sent off facing {other}, playing a man light",
    "dismissal leaves {off} shorthanded against {other} for the remainder",
    "{off} reduced numbers, {other} with the extra man on the pitch",
]
PARAPHRASE_MOM = [
    "{team} seizing control of territory versus {opp}, tide turning",
    "surge in field position for {team} against {opp} across a quarter hour",
]


def build_queries(c: Corpus) -> list[dict]:
    """Paraphrased agent-style queries. Relevant = exact pairing + event type
    (the doc generated for that fixture), competing against same-team
    confusers of the same event type."""
    qs = []
    for i, (h, a) in enumerate(TEAMS):
        rel_goal = {
            j
            for j, (k, t) in enumerate(zip(c.kinds, c.teams))
            if k == "goal" and t == (h, a)
        }
        qs.append(
            {
                "query": PARAPHRASE_GOAL[i % len(PARAPHRASE_GOAL)].format(h=h, a=a),
                "relevant": rel_goal,
                "event_filter": "goal",
            }
        )
        rel_red = {
            j
            for j, (k, t) in enumerate(zip(c.kinds, c.teams))
            if k == "red_card" and t == (h, a)
        }
        qs.append(
            {
                "query": PARAPHRASE_RED[i % len(PARAPHRASE_RED)].format(off=a, other=h),
                "relevant": rel_red,
                "event_filter": "red_card",
            }
        )
        rel_mom = {
            j
            for j, (k, t) in enumerate(zip(c.kinds, c.teams))
            if k == "momentum" and t == (h, a)
        }
        qs.append(
            {
                "query": PARAPHRASE_MOM[i % len(PARAPHRASE_MOM)].format(team=h, opp=a),
                "relevant": rel_mom,
                "event_filter": None,
            }
        )
    return qs


def get_dense_encoder():
    try:
        from sentence_transformers import SentenceTransformer  # noqa

        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

        def enc(texts):
            return np.asarray(model.encode(texts, normalize_embeddings=True))

        return enc, "all-MiniLM-L6-v2 (production encoder)"
    except Exception:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2))

        state = {}

        def enc(texts):
            if "fitted" not in state:
                state["fitted"] = vec.fit(texts)
            m = vec.transform(texts).toarray()
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            return m / np.maximum(norms, 1e-12)

        return enc, "TF-IDF fallback (no local MiniLM cache — fusion-logic test only)"


_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(t: str) -> list[str]:
    return _TOKEN.findall(t.lower())


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.toks = [tokenize(d) for d in docs]
        self.dl = np.array([len(t) for t in self.toks], dtype=float)
        self.avgdl = self.dl.mean()
        self.df: dict[str, int] = {}
        for t in self.toks:
            for w in set(t):
                self.df[w] = self.df.get(w, 0) + 1
        self.N = len(docs)

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(self.N)
        for w in tokenize(query):
            n = self.df.get(w)
            if not n:
                continue
            idf = math.log(1 + (self.N - n + 0.5) / (n + 0.5))
            for i, toks in enumerate(self.toks):
                tf = toks.count(w)
                if tf:
                    out[i] += (
                        idf
                        * tf
                        * (self.k1 + 1)
                        / (
                            tf
                            + self.k1 * (1 - self.b + self.b * self.dl[i] / self.avgdl)
                        )
                    )
        return out


def evaluate(ranked: list[int], relevant: set[int], k: int) -> dict:
    top = ranked[:k]
    hits = sum(1 for i in top if i in relevant)
    recall = hits / len(relevant) if relevant else 0.0
    precision = hits / k
    rr = 0.0
    for rank, i in enumerate(ranked, 1):
        if i in relevant:
            rr = 1.0 / rank
            break
    dcg = sum(1.0 / math.log2(r + 1) for r, i in enumerate(top, 1) if i in relevant)
    idcg = sum(1.0 / math.log2(r + 1) for r in range(1, min(len(relevant), k) + 1))
    return {
        "recall": recall,
        "precision": precision,
        "mrr": rr,
        "ndcg": dcg / idcg if idcg else 0.0,
    }


def run(alphas: list[float], k: int = 5) -> dict:
    corpus = build_corpus()
    queries = build_queries(corpus)
    enc, encoder_name = get_dense_encoder()

    doc_vecs = enc(corpus.docs)
    bm25 = BM25(corpus.docs)
    kinds = np.array(corpus.kinds)

    def rank(query: str, alpha: float, event_filter) -> list[int]:
        qv = enc([query])[0]
        dense = doc_vecs @ qv  # cosine (normalized)
        sparse = bm25.scores(query)
        if sparse.max() > 0:
            sparse = sparse / sparse.max()
        if dense.max() > dense.min():
            dense = (dense - dense.min()) / (dense.max() - dense.min())
        score = alpha * dense + (1 - alpha) * sparse
        if event_filter is not None:  # mirrors Weaviate event_type filter
            score = np.where(kinds == event_filter, score, -np.inf)
        return list(np.argsort(-score))

    results = {}
    for alpha in alphas:
        agg = {"recall": [], "precision": [], "mrr": [], "ndcg": []}
        for q in queries:
            m = evaluate(rank(q["query"], alpha, q["event_filter"]), q["relevant"], k)
            for key in agg:
                agg[key].append(m[key])
        results[f"alpha={alpha:.2f}"] = {
            f"{key}@{k}" if key != "mrr" else "mrr": round(float(np.mean(v)), 4)
            for key, v in agg.items()
        }

    # filter ablation at production alpha
    agg_nf = {"recall": [], "mrr": []}
    for q in queries:
        m = evaluate(rank(q["query"], 0.75, None), q["relevant"], k)
        agg_nf["recall"].append(m["recall"])
        agg_nf["mrr"].append(m["mrr"])

    return {
        "encoder": encoder_name,
        "corpus_size": len(corpus.docs),
        "n_queries": len(queries),
        "k": k,
        "by_alpha": results,
        "event_filter_ablation": {
            "with_filter (production)": results.get("alpha=0.75"),
            "without_filter": {
                f"recall@{k}": round(float(np.mean(agg_nf["recall"])), 4),
                "mrr": round(float(np.mean(agg_nf["mrr"])), 4),
            },
        },
        "note": (
            "alpha=1.0 is dense-only, alpha=0.0 is BM25-only; production uses 0.75. "
            "If encoder is the TF-IDF fallback, treat numbers as a fusion-logic "
            "check, and re-run with MiniLM cached for production-representative "
            "metrics."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alphas", default="0,0.25,0.5,0.75,1.0")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--json", help="write report to this path")
    args = ap.parse_args()

    alphas = [float(x) for x in args.alphas.split(",")]
    report = run(alphas, args.k)

    print(f"\nOffline retrieval eval — encoder: {report['encoder']}")
    print(
        f"corpus={report['corpus_size']} docs, queries={report['n_queries']}, K={report['k']}\n"
    )
    print(f"{'config':>12} {'recall@K':>9} {'prec@K':>8} {'MRR':>7} {'NDCG@K':>7}")
    for cfg, m in report["by_alpha"].items():
        print(
            f"{cfg:>12} {m[f'recall@{args.k}']:>9} {m[f'precision@{args.k}']:>8} "
            f"{m['mrr']:>7} {m[f'ndcg@{args.k}']:>7}"
        )
    nf = report["event_filter_ablation"]["without_filter"]
    print(
        f"\nevent_type filter off (alpha=0.75): recall@{args.k}={nf[f'recall@{args.k}']} "
        f"mrr={nf['mrr']}"
    )

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
