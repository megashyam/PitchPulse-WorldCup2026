"""Canonical team-name aliases shared by the simulator, feeds, and StatsBomb.

The project uses three naming universes: simulator names, live-feed variants,
and StatsBomb open-data names. This module provides the single mapping layer
between them and validates the feed aliases against the simulator's canonical
team set at import time.
"""

from __future__ import annotations

from typing import Dict, Set

from ml.wc_2026_config import WC2026_TEAMS

SIM_NAMES: Set[str] = {t.name for t in WC2026_TEAMS}

_TO_SIM: Dict[str, str] = {
    "United States": "USA",
    "United States of America": "USA",
    "US": "USA",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Holland": "Netherlands",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
}

_TO_STATSBOMB: Dict[str, str] = {
    "USA": "United States",
    "United States": "United States",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "Ivory Coast": "Côte d'Ivoire",
    "Cote d'Ivoire": "Côte d'Ivoire",
    "Holland": "Netherlands",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
}

_bad = {v for v in _TO_SIM.values() if v not in SIM_NAMES}
assert not _bad, f"team_names._TO_SIM maps to names outside WC2026_TEAMS: {_bad}"


def to_sim(name: str) -> str:
    """Resolve a feed or display name to the simulator's canonical name."""
    if name in SIM_NAMES:
        return name
    return _TO_SIM.get(name, name)


def to_statsbomb(name: str) -> str:
    """Resolve a simulator or feed name to the StatsBomb open-data name."""
    return _TO_STATSBOMB.get(name, name)


def is_sim_team(name: str) -> bool:
    return to_sim(name) in SIM_NAMES
