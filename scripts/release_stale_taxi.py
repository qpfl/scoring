#!/usr/bin/env python3
"""
Release taxi (practice squad) players from all rosters.

Per the constitution, taxi players auto-release at the midseason-draft
Thursday and at championship conclusion. There's no calendar trigger for
this (see docs/ROADMAP_2026.md P2.2) - a commissioner runs this manually at
the right time.

Released players are removed from data/rosters.json entirely. The FA pool is
commissioner-curated (not auto-populated on release - see P1.2), so re-add
any of them to data/fa_pool.json yourself with scripts/seed_fa_pool.py if
they should be available for pickup.

Usage:
    python scripts/release_stale_taxi.py                # release all taxi players
    python scripts/release_stale_taxi.py --team GSA      # only one team
    python scripts/release_stale_taxi.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ROSTERS_PATH = REPO_ROOT / 'data' / 'rosters.json'


def release_stale_taxi(rosters_path: Path, team: str | None = None, dry_run: bool = False) -> int:
    rosters = json.loads(rosters_path.read_text())
    released_count = 0

    for abbrev, team_data in rosters.items():
        if team and abbrev != team:
            continue

        # rosters.json stores each team as either a flat list (taxi players
        # marked with a `taxi` flag) or a nested {"roster", "taxi_squad"}
        # dict (see api/transaction.py's get_roster_and_taxi/
        # set_roster_and_taxi, which both formats support). Handle both so
        # taxi players on a nested-format team aren't silently skipped.
        is_nested = isinstance(team_data, dict)
        if is_nested:
            taxi_players = team_data.get('taxi_squad', [])
        elif isinstance(team_data, list):
            taxi_players = [p for p in team_data if p.get('taxi')]
        else:
            continue

        if not taxi_players:
            continue

        for p in taxi_players:
            print(f'  {abbrev}: releasing {p["name"]} ({p.get("position", "?")})')
            released_count += 1

        if is_nested:
            rosters[abbrev] = {'roster': team_data.get('roster', []), 'taxi_squad': []}
        else:
            rosters[abbrev] = [p for p in team_data if not p.get('taxi')]

    if released_count == 0:
        print('No taxi players to release.')
        return 0

    if dry_run:
        print(f'\n(dry run) Would release {released_count} taxi player(s)')
        return released_count

    rosters_path.write_text(json.dumps(rosters, indent=2))
    print(f'\nReleased {released_count} taxi player(s). Saved {rosters_path}')
    return released_count


def main() -> None:
    parser = argparse.ArgumentParser(description='Release taxi players from rosters.json')
    parser.add_argument('--team', help='Only release this team\'s taxi players')
    parser.add_argument('--rosters', default=str(ROSTERS_PATH), help='Path to rosters.json')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without saving')
    args = parser.parse_args()

    release_stale_taxi(Path(args.rosters), team=args.team, dry_run=args.dry_run)


if __name__ == '__main__':
    sys.exit(main() or 0)
