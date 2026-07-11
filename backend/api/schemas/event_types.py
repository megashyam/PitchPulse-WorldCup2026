"""
Central source of truth for all match event classifications and match status
groups used throughout the application.


"""

GOAL_TYPES = frozenset({"goal", "own_goal", "penalty_goal"})
RED_TYPES = frozenset({"red", "yellow_red"})
SIGNIFICANT_TYPES = GOAL_TYPES | RED_TYPES

TRIGGER_TYPES = SIGNIFICANT_TYPES | frozenset({"yellow", "substitution"})

LIVE_STATUSES = frozenset({"1H", "HT", "2H", "ET", "P"})
COMPLETED_STATUSES = frozenset({"FT", "AET", "PEN"})
PROCESSABLE_STATUSES = LIVE_STATUSES | COMPLETED_STATUSES
