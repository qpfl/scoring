#!/usr/bin/env python3
"""Record, for every rostered player in a completed season, whether he played.

The live scorer stamps each weekly entry with ``found`` (the player appears in
that week's NFL stats) and ``on_bye``. Seasons exported from the score
workbooks have neither, so the site could only guess games played for PPG:
every bye week and every week a player sat out counted as a game. This adds
both flags to the historical week files (and the legacy ``data_<season>.json``)
from the same nflverse data the bench-score backfill uses.

Scores are never touched. A nonzero recorded score always means the player
played, so an unusual name the stats can't match can't erase a real game.

Usage:
    python scripts/backfill_played_flags.py 2025
    python scripts/backfill_played_flags.py --all
    python scripts/backfill_played_flags.py 2025 --dry-run
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

HISTORICAL_SEASONS = tuple(range(2020, 2026))
SCORABLE_POSITIONS = {'QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL'}
# Roster codes -> nflverse schedule codes.
SCHEDULE_TEAM_CODES = {'LAR': 'LA', 'JAC': 'JAX', 'WSH': 'WAS', 'OAK': 'LV', 'SD': 'LAC'}


def teams_playing(schedule_rows: list[dict], week: int) -> set[str]:
    teams: set[str] = set()
    for row in schedule_rows:
        if row.get('week') == week and row.get('game_type', 'REG') == 'REG':
            teams.update(filter(None, (row.get('home_team'), row.get('away_team'))))
    return teams


def schedule_team(nfl_team: str) -> str:
    code = str(nfl_team or '').strip().upper()
    return SCHEDULE_TEAM_CODES.get(code, code)


def played_flags(player: dict, week_teams: set[str], found_in_stats) -> dict:
    """The ``on_bye`` / ``found`` flags for one roster entry (empty if unknown)."""
    position = 'D/ST' if player.get('position') == 'DEF' else player.get('position')
    if position not in SCORABLE_POSITIONS:
        return {}
    flags: dict = {}
    team = schedule_team(player.get('nfl_team'))
    known_team = team and team != 'FA' and len(team) <= 3
    if known_team and week_teams:
        flags['on_bye'] = team not in week_teams
    score = player.get('score')
    if isinstance(score, (int, float)) and score != 0:
        flags['found'] = True
    elif flags.get('on_bye'):
        flags['found'] = False
    else:
        found = found_in_stats(player)
        if found is not None:
            flags['found'] = found
    return flags


def iter_week_players(week: dict):
    for team in week.get('teams', []):
        yield from team.get('roster', [])
        yield from team.get('taxi_squad', [])
    for matchup in week.get('matchups', []):
        for key in ('team1', 'team2'):
            team = matchup.get(key)
            if isinstance(team, dict):
                yield from team.get('roster', [])
                yield from team.get('taxi_squad', [])


def backfill_season(season: int, *, write: bool) -> Counter:
    from scripts.backfill_bench_scores import SeasonData

    season_data = SeasonData(season)
    schedule_rows = season_data.schedules.to_dicts()
    scorers: dict = {}
    cache: dict = {}
    stats: Counter = Counter()

    def flags_for(player: dict, week: int) -> dict:
        key = (
            week,
            player.get('name'),
            player.get('position'),
            player.get('nfl_team'),
            player.get('score'),
        )
        if key not in cache:

            def found_in_stats(entry):
                scorer = scorers.setdefault(week, season_data.scorer(week))
                position = 'D/ST' if entry.get('position') == 'DEF' else entry.get('position')
                try:
                    result = scorer.score_player(
                        entry['name'], entry.get('nfl_team') or '', position
                    )
                except Exception:  # noqa: BLE001 - one bad row shouldn't abort the season
                    return None
                return bool(result.found_in_stats)

            cache[key] = played_flags(player, teams_playing(schedule_rows, week), found_in_stats)
        return cache[key]

    def apply(week: dict, *, count: bool) -> None:
        if not week.get('has_scores', True):
            return
        for player in iter_week_players(week):
            flags = flags_for(player, week['week'])
            player.update(flags)
            if count:
                stats[f'found={flags.get("found")}'] += 1
                stats[f'on_bye={flags.get("on_bye")}'] += 1

    week_files = sorted(
        (PROJECT_DIR / 'web' / 'data' / 'seasons' / str(season) / 'weeks').glob('week_*.json')
    )
    for path in week_files:
        week = json.loads(path.read_text())
        apply(week, count=True)
        if write:
            path.write_text(json.dumps(week, indent=2))

    legacy_path = PROJECT_DIR / 'web' / f'data_{season}.json'
    if legacy_path.exists():
        legacy = json.loads(legacy_path.read_text())
        for week in legacy.get('weeks', []):
            apply(week, count=False)
        if write:
            legacy_path.write_text(json.dumps(legacy, separators=(',', ':')))
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('season', nargs='?', type=int)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.all and args.season not in HISTORICAL_SEASONS:
        parser.error(f'season must be one of {HISTORICAL_SEASONS} (or pass --all)')
    for season in HISTORICAL_SEASONS if args.all else (args.season,):
        stats = backfill_season(season, write=not args.dry_run)
        print(f'{season}: {dict(stats)}')


if __name__ == '__main__':
    main()
