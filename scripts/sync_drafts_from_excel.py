#!/usr/bin/env python3
"""
Convert Drafts.xlsx to drafts.json.

The Excel file has one sheet per draft, with rounds laid out in a grid format:
- Each round has columns: Pick#, Team, Add, Drop
- Multiple rounds can be in the same row block (e.g., Round 1, 2, 3 side by side)
- TAXI rounds are at the bottom

Usage:
    python scripts/sync_drafts_from_excel.py
    python scripts/sync_drafts_from_excel.py --excel "Drafts.xlsx"
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def parse_round_block(df, start_row, round_label_col, draft_name):
    """
    Parse a round block starting at start_row.
    Returns (round_number, picks_list) or None if not a valid round.
    """
    # Get the round label (e.g., "Round 1", "TAXI Round 1")
    round_label = df.iloc[start_row, round_label_col]
    if pd.isna(round_label) or not isinstance(round_label, str):
        return None

    round_label = str(round_label).strip()
    if not (round_label.startswith('Round ') or round_label.startswith('TAXI')):
        return None

    # Extract round number
    if round_label.startswith('TAXI'):
        # Keep as "TAXI Round X" for display
        round_num = round_label
    else:
        # Extract just the number for regular rounds
        match = re.search(r'Round (\d+)', round_label)
        if match:
            round_num = match.group(1)
        else:
            return None

    # Check for Team, Add, Drop headers - they're on the SAME row as the round label
    team_col = round_label_col + 1
    add_col = round_label_col + 2
    drop_col = round_label_col + 3

    # Verify headers exist on the same row
    if (team_col >= len(df.columns) or
        df.iloc[start_row, team_col] != 'Team' or
        df.iloc[start_row, add_col] != 'Add'):
        return None

    # Parse picks starting from start_row + 1 (next row after header)
    picks = []
    pick_row = start_row + 1

    while pick_row < len(df):
        pick_num = df.iloc[pick_row, round_label_col]

        # Stop if we hit an empty row or another round header
        if pd.isna(pick_num):
            break

        # Check if this is a new round header
        pick_num_str = str(pick_num).strip()
        if pick_num_str.startswith('Round ') or pick_num_str.startswith('TAXI'):
            break

        team = df.iloc[pick_row, team_col]
        player = df.iloc[pick_row, add_col]
        dropped = df.iloc[pick_row, drop_col]

        # Skip if no team specified
        if pd.isna(team):
            pick_row += 1
            continue

        team = str(team).strip()

        # Handle player (could be PASS or empty)
        if pd.isna(player):
            player = "PASS"
        else:
            player = str(player).strip()
            if not player:
                player = "PASS"

        # Handle dropped player
        if pd.isna(dropped):
            dropped = None
        else:
            dropped = str(dropped).strip()
            if not dropped or dropped == '-':
                dropped = None

        # Create pick entry
        pick_entry = {
            "pick": str(pick_num_str),
            "team": team,
            "player": player
        }

        if dropped:
            pick_entry["dropped"] = dropped

        picks.append(pick_entry)
        pick_row += 1

    return (round_num, picks) if picks else None


def parse_draft_sheet(df, sheet_name):
    """Parse a single draft sheet and return the draft data structure."""
    # Determine draft type and year from sheet name
    year_match = re.search(r'(\d{4})', sheet_name)
    year = int(year_match.group(1)) if year_match else None

    # Determine draft type
    if 'Offseason' in sheet_name or 'Founding' in sheet_name:
        draft_type = 'offseason'
    elif 'Midseason' in sheet_name:
        draft_type = 'midseason'
    elif 'Expansion' in sheet_name:
        draft_type = 'offseason'
    else:
        draft_type = 'offseason'

    # Parse all rounds from the sheet
    # Rounds are typically laid out in a grid: 3 across per row block
    rounds_data = {}

    # Scan through the dataframe looking for round headers
    for row_idx in range(len(df)):
        for col_idx in [0, 5, 10]:  # Check columns 0, 5, 10 for round headers
            # Skip if column doesn't exist
            if col_idx >= len(df.columns):
                continue

            result = parse_round_block(df, row_idx, col_idx, sheet_name)
            if result:
                round_num, picks = result
                if picks:  # Only add if there are actual picks
                    rounds_data[round_num] = picks

    # Convert to list format
    rounds_list = []

    # Sort regular rounds numerically, keep TAXI rounds separate
    regular_rounds = sorted([k for k in rounds_data.keys() if not isinstance(k, str) or not k.startswith('TAXI')],
                           key=lambda x: int(x) if isinstance(x, str) and x.isdigit() else 999)
    taxi_rounds = sorted([k for k in rounds_data.keys() if isinstance(k, str) and k.startswith('TAXI')])

    for round_num in regular_rounds:
        rounds_list.append({
            "round": str(round_num),
            "picks": rounds_data[round_num]
        })

    for round_num in taxi_rounds:
        rounds_list.append({
            "round": round_num,
            "picks": rounds_data[round_num]
        })

    return {
        "name": sheet_name,
        "year": year,
        "type": draft_type,
        "rounds": rounds_list
    }


def sync_drafts_from_excel(excel_path: Path, output_path: Path):
    """Convert Drafts.xlsx to drafts.json."""
    if not excel_path.exists():
        print(f"Error: {excel_path} not found")
        return False

    print(f"Reading drafts from {excel_path}...")

    # Read all sheets
    excel_file = pd.ExcelFile(excel_path)
    sheet_names = excel_file.sheet_names

    print(f"Found {len(sheet_names)} draft sheets")

    drafts = []

    for sheet_name in sheet_names:
        print(f"\nProcessing: {sheet_name}")
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)

        try:
            draft_data = parse_draft_sheet(df, sheet_name)

            if draft_data['rounds']:
                print(f"  ✓ Found {len(draft_data['rounds'])} rounds")
                drafts.append(draft_data)
            else:
                print(f"  ⚠ No rounds found")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            import traceback
            traceback.print_exc()

    # Create output structure
    output_data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "drafts": drafts
    }

    # Write to file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n✓ Wrote {len(drafts)} drafts to {output_path}")

    # Summary
    print("\nSummary:")
    for draft in drafts:
        rounds_str = ', '.join([r['round'] for r in draft['rounds']])
        print(f"  {draft['name']}: {rounds_str}")

    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Convert Drafts.xlsx to drafts.json")
    parser.add_argument("--excel", "-e", default="Drafts.xlsx", help="Path to Excel file")
    parser.add_argument("--output", "-o", default="data/drafts.json", help="Output JSON path")
    args = parser.parse_args()

    project_dir = Path(__file__).parent.parent
    excel_path = project_dir / args.excel
    output_path = project_dir / args.output

    success = sync_drafts_from_excel(excel_path, output_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
