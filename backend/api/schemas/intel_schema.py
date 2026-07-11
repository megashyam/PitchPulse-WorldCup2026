"""
schemas/intel.py

Pydantic models for match intelligence feed responses.
Used by API routes and frontend timeline components.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class IntelEntry(BaseModel):
    """
    Single AI-generated match insight.
    Stored in Redis feed and streamed to frontend.
    """

    fixture_id: int

    # Match minute used for ordering and stale-entry filtering.
    minute: int

    # tactical | event_reaction | xg_divergence
    narration_type: str

    # Generated explanation shown to users.
    narrative: str

    # Model-calculated importance score.
    score: float

    # Number of retrieved RAG documents used.
    rag_docs_used: int

    # Generation source: mistral | groq | template.
    via: str

    updated_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class IntelFeed(BaseModel):
    """
    Full intelligence timeline for one fixture.
    """

    fixture_id: int

    # Newest-first list of insights.
    entries: List[IntelEntry]

    # Empty feeds may not have a timestamp yet.
    updated_at: Optional[datetime] = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
