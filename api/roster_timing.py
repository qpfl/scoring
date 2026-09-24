"""When a roster move takes effect, and the frozen roster that protects a started week.

Scoring a week reads that week's roster. Without a frozen copy, a release or
trade made after a player's game would retroactively erase the points he
already scored, because the scorer would only see today's roster. So the
first roster move after a week's first kickoff freezes that week's roster in
``data/roster_snapshots/{season}/week_{N}.json``; the scorer, the lineup API,
and the integrity check read the frozen copy for that week.

A move whose players have not played yet this week lands in the frozen copy
too (it takes effect this week). If any player involved has already played,
the whole move takes effect next week instead: the current roster changes,
the frozen copy does not.

Kept import-free of ``qpfl`` because Vercel does not bundle that package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

LAST_FANTASY_WEEK = 17
NFL_TEAM_ALIASES = {'LAR': 'LA', 'JAC': 'JAX'}


def roster_snapshot_path(season: int, week: int) -> str:
    return f'data/roster_snapshots/{season}/week_{week}.json'


def parse_game_times(live: object) -> dict[int, dict[str, datetime]]:
    """Parse ``live.json``'s ``game_times`` ({week: {nfl_team: iso}}).

    Missing game times (offseason, or a test fixture without them) parse to
    ``{}``. Malformed ones raise ``ValueError`` so the caller can fail closed.
    """
    if not isinstance(live, dict):
        return {}
    raw = live.get('game_times')
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError('game_times is malformed')
    parsed: dict[int, dict[str, datetime]] = {}
    for week_key, teams in raw.items():
        try:
            week = int(week_key)
        except (TypeError, ValueError) as error:
            raise ValueError('game_times is malformed') from error
        if not isinstance(teams, dict):
            raise ValueError('game_times is malformed')
        week_times = {}
        for nfl_team, value in teams.items():
            if not isinstance(nfl_team, str) or not isinstance(value, str):
                raise ValueError('game_times is malformed')
            try:
                kickoff = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError as error:
                raise ValueError('game_times is malformed') from error
            if kickoff.tzinfo is None:
                raise ValueError('game_times is malformed')
            week_times[nfl_team] = kickoff
        if week_times:
            parsed[week] = week_times
    return parsed


def started_unlocked_week(game_times: dict[int, dict[str, datetime]], now: datetime) -> int | None:
    """The fantasy week whose first game has kicked off but whose scores are
    still open - i.e. the following week has not kicked off yet (the lock
    rule in qpfl/week_status.py:week_is_locked). At most one week qualifies.
    """
    for week in sorted(game_times):
        if week > LAST_FANTASY_WEEK:
            return None
        if min(game_times[week].values()) > now:
            return None
        following = game_times.get(week + 1)
        if following and min(following.values()) <= now:
            continue
        return week
    return None


@dataclass(frozen=True)
class RosterTiming:
    started_week: int | None
    week_times: dict[str, datetime]
    known_teams: frozenset[str]
    now: datetime

    def has_played(self, nfl_team: object) -> bool:
        """Whether this NFL team's game in the started week has kicked off.

        An unknown team code counts as played, so a data problem defers a
        move to next week (never erases points) rather than rewriting a
        started week.
        """
        if not isinstance(nfl_team, str) or not nfl_team:
            return True
        code = nfl_team if nfl_team in self.known_teams else NFL_TEAM_ALIASES.get(nfl_team)
        if code is None or code not in self.known_teams:
            return True
        kickoff = self.week_times.get(code)
        return kickoff is not None and kickoff <= self.now


def resolve_roster_timing(
    game_times: dict[int, dict[str, datetime]], now: datetime
) -> RosterTiming:
    started_week = started_unlocked_week(game_times, now)
    known_teams = frozenset(team for week_times in game_times.values() for team in week_times)
    week_times = game_times.get(started_week, {}) if started_week is not None else {}
    return RosterTiming(started_week, week_times, known_teams, now)


def frozen_rosters(snapshot_content: object) -> dict | None:
    """The rosters inside a roster snapshot file, or None if it is malformed."""
    if not isinstance(snapshot_content, dict):
        return None
    rosters = snapshot_content.get('rosters')
    return rosters if isinstance(rosters, dict) else None
