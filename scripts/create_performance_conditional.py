#!/usr/bin/env python3
"""
Create a performance-based or custom conditional pick.

This handles conditionals that can't be auto-resolved from draft order, such as:
- Player performance conditions ("if Mahomes plays 6+ games")
- Playoff results ("if team makes playoffs")
- Trade conditions ("if player is traded by Week 10")
- Custom conditions

Usage:
    python scripts/create_performance_conditional.py \\
        --year 2027 \\
        --round 1 \\
        --original-team GSA \\
        --condition-type player_performance \\
        --condition "If Patrick Mahomes plays in 6+ games" \\
        --if-true AYP \\
        --if-false GSA \\
        --draft-type offseason

This creates a conditional that:
- Reserves GSA's 2027 R1 pick
- Goes to AYP if condition is met
- Stays with GSA if condition is not met
- Requires manual resolution by commissioner
"""

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


def create_performance_conditional(
    year: str,
    round_num: int,
    original_team: str,
    condition_type: str,
    condition_text: str,
    if_true_owner: str,
    if_false_owner: str,
    draft_type: str = 'offseason',
    dry_run: bool = False
):
    """Create a performance-based conditional pick."""

    picks_path = Path('data/draft_picks.json')
    with open(picks_path) as f:
        data = json.load(f)

    picks = data.get('picks', [])
    conditionals = data.get('conditional_designations', [])

    print(f"Creating performance conditional for {year} R{round_num} {original_team}")
    print()

    # Find the physical pick
    physical_pick = None
    for pick in picks:
        if (pick.get('year') == year and
            pick.get('round') == round_num and
            pick.get('original_team') == original_team and
            pick.get('draft_type') == draft_type):
            physical_pick = pick
            break

    if not physical_pick:
        print(f"❌ Error: Could not find {year} R{round_num} pick for {original_team}")
        return False

    if physical_pick.get('reserved'):
        print(f"❌ Error: Pick is already reserved (part of another conditional)")
        return False

    # Create conditional designation
    group_id = f"cond-{year}-r{round_num}-{original_team}-{condition_type}"

    # Check if this conditional already exists
    existing = [c for c in conditionals if c.get('id') == group_id]
    if existing:
        print(f"❌ Error: Conditional {group_id} already exists")
        return False

    print(f"Condition Type: {condition_type}")
    print(f"Condition: {condition_text}")
    print(f"  If TRUE  → {if_true_owner} gets the pick")
    print(f"  If FALSE → {if_false_owner} gets the pick")
    print()

    # Create the conditional designation
    conditional = {
        'id': group_id,
        'year': year,
        'round': round_num,
        'designation': 'conditional',  # Not "better/worse"
        'condition_type': condition_type,
        'condition_text': condition_text,
        'physical_picks': [original_team],
        'if_true_owner': if_true_owner,
        'if_false_owner': if_false_owner,
        'current_owner': None,  # No one owns it until resolved
        'previous_owners': [],
        'draft_type': draft_type,
        'resolved': False,
        'resolved_to': None,
        'requires_manual_resolution': True,
        'auto_resolvable': False
    }

    print("Conditional designation:")
    print(f"  ID: {group_id}")
    print(f"  Requires manual resolution: Yes")
    print(f"  Auto-resolvable: No")
    print()

    if dry_run:
        print("🔍 DRY RUN - Would make the following changes:")
        print(f"  - Add conditional designation: {group_id}")
        print(f"  - Reserve pick: {year} R{round_num} {original_team}")
        return True

    # Reserve the physical pick
    physical_pick['reserved'] = True
    physical_pick['conditional_group_id'] = group_id
    physical_pick['current_owner'] = None

    # Add conditional
    conditionals.append(conditional)

    # Save
    data['picks'] = picks
    data['conditional_designations'] = conditionals
    data['updated_at'] = datetime.now(timezone.utc).isoformat()

    with open(picks_path, 'w') as f:
        json.dump(data, f, indent=2)

    print("✅ Performance conditional created")
    print(f"   Saved to {picks_path}")
    print()
    print("Next steps:")
    print(f"  1. Track the condition throughout the season")
    print(f"  2. When resolved, run:")
    print(f"     python scripts/resolve_performance_conditional.py \\")
    print(f"       --group-id {group_id} \\")
    print(f"       --condition-met [true/false]")

    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Create a performance-based or custom conditional pick',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--year', required=True, help='Draft year (e.g., 2027)')
    parser.add_argument('--round', type=int, required=True, help='Round number')
    parser.add_argument('--original-team', required=True, help='Team that originally owns the pick')
    parser.add_argument('--condition-type', required=True,
                        choices=['player_performance', 'playoff_result', 'trade_condition', 'custom'],
                        help='Type of condition')
    parser.add_argument('--condition', required=True, help='Description of the condition')
    parser.add_argument('--if-true', required=True, help='Team that gets pick if condition is met')
    parser.add_argument('--if-false', required=True, help='Team that gets pick if condition is not met')
    parser.add_argument('--draft-type', default='offseason',
                        choices=['offseason', 'offseason_taxi', 'waiver', 'waiver_taxi'],
                        help='Type of draft')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview what would be done without making changes')

    args = parser.parse_args()

    create_performance_conditional(
        year=args.year,
        round_num=args.round,
        original_team=args.original_team,
        condition_type=args.condition_type,
        condition_text=args.condition,
        if_true_owner=args.if_true,
        if_false_owner=args.if_false,
        draft_type=args.draft_type,
        dry_run=args.dry_run
    )
