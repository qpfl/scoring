#!/usr/bin/env python3
"""Backfill weekly bench (non-starter) scores in historical web/data_<season>.json files.

Why this exists: the historical exports come from `previous_seasons/<year> Scores.xlsx`,
where a score cell is only filled in for bolded starters. `export_week()` is supposed to
backfill bench players via `calculate_bench_scores()`, but in the committed files that
only landed for a fraction of bench rows (none at all for 2020/2021), so most bench
players carry `score: 0.0` for every week. Anything that sums per-week player scores --
the Teams -> Compare view's `getPlayerSeasonPoints()` in particular -- then shows 0.0 for
players who were never in a starting lineup.

This script rescores those rows with the current scorer and writes them back in place.
It never touches starter scores (the Excel values are the season's official record) or
`total_score` / standings, which are starters-only by construction.

Note: `export_for_web.py --reexport-historical <year>` rewrites these files from Excel and
will drop the backfill (look for the `bench_scores_backfilled` key to tell whether a file
still has it) -- re-run this script afterwards.

Caveat: scoring rules in `qpfl/scoring.py` are not season-versioned, so backfilled bench
scores use today's rules. Run with --validate to see how closely today's rules reproduce
the recorded starter scores for a season before trusting its bench numbers.

Usage:
    python scripts/backfill_bench_scores.py --dry-run            # all historical seasons
    python scripts/backfill_bench_scores.py 2023 2024 --write
    python scripts/backfill_bench_scores.py 2024 --validate --dry-run
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import nflreadpy as nfl  # noqa: E402
import polars as pl  # noqa: E402

from qpfl import QPFLScorer  # noqa: E402
from qpfl.data_fetcher import NFLDataFetcher  # noqa: E402

HISTORICAL_SEASONS = (2020, 2021, 2022, 2023, 2024)
SCORABLE_POSITIONS = {'QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL'}
# A taxi entry whose `position` looks like "Player Name (TEAM)" has name/position
# swapped -- an older export read the Excel taxi rows in the wrong order.
TAXI_SWAP_RE = re.compile(r'^(?P<name>.+?)\s*\((?P<team>[A-Z0-9]{2,3})\)$')


class SeasonData:
    """Season-level nflreadpy frames, loaded once and sliced per week.

    Constructing an NFLDataFetcher per week would re-read the whole season's
    play-by-play 17 times; this loads each frame once and hands each week a
    pre-populated fetcher.
    """

    def __init__(self, season: int):
        self.season = season
        print(f'  Loading {season} player stats, team stats, schedules, play-by-play...')
        self.player_stats = nfl.load_player_stats(seasons=season, summary_level='week')
        self.team_stats = nfl.load_team_stats(seasons=season, summary_level='week')
        self.schedules = nfl.load_schedules(seasons=season)
        self.pbp = nfl.load_pbp(seasons=season)
        self.players_db = nfl.load_players()

    def scorer(self, week: int) -> QPFLScorer:
        fetcher = NFLDataFetcher(self.season, week)
        fetcher._player_stats = self.player_stats.filter(pl.col('week') == week)
        fetcher._team_stats = self.team_stats.filter(pl.col('week') == week)
        fetcher._schedules = self.schedules.filter(pl.col('week') == week)
        fetcher._pbp = self.pbp.filter(pl.col('week') == week)
        fetcher._players_db = self.players_db
        return QPFLScorer(self.season, week, data_fetcher=fetcher)


def score_of(scorer: QPFLScorer, player: dict) -> float | None:
    """Score one roster entry, or None if it can't be scored / wasn't found."""
    position = str(player.get('position') or '').strip().upper()
    if position == 'DEF':
        position = 'D/ST'
        player['position'] = position
    if position not in SCORABLE_POSITIONS:
        return None
    try:
        result = scorer.score_player(player['name'], player.get('nfl_team') or '', position)
    except Exception as exc:  # noqa: BLE001 - one bad row shouldn't abort the season
        print(f'      ! {player["name"]} ({position}): {type(exc).__name__}: {exc}')
        return None
    if not result.found_in_stats:
        return None
    return round(result.total_points, 1)


def fix_taxi_entries(week: dict) -> int:
    """Un-swap taxi entries where `position` holds "Player Name (TEAM)"."""
    fixed = 0
    for matchup in week.get('matchups', []):
        for team in (matchup['team1'], matchup['team2']):
            for entry in team.get('taxi_squad', []):
                match = TAXI_SWAP_RE.match(str(entry.get('position', '')))
                entry_position = str(entry.get('name') or '').strip().upper()
                if not match or entry_position not in {*SCORABLE_POSITIONS, 'DEF'}:
                    continue
                entry['position'] = 'D/ST' if entry_position == 'DEF' else entry_position
                entry['name'] = match.group('name')
                entry['nfl_team'] = entry.get('nfl_team') or match.group('team')
                fixed += 1
    return fixed


def backfill_season(
    season: int, *, write: bool, validate: bool, recompute_all: bool
) -> dict[str, int]:
    path = PROJECT_DIR / 'web' / f'data_{season}.json'
    if not path.exists():
        print(f'{season}: {path} not found, skipping')
        return {}

    with open(path) as f:
        data = json.load(f)

    weeks = [w for w in data.get('weeks', []) if w.get('has_scores')]
    if not weeks:
        print(f'{season}: no weeks with scores, skipping')
        return {}

    print(f'{season}: {len(weeks)} weeks with scores')
    season_data = SeasonData(season)

    stats = {
        'filled': 0,
        'still_zero': 0,
        'unscorable': 0,
        'overwritten': 0,
        'taxi_fixed': 0,
        'starters_checked': 0,
        'starters_matched': 0,
    }

    for week in weeks:
        scorer = season_data.scorer(week['week'])
        week_filled = week_delta = 0
        stats['taxi_fixed'] += fix_taxi_entries(week)

        for matchup in week.get('matchups', []):
            for team in (matchup['team1'], matchup['team2']):
                entries = [
                    *((player, bool(player.get('starter'))) for player in team.get('roster', [])),
                    *((player, False) for player in team.get('taxi_squad', [])),
                ]
                for player, is_starter in entries:
                    existing = player.get('score') or 0.0

                    if is_starter:
                        if validate:
                            computed = score_of(scorer, player)
                            if computed is not None:
                                stats['starters_checked'] += 1
                                if abs(computed - existing) < 0.05:
                                    stats['starters_matched'] += 1
                        continue

                    if existing != 0.0 and not recompute_all:
                        continue

                    computed = score_of(scorer, player)
                    if computed is None:
                        stats['unscorable'] += 1
                        continue
                    if computed == existing:
                        if computed == 0.0:
                            stats['still_zero'] += 1
                        continue
                    if existing != 0.0:
                        stats['overwritten'] += 1
                        week_delta += 1
                    player['score'] = computed
                    stats['filled'] += 1
                    week_filled += 1

        note = f' ({week_delta} existing values changed)' if week_delta else ''
        print(f'    week {week["week"]:>2}: {week_filled} bench scores filled{note}')

    print(
        f'  {season} summary: {stats["filled"]} bench scores filled, '
        f'{stats["still_zero"]} legitimately 0, {stats["unscorable"]} not found in stats, '
        f'{stats["taxi_fixed"]} taxi entries un-swapped'
    )
    if validate and stats['starters_checked']:
        pct = 100 * stats['starters_matched'] / stats['starters_checked']
        print(
            f'  {season} starter check: {stats["starters_matched"]}/'
            f'{stats["starters_checked"]} ({pct:.1f}%) recorded starter scores '
            f'reproduced by the current scorer'
        )

    if write:
        # Record provenance: these bench scores were not in the Excel record.
        provenance = {
            'tool': 'scripts/backfill_bench_scores.py',
            'scores_filled': stats['filled'],
            'rules': 'current qpfl/scoring.py (not season-versioned)',
        }
        if validate and stats['starters_checked']:
            provenance['starter_match'] = f'{stats["starters_matched"]}/{stats["starters_checked"]}'
        data['bench_scores_backfilled'] = provenance

        # Match the compact formatting the exporters use.
        with open(path, 'w') as f:
            json.dump(data, f, separators=(',', ':'))
        print(f'  wrote {path}')
    else:
        print(f'  dry run, {path} unchanged')

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'seasons',
        nargs='*',
        type=int,
        default=list(HISTORICAL_SEASONS),
        help=f'seasons to backfill (default: {" ".join(map(str, HISTORICAL_SEASONS))})',
    )
    parser.add_argument('--write', action='store_true', help='write changes to disk')
    parser.add_argument('--dry-run', action='store_true', help='report only (default)')
    parser.add_argument(
        '--validate',
        action='store_true',
        help='also rescore starters and report how many match the Excel record '
        '(does not modify them)',
    )
    parser.add_argument(
        '--recompute-all',
        action='store_true',
        help='also rescore bench players that already have a non-zero score',
    )
    args = parser.parse_args()

    if args.write and args.dry_run:
        parser.error('--write and --dry-run are mutually exclusive')

    for season in args.seasons:
        backfill_season(
            season,
            write=args.write,
            validate=args.validate,
            recompute_all=args.recompute_all,
        )
        print()


if __name__ == '__main__':
    main()
