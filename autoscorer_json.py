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
    get_full_schedule,
    save_week_scores,
    score_week_from_json,
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
    parser = argparse.ArgumentParser(description="QPFL JSON-based Fantasy Football Autoscorer (2026+)")
    parser.add_argument(
        "--season", "-y",
        type=int,
        required=True,
        help="NFL season year (e.g., 2026)",
    )
    parser.add_argument(
        "--week", "-w",
        type=int,
        required=True,
        help="Week number to score",
    )
    parser.add_argument(
        "--data-dir", "-d",
        default="data",
        help="Path to data directory",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path for scored week JSON (defaults to web/data/seasons/{year}/weeks/week_{N}.json)",
    )
    parser.add_argument(
        "--update-standings",
        action="store_true",
        help="Update standings after scoring",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress detailed output",
    )

    args = parser.parse_args()

    # Set up paths
    data_dir = Path(args.data_dir)
    rosters_path = data_dir / "rosters.json"
    lineup_path = data_dir / "lineups" / str(args.season) / f"week_{args.week}.json"
    teams_path = data_dir / "teams.json"
    schedule_path = Path("schedule.txt")

    # Output paths
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path("web/data/seasons") / str(args.season) / "weeks" / f"week_{args.week}.json"

    standings_path = Path("web/data/seasons") / str(args.season) / "standings.json"

    # Validate files exist
    if not rosters_path.exists():
        print(f"❌ Rosters file not found: {rosters_path}")
        sys.exit(1)

    if not lineup_path.exists():
        print(f"⚠️  Lineup file not found: {lineup_path}")
        print("   Lineups need to be submitted before scoring.")
        sys.exit(0)

    # Load team info
    teams_info = load_teams_info(teams_path)

    # Score the week
    print(f"Scoring Week {args.week} of {args.season}...")

    teams, results = score_week_from_json(
        rosters_path=rosters_path,
        lineup_path=lineup_path,
        season=args.season,
        week=args.week,
        teams_info=teams_info,
        verbose=not args.quiet,
    )

    # Print summary
    print("\n" + "="*60)
    print("FINAL STANDINGS")
    print("="*60)

    sorted_results = sorted(results.items(), key=lambda x: x[1][0], reverse=True)
    for rank, (team_name, (total, _)) in enumerate(sorted_results, 1):
        print(f"  {rank}. {team_name}: {total:.1f} pts")

    # Get matchups for context
    matchups = []
    if schedule_path.exists():
        matchups = get_matchups_for_week(schedule_path, standings_path, args.week)

    # Save scored week
    save_week_scores(output_path, args.week, teams, results, matchups)

    # Update standings if requested
    if args.update_standings:
        season_weeks_dir = Path("web/data/seasons") / str(args.season) / "weeks"
        week_files = sorted(season_weeks_dir.glob("week_*.json"))

        update_standings_json(standings_path, week_files, args.season)
        print(f"Standings updated: {standings_path}")


if __name__ == "__main__":
    main()

