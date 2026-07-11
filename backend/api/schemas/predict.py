"""
Pydantic models for tournament prediction API responses.

Separates:
- stage-level probabilities
- team tournament outcomes
- simulation lifecycle responses
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class StageProbability(BaseModel):
    """Probability and confidence interval for a single tournament stage."""

    p: float = 0.0
    ci_lo: float = 0.0
    ci_hi: float = 0.0


class TeamPrediction(BaseModel):
    """Per-team tournament probabilities returned to the UI."""

    name: str
    group: str
    elo: float
    fifa_rank: int

    group_exit: StageProbability = Field(default_factory=StageProbability)
    group_first: StageProbability = Field(default_factory=StageProbability)
    group_second: StageProbability = Field(default_factory=StageProbability)
    group_third: StageProbability = Field(default_factory=StageProbability)
    group_fourth: StageProbability = Field(default_factory=StageProbability)

    r32: StageProbability = Field(default_factory=StageProbability)
    r16: StageProbability = Field(default_factory=StageProbability)
    qf: StageProbability = Field(default_factory=StageProbability)
    sf: StageProbability = Field(default_factory=StageProbability)
    final: StageProbability = Field(default_factory=StageProbability)
    champion: StageProbability = Field(default_factory=StageProbability)

    @classmethod
    def from_result(cls, r) -> "TeamPrediction":
        """Convert the simulator result model into the API response shape."""

        def sp(stage: str) -> StageProbability:
            p = r.probs.get(stage, 0.0)
            lo, hi = r.ci_95.get(stage, (0.0, 0.0))
            return StageProbability(p=p, ci_lo=lo, ci_hi=hi)

        return cls(
            name=r.name,
            group=r.group,
            elo=r.elo,
            fifa_rank=r.fifa_rank,
            group_exit=sp("group_exit"),
            group_first=sp("group_first"),
            group_second=sp("group_second"),
            group_third=sp("group_third"),
            group_fourth=sp("group_fourth"),
            r32=sp("r32"),
            r16=sp("r16"),
            qf=sp("qf"),
            sf=sp("sf"),
            final=sp("final"),
            champion=sp("champion"),
        )


class TournamentPrediction(BaseModel):
    """Top-level tournament prediction payload."""

    sim_id: str
    n_sims: int
    elapsed_s: float
    run_at: datetime
    teams: List[TeamPrediction]
    status: str = "complete"


class SimStatus(BaseModel):
    """Current lifecycle state for an in-flight tournament simulation."""

    status: str
    sim_id: Optional[str] = None
    started_at: Optional[datetime] = None
    error: Optional[str] = None


class SimTriggerResponse(BaseModel):
    """Response returned when a new simulation is queued."""

    accepted: bool
    message: str
    sim_id: str
