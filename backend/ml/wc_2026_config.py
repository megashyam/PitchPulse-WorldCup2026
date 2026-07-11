"""
FIFA World Cup 2026 Tournament Configuration

Central configuration module defining the team universe, group assignments,
and knockout bracket structure used across the simulation pipeline.

The configuration provides:
    - Team metadata (name, group, Elo rating, FIFA ranking)
    - Lookup mappings for fast team access
    - Group-stage composition
    - Round-of-32 bracket ordering

All downstream simulation components consume these definitions to ensure a
consistent tournament structure across probability generation, Monte Carlo
simulation, and API responses.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class TeamConfig:
    name: str
    group: str
    elo: float
    fifa_rank: int = 0


WC2026_TEAMS: List[TeamConfig] = [
    # Pot 1 — group seeds
    TeamConfig("Argentina", "A", 1950, 1),
    TeamConfig("France", "B", 1900, 2),
    TeamConfig("England", "C", 1870, 4),
    TeamConfig("USA", "D", 1720, 11),
    TeamConfig("Spain", "E", 1850, 3),
    TeamConfig("Mexico", "F", 1700, 15),
    TeamConfig("Germany", "G", 1820, 6),
    TeamConfig("Netherlands", "H", 1810, 7),
    TeamConfig("Canada", "I", 1670, 14),
    TeamConfig("Croatia", "J", 1780, 9),
    TeamConfig("Italy", "K", 1770, 10),
    TeamConfig("Morocco", "L", 1760, 12),
    # Pot 2
    TeamConfig("Colombia", "A", 1750, 13),
    TeamConfig("Uruguay", "B", 1740, 16),
    TeamConfig("Japan", "C", 1730, 17),
    TeamConfig("Brazil", "D", 1860, 5),
    TeamConfig("Senegal", "E", 1710, 18),
    TeamConfig("Portugal", "F", 1830, 8),
    TeamConfig("South Korea", "G", 1690, 22),
    TeamConfig("Denmark", "H", 1680, 21),
    TeamConfig("Belgium", "I", 1790, 20),
    TeamConfig("Switzerland", "J", 1660, 19),
    TeamConfig("Austria", "K", 1650, 23),
    TeamConfig("Ecuador", "L", 1640, 24),
    # Pot 3
    TeamConfig("Peru", "A", 1630, 25),
    TeamConfig("Iran", "B", 1620, 26),
    TeamConfig("Australia", "C", 1610, 27),
    TeamConfig("Nigeria", "D", 1600, 28),
    TeamConfig("Poland", "E", 1590, 29),
    TeamConfig("Serbia", "F", 1580, 30),
    TeamConfig("Turkey", "G", 1570, 31),
    TeamConfig("Chile", "H", 1560, 32),
    TeamConfig("Ivory Coast", "I", 1550, 33),
    TeamConfig("Egypt", "J", 1540, 34),
    TeamConfig("Saudi Arabia", "K", 1530, 35),
    TeamConfig("Ghana", "L", 1520, 36),
    # Pot 4
    TeamConfig("Venezuela", "A", 1500, 37),
    TeamConfig("Algeria", "B", 1490, 38),
    TeamConfig("South Africa", "C", 1480, 39),
    TeamConfig("Qatar", "D", 1510, 40),
    TeamConfig("Tunisia", "E", 1470, 41),
    TeamConfig("Paraguay", "F", 1460, 42),
    TeamConfig("Panama", "G", 1450, 43),
    TeamConfig("Costa Rica", "H", 1440, 44),
    TeamConfig("Wales", "I", 1430, 45),
    TeamConfig("Scotland", "J", 1420, 46),
    TeamConfig("Honduras", "K", 1410, 47),
    TeamConfig("Cameroon", "L", 1400, 48),
]

TEAM_BY_NAME: Dict[str, TeamConfig] = {t.name: t for t in WC2026_TEAMS}

GROUPS: Dict[str, List[TeamConfig]] = {}
for _t in WC2026_TEAMS:
    GROUPS.setdefault(_t.group, []).append(_t)


R32_BRACKET = [
    # Winners A-H vs best-8 thirds .
    (0, 31),
    (1, 30),
    (2, 29),
    (3, 28),
    (4, 27),
    (5, 26),
    (6, 25),
    (7, 24),
    # Winners I-L vs runners-up A-D.
    (8, 12),
    (9, 13),
    (10, 14),
    (11, 15),
    # Runners-up E-L vs each other.
    (16, 17),
    (18, 19),
    (20, 21),
    (22, 23),
]
