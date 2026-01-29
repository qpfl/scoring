#!/usr/bin/env python3
"""
QPFL Autoscorer CLI

Automatically scores fantasy football lineups using nflreadpy for real-time NFL stats.

Usage:
    python autoscorer.py --excel "2025 Scores.xlsx" --sheet "Week 13" --season 2025 --week 13
"""

import argparse
import sys

import openpyxl

from qpfl import score_week, update_excel_scores


def check_sheet_exists(excel_path: str, sheet_name: str) -> bool:
    """Check if a sheet exists in the Excel file."""
    try:
        wb = openpyxl.load_workbook(excel_path, read_only=True)
        exists = sheet_name in wb.sheetnames
        wb.close()
        return exists
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description='QPFL Fantasy Football Autoscorer')
    parser.add_argument(
        '--excel',
        '-e',
        default='2025 Scores.xlsx',
        help='Path to the Excel file with rosters',
    )
    parser.add_argument(
        '--sheet',
        '-s',
        default=None,
        help="Sheet name to score (defaults to 'Week N' based on --week)",
    )
    parser.add_argument(
        '--season',
        '-y',
        type=int,
        default=2025,
        help='NFL season year',
    )
    parser.add_argument(
        '--week',
        '-w',
        type=int,
        default=13,
        help='Week number to score',
    )
    parser.add_argument(
        '--update',
        '-u',
        action='store_true',
        help='Update Excel file with scores',
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress detailed output',
    )

    args = parser.parse_args()

    # Derive sheet name from week if not explicitly provided
    if args.sheet is None:
        args.sheet = f'Week {args.week}'

    # Check if the sheet exists before attempting to score
    if not check_sheet_exists(args.excel, args.sheet):
        print(f"⚠️  Sheet '{args.sheet}' not found in {args.excel}")
        print("   Skipping scoring - sheet will be created before next week's games begin.")
        print('   This is expected early in the week before lineups are set.')
        # Exit with success (0) so the workflow continues
        sys.exit(0)

    # Score the week
    teams, results = score_week(
        excel_path=args.excel,
        sheet_name=args.sheet,
        season=args.season,
        week=args.week,
        verbose=not args.quiet,
    )

    # Print summary
    print('\n' + '=' * 60)
    print('FINAL STANDINGS')
    print('=' * 60)

    sorted_results = sorted(results.items(), key=lambda x: x[1][0], reverse=True)
    for rank, (team_name, (total, _)) in enumerate(sorted_results, 1):
        print(f'  {rank}. {team_name}: {total:.1f} pts')

    # Update Excel if requested
    if args.update:
        update_excel_scores(args.excel, args.sheet, teams, results)


if __name__ == '__main__':
    main()
