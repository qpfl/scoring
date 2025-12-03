"""Data models for QPFL autoscorer."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class PlayerScore:
    """Container for a player's score breakdown."""
    name: str
    position: str
    team: str
    total_points: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)
    found_in_stats: bool = False
    data_notes: List[str] = field(default_factory=list)  # Flags for data discrepancies


@dataclass
class FantasyTeam:
    """Container for a fantasy team's roster."""
    name: str
    owner: str
    abbreviation: str
    column_index: int  # 1-based column index in Excel
    players: Dict[str, List[Tuple[str, str, bool]]] = field(default_factory=dict)
    # players[position] = [(player_name, nfl_team, is_started), ...]

