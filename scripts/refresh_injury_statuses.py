#!/usr/bin/env python3
"""Refresh data/injury_statuses.json from ESPN (no-op if cache is still fresh)."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl import load_projection_schedule_rows  # noqa: E402
from qpfl.injuries import load_injury_statuses  # noqa: E402
from qpfl.json_scorer import load_rosters  # noqa: E402


def next_game_dates(season: int, today: str) -> dict[str, str]:
    """Map each NFL team to the (Eastern) date of its next game on or after ``today``."""
    try:
        rows = load_projection_schedule_rows([season])
    except Exception as e:  # pragma: no cover - depends on live nflverse data
        print(f'  Could not load NFL schedule ({e}); skipping next-game context')
        return {}
    dates: dict[str, str] = {}
    for row in rows:
        gameday = str(row.get('gameday') or '')[:10]
        if row.get('game_type') != 'REG' or not gameday or gameday < today:
            continue
        for team in (row.get('home_team'), row.get('away_team')):
            if team and (team not in dates or gameday < dates[team]):
                dates[team] = gameday
    return dates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--season', type=int, default=None)
    args = parser.parse_args()

    today = datetime.now(ZoneInfo('America/New_York')).date()
    season = args.season or (today.year if today.month >= 3 else today.year - 1)
    rosters = load_rosters(args.data_dir / 'rosters.json')
    result = load_injury_statuses(
        rosters,
        args.data_dir / 'injury_statuses.json',
        next_kickoffs=next_game_dates(season, today.isoformat()),
    )
    print(
        f'Injury cache updated_at: {result.get("updated_at")} ({len(result.get("players", {}))} players)'
    )


if __name__ == '__main__':
    main()
