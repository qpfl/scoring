"""NFL week-completion helpers used by scoring automation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


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
