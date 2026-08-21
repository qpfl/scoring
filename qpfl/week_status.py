"""NFL week-completion helpers used by scoring automation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def latest_completed_week(schedule_rows: Iterable[Mapping[str, Any]], max_week: int = 17) -> int:
    """Return the latest fantasy week whose NFL games all have final results."""
    games_by_week: dict[int, list[Mapping[str, Any]]] = {}
    for row in schedule_rows:
        if row.get('game_type') != 'REG':
            continue
        week = row.get('week')
        if not isinstance(week, int) or not 1 <= week <= max_week:
            continue
        games_by_week.setdefault(week, []).append(row)

    completed = [
        week
        for week, games in games_by_week.items()
        if games and all(game.get('result') not in (None, '') for game in games)
    ]
    return max(completed, default=0)
