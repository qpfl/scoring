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
from datetime import datetime, timezone
from pathlib import Path

from qpfl import (
    NFLDataFetcher,
    apply_score_adjustments,
    build_availability_lookup,
    calculate_week_projections,
    compact_schedule_rows,
    get_full_schedule,
    load_coach_overrides,
    load_projection_depth_chart_rows,
    load_projection_roster_rows,
    load_projection_schedule_rows,
    load_rosters,
    load_snapshot,
    load_week16_results,
    save_snapshot,
    save_week_scores,
    schedule_path_for_season,
    score_week_from_json,
    snapshot_path,
    update_standings_json,
)
from qpfl.availability import COACH_OVERRIDES_FILENAME
from qpfl.avatars import load_manifest as load_avatar_manifest
from qpfl.injuries import load_injury_statuses
from qpfl.roster_snapshots import roster_snapshot_path, write_roster_snapshot
from qpfl.week_status import week_games_are_final, week_is_locked


def load_teams_info(teams_path: Path) -> dict[str, dict]:
    """Load team info from teams.json."""
    if not teams_path.exists():
        return {}

    with open(teams_path) as f:
        data = json.load(f)

    return {t['abbrev']: t for t in data.get('teams', [])}


def _week_output_already_finalized(output_path: Path) -> bool:
    """Whether `output_path` already has games_final: true.

    Used only by --finalize's narrow lock exception: a week whose output
    already shows games_final: true was already correctly closed out, so
    --finalize must refuse to touch it even though the week is locked -
    only a week that never got that flag set gets the one-time bypass.
    """
    if not output_path.exists():
        return False
    try:
        existing = json.loads(output_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(existing, dict) and existing.get('games_final') is True


def load_team_name_history(team_names_path: Path) -> dict:
    """Load data/team_names.json, or an empty history if it isn't there."""
    if not team_names_path.exists():
        return {}

    with open(team_names_path) as f:
        return json.load(f)


def get_matchups_for_week(schedule_path: Path, standings_path: Path, week: int) -> list[dict]:
    """Get matchups for a specific week."""
    # Load standings for playoff seeding
    standings = []
    if standings_path.exists():
        with open(standings_path) as f:
            data = json.load(f)
            standings = data.get('standings', [])

    # Week 17's finals are drawn from the Week 16 results
    week16 = (
        load_week16_results(standings_path.parent / 'weeks' / 'week_16.json')
        if week == 17
        else None
    )

    # Get full schedule
    schedule = get_full_schedule(schedule_path, standings, week16_results=week16)

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
    parser.add_argument(
        '--force',
        action='store_true',
        help=(
            "Rescore a locked week anyway. Once the following week's first game has "
            'kicked off, a week is locked and this script refuses to change its scores, '
            'projections, or points - even if nflverse later amends its stats. Only use '
            'this for a deliberate, known-good commissioner correction.'
        ),
    )
    parser.add_argument(
        '--finalize',
        action='store_true',
        help=(
            'Bypass the lock only to complete a week that became fully final right as '
            'the following week kicked off and was never actually finalized (its output '
            'file does not yet have games_final: true). Unlike --force, this refuses to '
            'touch a week whose output already shows games_final: true, so it can never '
            're-open a week that was already correctly closed out.'
        ),
    )

    args = parser.parse_args()

    # Validate week is in range up front so an out-of-range value gives a clear
    # error instead of a confusing "lineup file not found" later.
    if not 1 <= args.week <= 17:
        parser.error(f'--week must be between 1 and 17 (got {args.week})')

    # Set up paths
    data_dir = Path(args.data_dir)
    live_rosters_path = data_dir / 'rosters.json'
    # A week scores from its frozen roster once one exists, so roster moves
    # made after its players' games can't rewrite it (qpfl/roster_snapshots.py).
    week_roster_snapshot_path = roster_snapshot_path(data_dir, args.season, args.week)
    rosters_path = (
        week_roster_snapshot_path if week_roster_snapshot_path.exists() else live_rosters_path
    )
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

    # Full-season schedule context, used below both for the opponent-strength
    # adjustment in projections and (here) to check whether this week is
    # locked. NFLDataFetcher.schedules only covers args.week, so this is
    # loaded separately rather than reused from there.
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

    # A week locks the instant the following week's first game kicks off - no
    # more score/projection changes after that, even from an nflverse stat
    # correction. See qpfl.week_status.week_is_locked.
    #
    # --finalize is a narrow exception: a week that became fully final right
    # as the next week's first game kicked off, and so never got a chance to
    # be scored with games_final: true, would otherwise be stuck out of
    # standings forever - nothing after the lock can write to it. It only
    # applies when the existing output truly was never finalized; a week
    # that already has games_final: true is left alone even under
    # --finalize. See docs/ROADMAP_2026.md P3.1 / the in-season reliability
    # plan, phase 2.6.
    locked = week_is_locked(projection_schedule_rows, args.week, args.season)
    if locked and not args.force:
        if args.finalize and not _week_output_already_finalized(output_path):
            print(
                f'🔓 Week {args.week} of {args.season} is locked but was never finalized '
                '(no games_final: true recorded) - completing the one-time finalization '
                'under --finalize.'
            )
        else:
            print(
                f'🔒 Week {args.week} of {args.season} is locked: the following week has '
                'already kicked off. Refusing to change its scores/projections. '
                'Pass --force to override for a deliberate commissioner correction.'
            )
            sys.exit(0)

    if rosters_path != live_rosters_path:
        print(f'Using the frozen Week {args.week} roster: {rosters_path}')

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

    # Who is actually expected to play. Missing context leaves projections
    # untouched rather than zeroing anyone by mistake.
    if source_snapshot is not None:
        projection_roster_rows = source_snapshot.get('projection_rosters') or []
        if not projection_roster_rows:
            print(
                'WARNING: snapshot has no NFL roster context; '
                'projecting every rostered player as available'
            )
    else:
        try:
            projection_roster_rows = load_projection_roster_rows(args.season)
        except Exception as e:
            print(
                f'WARNING: NFL roster statuses unavailable ({e}); '
                'projecting every rostered player as available'
            )
            projection_roster_rows = []

    # Depth charts catch a healthy backup an injury/roster feed can't see -
    # e.g. Kyle Allen behind Josh Allen - who would otherwise fall back to the
    # starting-QB position average. Missing context just skips that check.
    if source_snapshot is not None:
        projection_depth_chart_rows = source_snapshot.get('projection_depth_charts') or []
        if not projection_depth_chart_rows:
            print('WARNING: snapshot has no depth chart context; skipping backup detection')
    else:
        try:
            projection_depth_chart_rows = load_projection_depth_chart_rows(args.season)
        except Exception as e:
            print(f'WARNING: NFL depth charts unavailable ({e}); skipping backup detection')
            projection_depth_chart_rows = []

    availability = build_availability_lookup(
        projection_roster_rows,
        load_injury_statuses(load_rosters(live_rosters_path), data_dir / 'injury_statuses.json'),
        projection_depth_chart_rows,
    )
    coach_overrides = load_coach_overrides(data_dir / COACH_OVERRIDES_FILENAME)

    projections = calculate_week_projections(
        teams=teams,
        results=results,
        matchups=matchups,
        season=args.season,
        week=args.week,
        history_root=Path('web/data/seasons'),
        schedule_rows=projection_schedule_rows,
        availability=availability,
        coach_overrides=coach_overrides,
    )

    # A pre-kickoff run (nflverse hasn't published the season's stats yet) has
    # nothing worth archiving - the week gets snapshotted on a later run once
    # real stats exist.
    if args.save_snapshot and not data_fetcher.week_stats_available:
        print(f'Skipping stat snapshot: no stats published for Week {args.week} yet')
    elif args.save_snapshot:
        snap_path = snapshot_path(args.season, args.week, data_dir)
        snapshot = data_fetcher.to_snapshot()
        snapshot['projection_schedules'] = projection_schedule_rows
        snapshot['projection_rosters'] = projection_roster_rows
        snapshot['projection_depth_charts'] = projection_depth_chart_rows
        if save_snapshot(snapshot, snap_path):
            print(f'Saved stat snapshot: {snap_path}')
        else:
            print(f'Stat snapshot unchanged: {snap_path}')

    # Save scored week. Standings only count a week once every game in it is
    # final, so record that here while the NFL schedule is in hand - the
    # standings pass sees week files, not the schedule.
    games_final = week_games_are_final(
        projection_schedule_rows
        or compact_schedule_rows(data_fetcher.schedules.iter_rows(named=True)),
        args.week,
        args.season,
    )
    # A finished week nothing froze still has its as-played roster in
    # rosters.json (any move since kickoff would have frozen it). Freeze it
    # now, before a later move changes rosters.json, so a --force rescore
    # stays reproducible. Once the week locks, rosters.json may already
    # reflect the next week's moves, so a locked week is never frozen here.
    if (
        games_final
        and not locked
        and rosters_path == live_rosters_path
        and write_roster_snapshot(
            week_roster_snapshot_path,
            args.season,
            args.week,
            load_rosters(live_rosters_path),
            datetime.now(timezone.utc).isoformat(),
        )
    ):
        print(f'Froze the Week {args.week} roster: {week_roster_snapshot_path}')

    save_week_scores(
        output_path,
        args.week,
        teams,
        results,
        matchups,
        projections,
        games_final,
        season=args.season,
        team_name_history=load_team_name_history(data_dir / 'team_names.json'),
        avatar_manifest=load_avatar_manifest(data_dir / 'avatars.json'),
    )

    # Update standings if requested
    if args.update_standings:
        season_weeks_dir = Path('web/data/seasons') / str(args.season) / 'weeks'
        week_files = sorted(season_weeks_dir.glob('week_*.json'))

        update_standings_json(standings_path, week_files, args.season)
        print(f'Standings updated: {standings_path}')


if __name__ == '__main__':
    main()
