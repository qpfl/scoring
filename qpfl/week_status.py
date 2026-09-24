"""NFL week-completion helpers used by scoring automation."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# data/game_overrides.json: {"games": {"2026_03_BUF_CIN": "cancelled"}}. The
# commissioner's call for an NFL game that was postponed out of its week or
# cancelled, so the week can still finish, lock, and count in standings.
GAME_OVERRIDES_FILENAME = 'game_overrides.json'
GAME_OVERRIDE_VALUES = frozenset({'final', 'cancelled'})


def game_id(row: Mapping[str, Any]) -> str | None:
    """nflverse's game_id format ({season}_{week:02d}_{away}_{home}) from a schedule row."""
    season, week = row.get('season'), row.get('week')
    away, home = row.get('away_team'), row.get('home_team')
    if not isinstance(season, int) or not isinstance(week, int) or not away or not home:
        return None
    return f'{season}_{week:02d}_{away}_{home}'


def load_game_overrides(data_dir: str | Path) -> dict[str, str]:
    """Read data/game_overrides.json; a missing file means no overrides."""
    path = Path(data_dir) / GAME_OVERRIDES_FILENAME
    if not path.exists():
        return {}
    content = json.loads(path.read_text(encoding='utf-8'))
    games = content.get('games') if isinstance(content, dict) else None
    if not isinstance(games, dict):
        raise ValueError(f'{path} must be {{"games": {{game_id: "final" | "cancelled"}}}}')
    for key, value in games.items():
        if not isinstance(key, str) or value not in GAME_OVERRIDE_VALUES:
            raise ValueError(f'{path}: {key!r} must be "final" or "cancelled"')
    return dict(games)


def apply_game_overrides(
    schedule_rows: Iterable[Mapping[str, Any]], overrides: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Schedule rows with overridden games marked as having a result."""
    rows = []
    for row in schedule_rows:
        row = dict(row)
        override = overrides.get(game_id(row) or '')
        if override and row.get('result') in (None, ''):
            row['result'] = override
        rows.append(row)
    return rows


def week_games_are_final(
    schedule_rows: Iterable[Mapping[str, Any]], week: int, season: int | None = None
) -> bool:
    """Whether every NFL game in `week` has a final result.

    Standings can only count a week once it is over. Mid-week, a matchup where
    one manager's Thursday starter has played and the other's have not is not a
    1-0 record, it is an unfinished game. Returns False when the week has no
    games in `schedule_rows` at all, since "no evidence" is not "finished".

    Pass `season` whenever the rows span more than one - projection history
    carries the prior season too, and its games are all final, which would
    otherwise vote for a week the current season has not played yet.
    """
    games = [
        row
        for row in schedule_rows
        if row.get('game_type') == 'REG'
        and row.get('week') == week
        and (season is None or row.get('season') == season)
    ]
    return bool(games) and all(game.get('result') not in (None, '') for game in games)


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


def _kickoff(row: Mapping[str, Any]) -> datetime | None:
    gameday = row.get('gameday')
    gametime = row.get('gametime')
    if not gameday or not gametime:
        return None
    try:
        eastern = ZoneInfo('America/New_York')
        local = datetime.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M').replace(tzinfo=eastern)
    except (TypeError, ValueError):
        return None
    return local.astimezone(timezone.utc)


def week_is_locked(
    schedule_rows: Iterable[Mapping[str, Any]],
    week: int,
    season: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Whether `week` is locked because the next week's first game has kicked off.

    A week's scores, projections, and points must stop moving the instant the
    following week begins - a stat correction landing after that point (which
    does happen; nflverse box scores get amended) would otherwise still flow
    into a week that's already been paid out on. The lock is keyed to the next
    week's earliest kickoff rather than "this week is complete", because the
    latter can be true for days before the next week actually starts, and
    tying the lock to it would either under-protect (leave a real gap for
    late corrections) or over-lock (freeze the week early for no reason).

    Fails closed (not locked) when week + 1 has no game with a resolvable
    kickoff time, so a missing/malformed schedule never locks a week early.
    """
    current_time = now if now is not None else datetime.now(timezone.utc)
    next_week = week + 1
    kickoffs = [
        kickoff
        for row in schedule_rows
        if row.get('game_type') == 'REG'
        and row.get('week') == next_week
        and (season is None or row.get('season') == season)
        and (kickoff := _kickoff(row)) is not None
    ]
    return bool(kickoffs) and min(kickoffs) <= current_time


def current_scoring_week(
    schedule_rows: Iterable[Mapping[str, Any]],
    season: int,
    now: datetime | None = None,
    max_week: int = 17,
) -> int:
    """The fantasy week scoring should work on right now.

    The earliest week with an unfinished game (nflreadpy's "current week"),
    but never behind the latest week that has kicked off: a postponed game
    with no result would otherwise hold scoring on its week while the next
    week is being played.
    """
    current_time = now if now is not None else datetime.now(timezone.utc)
    rows = [
        row
        for row in schedule_rows
        if row.get('game_type') == 'REG'
        and row.get('season') == season
        and isinstance(row.get('week'), int)
    ]
    weeks = sorted({row['week'] for row in rows})
    if not weeks:
        return 1
    unfinished = [
        week for week in weeks if not week_games_are_final(rows, week, season) and week <= max_week
    ]
    earliest_unfinished = unfinished[0] if unfinished else max_week
    started = [
        week
        for week in weeks
        if week <= max_week
        and any(
            (kickoff := _kickoff(row)) is not None and kickoff <= current_time
            for row in rows
            if row['week'] == week
        )
    ]
    latest_started = started[-1] if started else 1
    return min(max(earliest_unfinished, latest_started, 1), max_week)
