from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TeamMomentumData(BaseModel):
    momentum_score: float
    goal_prob_5min: float
    ewma_possession: float
    ewma_pressure: float
    ewma_pass_acc: float
    bump: float


class MomentumSnapshot(BaseModel):
    fixture_id: int
    home_name: str
    away_name: str
    elapsed: Optional[int] = None
    home: TeamMomentumData
    away: TeamMomentumData
    updated_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
