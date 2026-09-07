#!/usr/bin/env python3
"""
Seed data/fa_pool.json with a list of free-agent player names.

Looks up each player's current NFL team and position via nflreadpy and
appends them to the pool with `available: true`. De-dupes by name against
players already in the pool.

The season roster feed is the primary source because it carries the player's
actual 2026 team and fantasy position; the all-time player database is only a
fallback, and it will happily return a retired namesake or a defensive
position for a two-way player.

Append ":POSITION" to a name to state the position outright. That is required
for D/ST and OL entries, which are NFL teams rather than players and so appear
in neither feed ("New York Giants:D/ST").

Run after each draft with the list of undrafted players (see
NEW_SEASON_CHECKLIST.md). Reuses the same name-cleaning/team-normalization
approach as scripts/update_player_teams.py.

Usage:
    python scripts/seed_fa_pool.py "Player One" "Player Two"
    python scripts/seed_fa_pool.py --names-file undrafted.txt
    python scripts/seed_fa_pool.py --names-file undrafted.txt --dry-run
"""

import argparse
import json
import re
import sys
from pathlib import Path

import polars as pl

try:
    import nflreadpy as nfl
except ImportError as exc:
    raise ImportError('Please install nflreadpy: pip install nflreadpy') from exc

REPO_ROOT = Path(__file__).parent.parent
FA_POOL_PATH = REPO_ROOT / 'data' / 'fa_pool.json'

# nflreadpy uses different abbreviations for a few teams than our system does.
NFLREADPY_TO_OURS = {'LA': 'LAR', 'JAX': 'JAC'}


def clean_name(name: str) -> str:
    """Strip name suffixes (Jr., Sr., II, III) for looser matching."""
    return re.sub(r'\s+(Sr\.?|Jr\.?|II|III|IV|V)$', '', name.strip()).strip()


def normalize_team(nflreadpy_abbrev: str | None) -> str:
    if not nflreadpy_abbrev:
        return 'FA'
    return NFLREADPY_TO_OURS.get(str(nflreadpy_abbrev), str(nflreadpy_abbrev))


def load_player_db(season: int) -> list[tuple[pl.DataFrame, str, str]]:
    """Player lookup tables, most authoritative first.

    Each entry is (frame, name column, team column). The season roster feed
    knows a player's current team and the position they actually play this
    year; load_players() spans every player in league history, so it is only
    consulted when the roster feed comes up empty.
    """
    tables: list[tuple[pl.DataFrame, str, str]] = []

    try:
        rosters = nfl.load_rosters(seasons=[season])
        if rosters is not None and rosters.height > 0:
            tables.append((rosters, 'full_name', 'team'))
    except Exception as exc:
        print(f'  load_rosters({season}) unavailable: {exc}')

    players = nfl.load_players()
    if players is not None and players.height > 0:
        team_col = 'latest_team' if 'latest_team' in players.columns else 'team'
        tables.append((players, 'display_name', team_col))

    if not tables:
        raise RuntimeError('nflreadpy returned no player data')
    return tables


def split_position(entry: str) -> tuple[str, str | None]:
    """ "New York Giants:D/ST" -> ("New York Giants", "D/ST")."""
    name, sep, position = entry.rpartition(':')
    return (name.strip(), position.strip()) if sep else (entry.strip(), None)


def lookup_team_unit(name: str) -> str | None:
    """NFL team abbreviation for a full team name, for D/ST and OL entries."""
    try:
        teams = nfl.load_teams()
    except Exception:
        return None
    match = teams.filter(pl.col('team_name').str.to_lowercase() == name.lower())
    return normalize_team(match.row(0, named=True)['team_abbr']) if match.height else None


def lookup_player(
    player_db: list[tuple[pl.DataFrame, str, str]], name: str, position: str | None = None
) -> dict | None:
    """Find a player's team/position by name. Exact match, then contains."""
    target = clean_name(name).lower()

    # D/ST and OL are NFL teams, not players — they only resolve by team name.
    if position in ('D/ST', 'OL'):
        abbrev = lookup_team_unit(name)
        return {'name': name, 'nfl_team': abbrev, 'position': position} if abbrev else None

    for frame, name_col, team_col in player_db:
        column = pl.col(name_col).str.to_lowercase()
        matches = frame.filter(column == target)
        if matches.height == 0:
            matches = frame.filter(column.str.contains(target, literal=True))
        if position:
            narrowed = matches.filter(pl.col('position') == position)
            matches = narrowed if narrowed.height else matches
        if matches.height == 0:
            continue

        row = matches.row(0, named=True)
        return {
            'name': name,
            'nfl_team': normalize_team(row.get(team_col)),
            'position': position or row.get('position'),
        }
    return None


def load_names(args: argparse.Namespace) -> list[str]:
    names = list(args.names)
    if args.names_file:
        path = Path(args.names_file)
        names.extend(line.strip() for line in path.read_text().splitlines() if line.strip())
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description='Seed data/fa_pool.json with free agents')
    parser.add_argument('names', nargs='*', help='Player names to add ("Name" or "Name:POSITION")')
    parser.add_argument('--names-file', help='Path to a file with one player name per line')
    parser.add_argument(
        '--fa-pool',
        default=str(FA_POOL_PATH),
        help='Path to fa_pool.json (default: data/fa_pool.json)',
    )
    parser.add_argument(
        '--season',
        type=int,
        default=None,
        help='Season roster feed to look names up in (default: current_season)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Show changes without saving')
    args = parser.parse_args()

    season = args.season
    if season is None:
        config = json.loads((REPO_ROOT / 'data' / 'league_config.json').read_text())
        season = int(config['current_season'])

    names = load_names(args)
    if not names:
        parser.error('Provide player names as arguments or via --names-file')

    fa_pool_path = Path(args.fa_pool)
    pool = json.loads(fa_pool_path.read_text()) if fa_pool_path.exists() else []
    if not isinstance(pool, list):
        pool = pool.get('players', [])
    existing_names = {p['name'] for p in pool}

    print('Loading player database from nflreadpy...')
    player_db = load_player_db(season)

    added = []
    skipped = []
    for entry_text in names:
        name, position = split_position(entry_text)
        if name in existing_names:
            skipped.append((name, 'already in pool'))
            continue
        info = lookup_player(player_db, name, position)
        if not info:
            skipped.append((name, 'not found in nflreadpy'))
            continue
        entry = {**info, 'available': True}
        pool.append(entry)
        existing_names.add(name)
        added.append(entry)

    for entry in added:
        print(f'  + {entry["name"]} ({entry["position"]}, {entry["nfl_team"]})')
    for name, reason in skipped:
        print(f'  - {name}: {reason}')

    print(f'\n{len(added)} added, {len(skipped)} skipped')

    if args.dry_run:
        print('(dry run - not saved)')
        return

    fa_pool_path.write_text(json.dumps(pool, indent=2))
    print(f'Saved {fa_pool_path}')


if __name__ == '__main__':
    sys.exit(main() or 0)
