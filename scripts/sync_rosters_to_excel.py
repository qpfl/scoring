#!/usr/bin/env python3
"""
Export data/rosters.json to a fresh Excel workbook (2026+).

rosters.json is the source of truth - it's updated continuously by roster
transactions, trades, and the nightly nfl_team refresh. This script writes a
current snapshot of it in the standard QPFL grid layout (the same layout
scripts/init_rosters_from_excel.py reads), so the two round-trip.

Player names only - no scores, formulas, or formatting. The output file is
replaced on each run. By default it writes Rosters_current.xlsx and leaves the
hand-maintained Rosters.xlsx alone.

Usage:
    python scripts/sync_rosters_to_excel.py
    python scripts/sync_rosters_to_excel.py --output "Rosters.xlsx"
"""

import argparse
import sys
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl.roster_sync import sync_rosters_to_excel


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Export rosters from JSON to Excel')
    parser.add_argument('--rosters', '-r', default='data/rosters.json', help='Path to rosters.json')
    parser.add_argument(
        '--output',
        '-o',
        '--excel',
        '-e',
        dest='output',
        default='Rosters_current.xlsx',
        help='Path to the Excel file to write (default: Rosters_current.xlsx)',
    )
    parser.add_argument('--teams', default='data/teams.json', help='Path to teams.json')
    args = parser.parse_args()

    project_dir = Path(__file__).parent.parent

    rosters_json = project_dir / args.rosters
    excel_path = project_dir / args.output
    teams_path = project_dir / args.teams

    print('Exporting rosters to Excel...')
    print(f'  Source: {rosters_json}')
    print(f'  Target: {excel_path}')

    ok = sync_rosters_to_excel(rosters_json, excel_path, teams_path=teams_path)
    if not ok:
        return 1

    print('Done!')
    return 0


if __name__ == '__main__':
    sys.exit(main())
