#!/usr/bin/env python3
"""
Create a new position-based conditional (better/worse).

Use this when two teams make a trade that includes a conditional pick
based on which team finishes with a better draft position.

Usage:
    python scripts/create_position_conditional.py \\
        --year 2027 \\
        --round 1 \\
        --team1 J/J \\
        --team2 CWR \\
        --better-owner S/T \\
        --worse-owner J/J \\
        --draft-type offseason

This creates:
- "Better of J/J and CWR's 2027 R1" designation owned by S/T
- "Worse of J/J and CWR's 2027 R1" designation owned by J/J
- Reserves both physical picks until resolution
"""

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


def create_position_conditional(
    year: str,
    round_num: int,
    team1: str,
    team2: str,
    better_owner: str,
    worse_owner: str,
    draft_type: str = 'offseason',
    dry_run: bool = False
):
    """Create a new position-based conditional."""

    picks_path = Path('data/draft_picks.json')
    with open(picks_path) as f:
        data = json.load(f)

    picks = data.get('picks', [])
    conditionals = data.get('conditional_designations', [])

    print(f"Creating position-based conditional for {year} R{round_num}")
    print(f"  Teams: {team1} and {team2}")
    print(f"  Better designation → {better_owner}")
    print(f"  Worse designation → {worse_owner}")
    print()

    # Find both physical picks
    physical_picks = []
    teams = sorted([team1, team2])

    for team in teams:
        pick = None
        for p in picks:
            if (p.get('year') == year and
                p.get('round') == round_num and
                p.get('original_team') == team and
                p.get('draft_type') == draft_type):
                pick = p
                break

        if not pick:
            print(f"❌ Error: Could not find {year} R{round_num} pick for {team}")
            return False

        if pick.get('reserved'):
            print(f"❌ Error: {team}'s pick is already reserved (part of another conditional)")
            return False

        physical_picks.append(pick)

    print(f"Found physical picks:")
    for pick in physical_picks:
        owner = pick.get('current_owner', 'unowned')
        print(f"  {pick['year']} R{pick['round']} {pick['original_team']} (currently: {owner})")
    print()

    # Create group ID
    group_id = f"cond-{year}-r{round_num}-{'-'.join(teams)}"

    # Check if this conditional already exists
    existing = [c for c in conditionals if c.get('id') == group_id and not c.get('resolved')]
    if existing:
        print(f"❌ Error: Conditional {group_id} already exists")
        print(f"   Current better owner: {existing[0].get('current_owner')}")
        return False

    print(f"Creating conditional designations:")
    print(f"  Group ID: {group_id}")
    print()

    # Create "better" designation
    better_des = {
        'id': group_id,
        'year': year,
        'round': round_num,
        'designation': 'better',
        'condition_text': f"Better of {' and '.join(teams)}'s {year} R{round_num}",
        'physical_picks': teams,
        'current_owner': better_owner,
        'previous_owners': [],
        'draft_type': draft_type,
        'resolved': False,
        'resolved_to': None
    }

    print(f"  BETTER designation:")
    print(f"    Owner: {better_owner}")
    print(f"    Text: {better_des['condition_text']}")

    # Create "worse" designation
    worse_des = {
        'id': group_id,
        'year': year,
        'round': round_num,
        'designation': 'worse',
        'condition_text': f"Worse of {' and '.join(teams)}'s {year} R{round_num}",
        'physical_picks': teams,
        'current_owner': worse_owner,
        'previous_owners': [],
        'draft_type': draft_type,
        'resolved': False,
        'resolved_to': None
    }

    print(f"  WORSE designation:")
    print(f"    Owner: {worse_owner}")
    print(f"    Text: {worse_des['condition_text']}")
    print()

    if dry_run:
        print("🔍 DRY RUN - Would make the following changes:")
        print(f"  - Add 2 conditional designations: {group_id}")
        print(f"  - Reserve 2 physical picks: {teams[0]} and {teams[1]}")
        print()
        print("Physical picks would be reserved with:")
        for pick in physical_picks:
            print(f"  {pick['year']} R{pick['round']} {pick['original_team']}")
            print(f"    current_owner: {pick.get('current_owner')} → None")
            print(f"    reserved: False → True")
        return True

    # Reserve physical picks
    for pick in physical_picks:
        pick['reserved'] = True
        pick['conditional_group_id'] = group_id
        pick['current_owner'] = None

    # Add designations
    conditionals.append(better_des)
    conditionals.append(worse_des)

    # Save
    data['picks'] = picks
    data['conditional_designations'] = conditionals
    data['updated_at'] = datetime.now(timezone.utc).isoformat()

    with open(picks_path, 'w') as f:
        json.dump(data, f, indent=2)

    print("✅ Position-based conditional created")
    print(f"   Saved to {picks_path}")
    print()
    print("What happens next:")
    print(f"  1. Both physical picks are now reserved")
    print(f"  2. {better_owner} can trade the 'better' designation")
    print(f"  3. {worse_owner} can trade the 'worse' designation")
    print(f"  4. At end of season, run:")
    print(f"     python scripts/finalize_season_and_draft_order.py --season [year]")
    print(f"  5. The conditional will be automatically resolved")

    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Create a new position-based conditional pick',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--year', required=True, help='Draft year (e.g., 2027)')
    parser.add_argument('--round', type=int, required=True, help='Round number')
    parser.add_argument('--team1', required=True, help='First team involved')
    parser.add_argument('--team2', required=True, help='Second team involved')
    parser.add_argument('--better-owner', required=True,
                        help='Team that gets the better pick (earlier in draft)')
    parser.add_argument('--worse-owner', required=True,
                        help='Team that gets the worse pick (later in draft)')
    parser.add_argument('--draft-type', default='offseason',
                        choices=['offseason', 'offseason_taxi', 'waiver', 'waiver_taxi'],
                        help='Type of draft')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview what would be done without making changes')

    args = parser.parse_args()

    create_position_conditional(
        year=args.year,
        round_num=args.round,
        team1=args.team1,
        team2=args.team2,
        better_owner=args.better_owner,
        worse_owner=args.worse_owner,
        draft_type=args.draft_type,
        dry_run=args.dry_run
    )
