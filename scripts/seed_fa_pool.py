#!/usr/bin/env python3
"""
Seed data/fa_pool.json with a list of free-agent player names.

Looks up each player's current NFL team and position via nflreadpy and
appends them to the pool with `available: true`. De-dupes by name against
players already in the pool.

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
except ImportError:
    raise ImportError('Please install nflreadpy: pip install nflreadpy')

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


def load_player_db() -> pl.DataFrame:
    df = nfl.load_players()
    if df is None or df.height == 0:
        raise RuntimeError('nflreadpy.load_players() returned no data')
    return df


def lookup_player(player_db: pl.DataFrame, name: str) -> dict | None:
    """Find a player's team/position by name. Exact match, then contains."""
    target = clean_name(name).lower()

    matches = player_db.filter(pl.col('display_name').str.to_lowercase() == target)
    if matches.height == 0:
        matches = player_db.filter(
            pl.col('display_name').str.to_lowercase().str.contains(target, literal=True)
        )
    if matches.height == 0:
        return None

    row = matches.row(0, named=True)
    return {
        'name': name,
        'nfl_team': normalize_team(row.get('team')),
        'position': row.get('position'),
    }


def load_names(args: argparse.Namespace) -> list[str]:
    names = list(args.names)
    if args.names_file:
        path = Path(args.names_file)
        names.extend(
            line.strip() for line in path.read_text().splitlines() if line.strip()
        )
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description='Seed data/fa_pool.json with free agents')
    parser.add_argument('names', nargs='*', help='Player names to add')
    parser.add_argument('--names-file', help='Path to a file with one player name per line')
    parser.add_argument(
        '--fa-pool',
        default=str(FA_POOL_PATH),
        help='Path to fa_pool.json (default: data/fa_pool.json)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Show changes without saving')
    args = parser.parse_args()

    names = load_names(args)
    if not names:
        parser.error('Provide player names as arguments or via --names-file')

    fa_pool_path = Path(args.fa_pool)
    pool = json.loads(fa_pool_path.read_text()) if fa_pool_path.exists() else []
    if not isinstance(pool, list):
        pool = pool.get('players', [])
    existing_names = {p['name'] for p in pool}

    print('Loading player database from nflreadpy...')
    player_db = load_player_db()

    added = []
    skipped = []
    for name in names:
        if name in existing_names:
            skipped.append((name, 'already in pool'))
            continue
        info = lookup_player(player_db, name)
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
