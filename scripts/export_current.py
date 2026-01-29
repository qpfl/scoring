#!/usr/bin/env python3
"""
Lightweight export script for current season updates.

This script is optimized for fast, frequent updates during the season.
It only updates scores and standings for the current season from JSON data.

For full exports (including historical data), use export_for_web.py.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import nflreadpy as nfl


def get_current_nfl_week() -> int:
    """Get current NFL week (not capped - offseason needs week 18+ for trading logic)."""
    try:
        return nfl.get_current_week()
    except Exception:
        return 1


def load_json(path: Path) -> dict | list:
    """Load JSON file, return empty dict/list if not found."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def export_current_season(data_dir: Path, web_dir: Path, season: int = 2026) -> dict:
    """
    Export current season data from JSON sources.

    Args:
        data_dir: Path to data/ directory
        web_dir: Path to web/ directory
        season: Current season year

    Returns:
        Updated data dictionary
    """
    # Load existing data.json to preserve historical data
    data_json_path = web_dir / 'data.json'
    if data_json_path.exists():
        with open(data_json_path) as f:
            data = json.load(f)
    else:
        data = {}

    # Load shared data from JSON (no Word docs)
    shared_dir = web_dir / 'data' / 'shared'

    # Constitution (static, rarely changes)
    constitution_path = shared_dir / 'constitution.json'
    if constitution_path.exists():
        data['constitution'] = load_json(constitution_path)

    # Hall of Fame stats
    hof_path = shared_dir / 'hall_of_fame.json'
    if hof_path.exists():
        data['hall_of_fame'] = load_json(hof_path)

    # Banners
    banners_path = shared_dir / 'banners.json'
    if banners_path.exists():
        data['banners'] = load_json(banners_path)
    else:
        # Fall back to scanning images directory
        banners_dir = web_dir / 'images' / 'banners'
        if banners_dir.exists():
            data['banners'] = sorted([f.name for f in banners_dir.glob('*_banner.png')])

    # Transactions from JSON log
    tx_log_path = data_dir / 'transaction_log.json'
    if tx_log_path.exists():
        tx_data = load_json(tx_log_path)
        all_txns = tx_data.get('transactions', [])
        data['transactions'] = all_txns  # Already sorted newest-first
        data['recent_transactions'] = all_txns[:10]  # First 10 (newest) for homepage

    # Pending trades
    pending_trades_path = data_dir / 'pending_trades.json'
    if pending_trades_path.exists():
        trades_data = load_json(pending_trades_path)
        data['pending_trades'] = trades_data.get('trades', [])

    # Trade blocks
    trade_blocks_path = data_dir / 'trade_blocks.json'
    if trade_blocks_path.exists():
        data['trade_blocks'] = load_json(trade_blocks_path)

    # Teams and rosters
    teams_path = data_dir / 'teams.json'
    if teams_path.exists():
        teams_data = load_json(teams_path)
        data['teams'] = teams_data.get('teams', [])

    rosters_path = data_dir / 'rosters.json'
    if rosters_path.exists():
        data['rosters'] = load_json(rosters_path)

    # Current season weeks from web/data/seasons/{year}/weeks/
    season_dir = web_dir / 'data' / 'seasons' / str(season)
    weeks_dir = season_dir / 'weeks'

    if weeks_dir.exists():
        weeks = []
        for week_file in sorted(weeks_dir.glob('week_*.json')):
            week_data = load_json(week_file)
            if week_data:
                weeks.append(week_data)

        # Update current season weeks in data
        # Find and replace current season or append
        if 'seasons' not in data:
            data['seasons'] = {}
        data['seasons'][str(season)] = {
            'weeks': weeks,
            'standings': load_json(season_dir / 'standings.json')
            if (season_dir / 'standings.json').exists()
            else [],
            'meta': load_json(season_dir / 'meta.json')
            if (season_dir / 'meta.json').exists()
            else {},
        }

    # For backward compatibility, also set top-level weeks/standings to current season
    if str(season) in data.get('seasons', {}):
        season_data = data['seasons'][str(season)]
        data['weeks'] = season_data.get('weeks', [])
        data['standings'] = season_data.get('standings', [])

    # Calculate team_stats from current season weeks
    # If no weeks yet (new season), team_stats should be empty
    weeks = data.get('weeks', [])
    standings = data.get('standings', [])
    if weeks and standings:
        # Import calculate_team_stats from export_for_web.py
        import sys
        script_dir = Path(__file__).parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from export_for_web import calculate_team_stats
        data['team_stats'] = calculate_team_stats(weeks, standings)
    else:
        # No weeks yet - clear team_stats so previous season data doesn't show
        data['team_stats'] = {}

    # Draft picks - prefer data/draft_picks.json (single source of truth)
    draft_picks_path = data_dir / 'draft_picks.json'
    if draft_picks_path.exists():
        picks_data = load_json(draft_picks_path)
        data['draft_picks'] = picks_data.get('picks', {})
    else:
        # Fall back to season-specific file
        season_picks_path = season_dir / 'draft_picks.json'
        if season_picks_path.exists():
            data['draft_picks'] = load_json(season_picks_path)

    # Drafts history
    drafts_path = data_dir / 'drafts.json'
    if drafts_path.exists():
        drafts_data = load_json(drafts_path)
        data['drafts'] = drafts_data.get('drafts', [])

    # Current week - detect offseason
    # For 2026, we're in the offseason until the schedule is available
    # For completed seasons, if week 17 exists but NFL week is 1, we're in the offseason
    nfl_week = get_current_nfl_week()
    weeks = data.get('weeks', [])
    max_week = max((w.get('week', 0) for w in weeks), default=0) if weeks else 0

    # Check if we have a schedule yet (from meta.json)
    season_dir = web_dir / 'data' / 'seasons' / str(season)
    meta_path = season_dir / 'meta.json'
    has_schedule = False
    if meta_path.exists():
        meta_data = load_json(meta_path)
        has_schedule = len(meta_data.get('schedule', [])) > 0

    if not has_schedule:
        # Offseason - no schedule yet
        data['current_week'] = 0
        data['is_offseason'] = True
        # Clear the schedule - it's from the previous season
        data['schedule'] = []

        # Generate placeholder standings from previous season order or teams list
        if not data.get('standings') or len(data.get('standings', [])) == 0:
            # Use previous season standings order if available
            prev_data_path = web_dir / f'data_{season - 1}.json'
            if prev_data_path.exists():
                prev_data = load_json(prev_data_path)
                prev_standings = prev_data.get('standings', [])
                if isinstance(prev_standings, dict):
                    prev_standings = prev_standings.get('standings', [])
                # Create placeholder standings with 0 stats
                # Look up current team names by abbrev
                teams_by_abbrev = {t.get('abbrev'): t for t in data.get('teams', [])}
                data['standings'] = [
                    {
                        'abbrev': t.get('abbrev'),
                        'team_name': teams_by_abbrev.get(t.get('abbrev'), {}).get(
                            'name', t.get('name', t.get('abbrev'))
                        ),
                        'name': teams_by_abbrev.get(t.get('abbrev'), {}).get(
                            'name', t.get('name', t.get('abbrev'))
                        ),
                        'owner': teams_by_abbrev.get(t.get('abbrev'), {}).get(
                            'owner', t.get('owner', '')
                        ),
                        'rank_points': 0,
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'points_for': 0,
                        'points_against': 0,
                    }
                    for t in prev_standings
                ]
            elif data.get('teams'):
                # No previous season, use current teams
                data['standings'] = [
                    {
                        'abbrev': t.get('abbrev'),
                        'team_name': t.get('name'),
                        'name': t.get('name'),
                        'owner': t.get('owner', ''),
                        'rank_points': 0,
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'points_for': 0,
                        'points_against': 0,
                    }
                    for t in data['teams']
                ]

        # For offseason, don't create placeholder weeks - let the frontend handle it
        # The frontend will show a "Coming Soon" message for matchups
    elif max_week >= 17 and nfl_week <= 1:
        # Fantasy season is complete, we're in the offseason
        data['current_week'] = 18
        data['is_offseason'] = True
    else:
        data['current_week'] = nfl_week
        data['is_offseason'] = False

    data['season'] = season
    data['is_historical'] = False  # Current season is never historical
    data['updated_at'] = datetime.now(timezone.utc).isoformat()

    # During offseason, include previous season data for homepage display
    if data.get('is_offseason'):
        prev_season = season - 1
        prev_data_path = web_dir / f'data_{prev_season}.json'
        if prev_data_path.exists():
            prev_data = load_json(prev_data_path)
            # Extract standings - may be wrapped in object with updated_at
            prev_standings = prev_data.get('standings', [])
            if isinstance(prev_standings, dict):
                prev_standings = prev_standings.get('standings', [])
            data['previous_season'] = {
                'season': prev_season,
                'weeks': prev_data.get('weeks', []),
                'standings': prev_standings,
                'teams': prev_data.get('teams', []),
            }

    return data


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Export current season data')
    parser.add_argument('--season', '-s', type=int, default=2026, help='Season year')
    parser.add_argument('--data-dir', '-d', default='data', help='Data directory')
    parser.add_argument('--web-dir', '-w', default='web', help='Web directory')
    parser.add_argument('--output', '-o', default=None, help='Output path (default: web/data.json)')
    args = parser.parse_args()

    project_dir = Path(__file__).parent.parent
    data_dir = project_dir / args.data_dir
    web_dir = project_dir / args.web_dir
    output_path = Path(args.output) if args.output else web_dir / 'data.json'

    print(f'Exporting season {args.season}...')

    data = export_current_season(data_dir, web_dir, args.season)

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f'Exported to {output_path}')
    print(f'  Weeks: {len(data.get("weeks", []))}')
    print(f'  Standings: {len(data.get("standings", []))}')
    print(f'  Current week: {data.get("current_week")}')


if __name__ == '__main__':
    main()
