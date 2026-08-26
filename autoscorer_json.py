#!/usr/bin/env python3
"""
QPFL JSON Autoscorer CLI (2026+)

Automatically scores fantasy football lineups using JSON-based data sources.
Lineups come from data/lineups/{year}/week_{N}.json
Rosters come from data/rosters.json

Usage:
    python autoscorer_json.py --season 2026 --week 1
    python autoscorer_json.py --season 2026 --week 1 --output web/data/seasons/2026/weeks/week_1.json
"""

import argparse
import json
import sys
from pathlib import Path

from qpfl import (
    NFLDataFetcher,
    apply_score_adjustments,
    calculate_week_projections,
    compact_schedule_rows,
    get_full_schedule,
    load_projection_schedule_rows,
    load_snapshot,
    save_snapshot,
    save_week_scores,
    schedule_path_for_season,
    score_week_from_json,
    snapshot_path,
    update_standings_json,
)


def load_teams_info(teams_path: Path) -> dict[str, dict]:
    """Load team info from teams.json."""
    if not teams_path.exists():
        return {}

    with open(teams_path) as f:
        data = json.load(f)

    return {t['abbrev']: t for t in data.get('teams', [])}


def get_matchups_for_week(schedule_path: Path, standings_path: Path, week: int) -> list[dict]:
    """Get matchups for a specific week."""
    # Load standings for playoff seeding
    standings = []
    if standings_path.exists():
        with open(standings_path) as f:
            data = json.load(f)
            standings = data.get('standings', [])

    # Get full schedule
    schedule = get_full_schedule(schedule_path, standings)

    # Find the week
    for week_data in schedule:
        if week_data.get('week') == week:
            return week_data.get('matchups', [])

    return []


def main():
    parser = argparse.ArgumentParser(
        description='QPFL JSON-based Fantasy Football Autoscorer (2026+)'
    )
    parser.add_argument(
        '--season',
        '-y',
        type=int,
        required=True,
        help='NFL season year (e.g., 2026)',
    )
    parser.add_argument(
        '--week',
        '-w',
        type=int,
        required=True,
        help='Week number to score',
    )
    parser.add_argument(
        '--data-dir',
        '-d',
        default='data',
        help='Path to data directory',
    )
    parser.add_argument(
        '--output',
        '-o',
        default=None,
        help='Output path for scored week JSON (defaults to web/data/seasons/{year}/weeks/week_{N}.json)',
    )
    parser.add_argument(
        '--update-standings',
        action='store_true',
        help='Update standings after scoring',
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress detailed output',
    )
    parser.add_argument(
        '--save-snapshot',
        action='store_true',
        help=(
            'Archive the exact nflreadpy inputs used to score this week to '
            'data/stat_snapshots/{season}/week_{N}.json.gz, so it can be re-scored '
            'bit-for-bit later without depending on nflreadpy/nflverse still being '
            'available (see docs/DURABILITY_PLAN.md).'
        ),
    )
    parser.add_argument(
        '--from-snapshot',
        action='store_true',
        help=(
            'Score entirely from a previously saved data/stat_snapshots/ file instead '
            'of fetching live from nflreadpy. Fails if no snapshot exists for this '
            'season/week.'
        ),
    )

    args = parser.parse_args()

    # Validate week is in range up front so an out-of-range value gives a clear
    # error instead of a confusing "lineup file not found" later.
    if not 1 <= args.week <= 17:
        parser.error(f'--week must be between 1 and 17 (got {args.week})')

    # Set up paths
    data_dir = Path(args.data_dir)
    rosters_path = data_dir / 'rosters.json'
    lineup_path = data_dir / 'lineups' / str(args.season) / f'week_{args.week}.json'
    teams_path = data_dir / 'teams.json'
    schedule_path = schedule_path_for_season(data_dir, args.season)

    # Output paths
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = (
            Path('web/data/seasons') / str(args.season) / 'weeks' / f'week_{args.week}.json'
        )

    standings_path = Path('web/data/seasons') / str(args.season) / 'standings.json'

    # Validate files exist
    if not rosters_path.exists():
        print(f'❌ Rosters file not found: {rosters_path}')
        sys.exit(1)

    if not lineup_path.exists():
        print(f'⚠️  Lineup file not found: {lineup_path}')
        print('   Lineups need to be submitted before scoring.')
        sys.exit(0)

    # Load team info
    teams_info = load_teams_info(teams_path)

    # Set up the NFL data fetcher: either a fresh live one (optionally archived
    # afterwards via --save-snapshot) or one rebuilt entirely from a prior
    # archive via --from-snapshot, for reproducing a historical week without
    # depending on nflreadpy/nflverse still being reachable or unchanged.
    source_snapshot = None
    if args.from_snapshot:
        snap_path = snapshot_path(args.season, args.week, data_dir)
        if not snap_path.exists():
            print(f'❌ No snapshot found at {snap_path}')
            sys.exit(1)
        print(f'Scoring Week {args.week} of {args.season} from snapshot: {snap_path}')
        source_snapshot = load_snapshot(snap_path)
        data_fetcher = NFLDataFetcher.from_snapshot(source_snapshot, args.season, args.week)
    else:
        data_fetcher = NFLDataFetcher(args.season, args.week)
        print(f'Scoring Week {args.week} of {args.season}...')

    teams, results = score_week_from_json(
        rosters_path=rosters_path,
        lineup_path=lineup_path,
        season=args.season,
        week=args.week,
        teams_info=teams_info,
        verbose=not args.quiet,
        data_fetcher=data_fetcher,
    )

    # Manual commissioner corrections (e.g. HC fired/ejected penalties, stat
    # fixes) - see data/score_adjustments.json and docs/ROADMAP_2026.md P2.1.
    results = apply_score_adjustments(teams, results, args.season, args.week)

    # Print summary
    print('\n' + '=' * 60)
    print('FINAL STANDINGS')
    print('=' * 60)

    sorted_results = sorted(results.items(), key=lambda x: x[1][0], reverse=True)
    for rank, (team_name, (total, _)) in enumerate(sorted_results, 1):
        print(f'  {rank}. {team_name}: {total:.1f} pts')

    # Get matchups for context
    matchups = []
    if schedule_path.exists():
        matchups = get_matchups_for_week(schedule_path, standings_path, args.week)

    # A regular-season week with no matchups means the season schedule was missing or
    # didn't have this week filled in - standings only accumulate PF/PA/W-L
    # from week_data['matchups'], so writing a matchup-less week file would
    # silently give every team's score nowhere to go (no points_for, no
    # win/loss) instead of failing loudly. See docs/ROADMAP_2026.md P1.7.
    if args.week <= 15 and not matchups:
        print(
            f'❌ No matchups found for Week {args.week} — refusing to write a matchup-less '
            f"week file (standings would silently lose this week's results). Check that "
            f'{schedule_path} has Week {args.week} filled in.'
        )
        sys.exit(1)

    if source_snapshot is not None:
        projection_schedule_rows = source_snapshot.get('projection_schedules')
        if not projection_schedule_rows:
            print(
                'WARNING: snapshot has no projection schedule context; '
                'using a neutral opponent adjustment for historical samples'
            )
            projection_schedule_rows = compact_schedule_rows(
                data_fetcher.schedules.iter_rows(named=True)
            )
    else:
        try:
            projection_schedule_rows = load_projection_schedule_rows([args.season - 1, args.season])
        except Exception as e:
            print(
                f'WARNING: projection schedule history unavailable ({e}); '
                'using a neutral opponent adjustment for historical samples'
            )
            projection_schedule_rows = compact_schedule_rows(
                data_fetcher.schedules.iter_rows(named=True)
            )

    projections = calculate_week_projections(
        teams=teams,
        results=results,
        matchups=matchups,
        season=args.season,
        week=args.week,
        history_root=Path('web/data/seasons'),
        schedule_rows=projection_schedule_rows,
    )

    if args.save_snapshot:
        snap_path = snapshot_path(args.season, args.week, data_dir)
        snapshot = data_fetcher.to_snapshot()
        snapshot['projection_schedules'] = projection_schedule_rows
        save_snapshot(snapshot, snap_path)
        print(f'Saved stat snapshot: {snap_path}')

    # Save scored week
    save_week_scores(output_path, args.week, teams, results, matchups, projections)

    # Update standings if requested
    if args.update_standings:
        season_weeks_dir = Path('web/data/seasons') / str(args.season) / 'weeks'
        week_files = sorted(season_weeks_dir.glob('week_*.json'))

        update_standings_json(standings_path, week_files, args.season)
        print(f'Standings updated: {standings_path}')


if __name__ == '__main__':
    main()
