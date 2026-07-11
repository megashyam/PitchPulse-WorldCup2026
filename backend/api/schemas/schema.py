"""Pydantic models and compatibility aliases for match state.

Central schema shared by:
- API ingestion workers
- Redis match-state storage
- AI agents (intel/counterfactual/briefing)
- Frontend response serialization

Keeps every service aligned on the same match representation.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ApiFixtureStatus(BaseModel):
    """Raw fixture status received from external football API."""

    long: str
    short: str
    elapsed: Optional[int] = None


class ApiTeamInfo(BaseModel):
    """Raw team metadata from external provider."""

    id: int
    name: str
    logo: str
    winner: Optional[bool] = None


# Backward compatibility for older imports.
ApitTeamInfo = ApiTeamInfo


class ApiGoals(BaseModel):
    """Raw score payload."""

    home: Optional[int] = None
    away: Optional[int] = None


class ApiEventTime(BaseModel):
    """Timestamp information for match events."""

    elapsed: int
    extra: Optional[int] = None


class ApiEvent(BaseModel):
    """Raw event format returned by football provider."""

    time: ApiEventTime
    team: dict
    player: dict
    assist: Optional[dict] = None
    type: str
    detail: str
    comments: Optional[str] = None


class ApiStatEntry(BaseModel):
    """Single statistic entry from API response."""

    type: str
    value: Optional[str | int | float] = None


class ApiTeamStats(BaseModel):
    """Raw team statistics payload."""

    team: dict
    statistics: list[ApiStatEntry]


class TeamStats(BaseModel):
    """
    Normalized team statistics used internally.

    Converts inconsistent provider fields into stable names
    consumed by models, prompts, and frontend components.
    """

    possession: float = 0.0
    shots_total: int = 0
    shots_on_goal: int = 0
    shots_off_goal: int = 0
    passes_total: int = 0
    passes_accurate: int = 0
    pass_accuracy: float = 0.0
    corner_kicks: int = 0
    fouls: int = 0
    offsides: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    goalkeeper_saves: int = 0
    expected_goals: float = 0.0

    @classmethod
    def from_api(cls, raw: ApiTeamStats) -> "TeamStats":
        """
        Transform provider-specific statistics into our internal schema.

        Handles missing values, percentage strings, and inconsistent
        field names from upstream APIs.
        """

        lookup = {entry.type: entry.value for entry in raw.statistics}

        def _f(v, default=0.0):
            try:
                if v is None:
                    return default
                if isinstance(v, str):
                    v = v.replace("%", "").strip()
                return float(v)
            except Exception:
                return default

        return cls(
            possession=_f(lookup.get("Ball Possession")),
            shots_total=int(_f(lookup.get("Total Shots"))),
            shots_on_goal=int(_f(lookup.get("Shots on Goal"))),
            shots_off_goal=int(_f(lookup.get("Shots off Goal"))),
            passes_total=int(_f(lookup.get("Total passes"))),
            passes_accurate=int(_f(lookup.get("Passes accurate"))),
            pass_accuracy=_f(lookup.get("Passes %") or lookup.get("Pass %")),
            corner_kicks=int(_f(lookup.get("Corner Kicks"))),
            fouls=int(_f(lookup.get("Fouls"))),
            offsides=int(_f(lookup.get("Offsides"))),
            yellow_cards=int(_f(lookup.get("Yellow Cards"))),
            red_cards=int(_f(lookup.get("Red Cards"))),
            goalkeeper_saves=int(_f(lookup.get("Goalkeeper Saves"))),
            expected_goals=_f(
                lookup.get("Expected Goals") or lookup.get("expected_goals")
            ),
        )


class MatchEvent(BaseModel):
    """
    Normalized match event used by AI agents.

    Examples:
    - goal
    - penalty_goal
    - red_card
    - substitution
    """

    elapsed: int
    extra: Optional[int] = None
    team_id: int
    team_name: str
    player_name: Optional[str] = None
    type: str
    detail: Optional[str] = None

    @classmethod
    def from_api(cls, raw: ApiEvent) -> "MatchEvent":
        """
        Convert external event format into internal event vocabulary.
        """

        return cls(
            elapsed=raw.time.elapsed,
            extra=raw.time.extra,
            team_id=raw.team["id"],
            team_name=raw.team["name"],
            player_name=raw.player.get("name"),
            type=raw.type.lower().replace(" ", "_"),
            detail=raw.detail,
        )


class MatchState(BaseModel):
    """
    Canonical match object stored in Redis.

    This is the main state object consumed by:
    - live probability models
    - counterfactual engine
    - AI narrative agents
    - frontend match page
    """

    fixture_id: int

    # Tournament metadata
    league_id: int = 1
    season: int = 2026
    round: str = ""

    # Match metadata
    venue: str = ""
    referee: str = ""

    # Current game state
    status_short: str = "NS"
    status_long: str = "Not Started"
    elapsed: Optional[int] = None

    # True when elapsed was estimated instead of directly provided.
    elapsed_estimated: bool = False

    kickoff_time: Optional[datetime] = None

    # Home team state
    home_id: int = 0
    home_name: str = ""
    home_logo: str = ""
    home_score: int = 0
    home_stats: TeamStats = Field(default_factory=TeamStats)

    # Away team state
    away_id: int = 0
    away_name: str = ""
    away_logo: str = ""
    away_score: int = 0
    away_stats: TeamStats = Field(default_factory=TeamStats)

    # Timeline events driving AI analysis.
    events: list[MatchEvent] = Field(default_factory=list)

    """
    Data provenance fields.

    Important because statistics may come from:
    - live API
    - StatsBomb historical proxy
    - unavailable source

    AI responses should disclose proxy data instead of implying
    live measurements.
    """
    stats_source: str = "unknown"

    # Links proxy statistics to the exact historical match used.
    stats_proxy_match_id: Optional[int] = None

    # Timestamp for Redis freshness checks.
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
