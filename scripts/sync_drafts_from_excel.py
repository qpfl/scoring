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

EXPANSION_2021_PLAYER_NAMES = {
    'L. Fournette': 'Leonard Fournette',
    'J. Burrow': 'Joe Burrow',
    'D. Hopkins': 'DeAndre Hopkins',
    'K. Cousins': 'Kirk Cousins',
    'M. Williams': 'Mike Williams',
    'T. McLaurin': 'Terry McLaurin',
    'J. Jacobs': 'Josh Jacobs',
    'D. Swift': "D'Andre Swift",
    'T. Lawrence': 'Trevor Lawrence',
    'P. Freiermuth': 'Pat Freiermuth',
    'D. Harris': 'Damien Harris',
    'A. Thielen': 'Adam Thielen',
    'J.K. Dobbins': 'J.K. Dobbins',
    'T. Higgins': 'Tee Higgins',
    'K. Hunt': 'Kareem Hunt',
    'C. Sutton': 'Courtland Sutton',
    'J. Cook': 'Jared Cook',
    'A. Rodgers': 'Aaron Rodgers',
    'T. Etienne Jr.': 'Travis Etienne Jr.',
    'T. Tagovailoa': 'Tua Tagovailoa',
    'M. Gaskin': 'Myles Gaskin',
    'J. Hurts': 'Jalen Hurts',
    'D. Schultz': 'Dalton Schultz',
    'L. Thomas': 'Logan Thomas',
    'N. Fant': 'Noah Fant',
    'H. Henry': 'Hunter Henry',
    'M. Brown': 'Marquise Brown',
    'J. Jones': 'Julio Jones',
    'C. Boswell': 'Chris Boswell',
    'J. Sanders': 'Jason Sanders',
    'M. Vrabel': 'Mike Vrabel',
    'C. Claypool': 'Chase Claypool',
    'C. Akers': 'Cam Akers',
    'B. Aiyuk': 'Brandon Aiyuk',
    'E. Moore': 'Elijah Moore',
}

PICK_POSITION_OVERRIDES = {
    ('2025 Offseason Draft', 'TAXI Round 4', '1'): 'D/ST',
    ('2025 Midseason Draft', '3', '7'): 'OL',
}

# Early drafts recorded picks as abbreviations ("T. Hill"), bare cities
# ("Buffalo") or typos, which can't be matched to a player's career profile,
# so the pick showed 0 points. Each entry names the player the drafting team
# actually rostered. A trailing D/ST or OL sets the pick's position.
PICK_PLAYER_CORRECTIONS = {
    ('Founding Draft', '2', '4'): 'Tyreek Hill',
    ('Founding Draft', '2', '6'): 'Buffalo Bills D/ST',
    ('Founding Draft', '2', '7'): 'DeAndre Hopkins',
    ('Founding Draft', '4', '2'): 'JuJu Smith-Schuster',
    ('Founding Draft', '4', '7'): 'Miles Sanders',
    ('Founding Draft', '5', '2'): 'DJ Moore',
    ('Founding Draft', '5', '4'): 'DK Metcalf',
    ('Founding Draft', '5', '8'): 'Adam Thielen',
    ('Founding Draft', '7', '5'): 'James Conner',
    ('Founding Draft', '7', '7'): 'San Francisco 49ers D/ST',
    ('Founding Draft', '8', '6'): 'Jared Cook',
    ('Founding Draft', '8', '8'): 'New England Patriots D/ST',
    ('Founding Draft', '9', '3'): 'John Harbaugh',
    ('Founding Draft', '9', '6'): 'Chicago Bears D/ST',
    ('Founding Draft', '10', '1'): 'Baltimore Ravens D/ST',
    ('Founding Draft', '10', '4'): 'Pittsburgh Steelers D/ST',
    ('Founding Draft', '11', '2'): 'Denver Broncos D/ST',
    ('Founding Draft', '11', '3'): 'Minnesota Vikings D/ST',
    ('Founding Draft', '11', '8'): 'Doug Pederson',
    ('Founding Draft', '12', '2'): 'Keenan Allen',
    ('Founding Draft', '13', '4'): 'New Orleans Saints D/ST',
    ('Founding Draft', '15', '1'): 'Kerryon Johnson',
    ('Founding Draft', '16', '1'): 'Indianapolis Colts D/ST',
    ('Founding Draft', '17', '3'): 'Ronald Jones',
    ('Founding Draft', '17', '4'): 'Los Angeles Chargers D/ST',
    ('Founding Draft', '17', '5'): 'Seattle Seahawks D/ST',
    ('Founding Draft', '17', '6'): 'Dallas Cowboys D/ST',
    ('Founding Draft', '18', '2'): 'Kansas City Chiefs D/ST',
    ('Founding Draft', '18', '7'): 'Tampa Bay Buccaneers D/ST',
    ('Founding Draft', '18', '8'): 'Cincinnati Bengals D/ST',
    ('Founding Draft', '19', '6'): 'Brandon McManus',
    ('Founding Draft', '20', '6'): 'Terry McLaurin',
    ('Founding Draft', 'TAXI Round 3', '1'): 'Philadelphia Eagles D/ST',
    ('Founding Draft', 'TAXI Round 3', '2'): 'Jamaal Williams',
    ('Founding Draft', 'TAXI Round 3', '4'): 'Will Dissly',
    ('Founding Draft', 'TAXI Round 3', '5'): 'Scotty Miller',
    ('Founding Draft', 'TAXI Round 4', '2'): 'Marvin Jones',
    ('2020 Midseason Draft', '1', '1'): 'Antonio Brown',
    ('2020 Midseason Draft', '1', '5'): 'Los Angeles Rams D/ST',
    ('2020 Midseason Draft', '1', '7'): 'Travis Fulgham',
    ('2020 Midseason Draft', '3', '1'): 'Miami Dolphins D/ST',
    ('2020 Midseason Draft', '4', '4'): 'Arizona Cardinals D/ST',
    ('2020 Midseason Draft', '5', '8'): 'Minnesota Vikings D/ST',
    ('2020 Midseason Draft', 'TAXI Round 3', '4'): 'Chase Edmonds',
    ('2020 Midseason Draft', 'TAXI Round 4', '2'): 'New Orleans Saints D/ST',
    ('2020 Midseason Draft', 'TAXI Round 4', '7'): 'Philadelphia Eagles D/ST',
    ('2020 Midseason Draft', 'TAXI Round 4', '9'): 'Robert Griffin',
    ('2021 Offseason Draft', '1', '5'): 'DeVonta Smith',
    ('2021 Offseason Draft', '2', '1'): 'Javonte Williams',
    ('2021 Offseason Draft', '3', '2'): 'Jason Sanders',
    ('2021 Offseason Draft', '3', '3'): 'Mac Jones',
    ('2021 Offseason Draft', '3', '7'): 'Washington Commanders D/ST',
    ('2021 Offseason Draft', '3', '8'): 'Cleveland Browns D/ST',
    ('2021 Offseason Draft', '4', '2'): 'Arizona Cardinals D/ST',
    ('2021 Offseason Draft', '4', '6'): 'San Francisco 49ers D/ST',
    ('2021 Offseason Draft', 'TAXI Round 1', '3'): 'Diontae Johnson',
    ('2021 Offseason Draft', 'TAXI Round 2', '3'): 'Los Angeles Chargers D/ST',
    ('2021 Offseason Draft', 'TAXI Round 4', '3'): 'Kenneth Gainwell',
    ('2021 Offseason Draft', 'TAXI Round 4', '5'): 'Philadelphia Eagles D/ST',
    ('2021 Offseason Draft', 'TAXI Round 4', '6'): 'Jared Cook',
    ('2021 Offseason Draft', 'TAXI Round 4', '7'): 'Taysom Hill',
    ('2021 Midseason Draft', '1', '3'): 'Cordarrelle Patterson',
    ('2021 Midseason Draft', '2', '2'): 'Antonio Brown',
    ('2021 Midseason Draft', '2', '8'): 'New York Jets D/ST',
    ('2021 Midseason Draft', '3', '1'): 'Indianapolis Colts D/ST',
    ('2021 Midseason Draft', '4', '2'): 'Ronald Jones',
    ('2021 Midseason Draft', 'TAXI Round 1', '4'): 'Zack Moss',
    ('2021 Midseason Draft', 'TAXI Round 2', '7'): 'Miami Dolphins D/ST',
    ('2021 Midseason Draft', 'TAXI Round 3', '2'): 'Los Angeles Chargers D/ST',
    ('2021 Midseason Draft', 'TAXI Round 3', '5'): 'Carolina Panthers D/ST',
    ('2021 Midseason Draft', 'TAXI Round 3', '3'): 'Jay Cutler',
    ('2021 Midseason Draft', 'TAXI Round 4', '4'): 'Detroit Lions D/ST',
    ('2021 Midseason Draft', 'TAXI Round 4', '6'): 'Ricky Seals-Jones',
    ('2022 Offseason Draft', '2', '1'): 'Trey McBride',
    ('2022 Offseason Draft', '2', '2'): 'Pittsburgh Steelers D/ST',
    ('2025 Midseason Draft', '2', '1'): 'Eddy Pineiro (SF)',
}

# Team cells whose "(via ...)" trade chain is malformed, so the drafting team
# can't be read from them.
PICK_TEAM_CORRECTIONS = {
    ('2021 Midseason Draft', '1', '6'): 'Redacted (via Ryan/Redacted/Spencer)',
}

# The same for a pick's "Drop" cell: abbreviations and typos that can't be
# matched to the released player's profile, so the release never showed in
# their ownership history. Each entry is checked against the roster the
# dropping team held going into that draft.
DROP_CORRECTIONS = {
    ('2021 Offseason Draft', '2', '3'): 'Jared Cook',
    ('2021 Offseason Draft', '2', '8'): 'Antonio Brown',
    ('2021 Offseason Draft', '4', '5'): 'James Conner',
    ('2021 Midseason Draft', '1', '3'): 'Ronald Jones',
    ('2022 Offseason Draft', '1', '2'): 'Myles Gaskin',
    ('2022 Offseason Draft', '2', '6'): 'Darrel Williams',
    ('2022 Midseason Draft', '4', '3'): 'Javonte Williams',
    ('2026 Offseason Draft', '3', '10'): 'Jake Elliott (PHI)',
    # The expansion sheet has no Drop column: each expansion team cut two of
    # its picks for its free-agent additions, and the cut player's original
    # team held first-add rights.
    ('2021 Expansion Draft', 'Free Agent Additions', '1'): 'Julio Jones (TEN)',
    ('2021 Expansion Draft', 'Free Agent Additions', '2'): 'Travis Etienne Jr. (JAX)',
    ('2021 Expansion Draft', 'Free Agent Additions', '3'): 'Marquise Brown (BAL)',
    ('2021 Expansion Draft', 'Free Agent Additions', '4'): 'Mike Williams (LAC)',
}


def expand_2021_player_name(value):
    label = str(value).strip()
    match = re.match(r'^(.*?)\s*(\([A-Z]{2,4}\))?$', label)
    if not match:
        return label
    name, team = match.groups()
    expanded = EXPANSION_2021_PLAYER_NAMES.get(name.strip(), name.strip())
    return f'{expanded} {team}'.strip() if team else expanded


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
    # Accept both 'Add' and 'Selection' as valid player column headers
    team_header = df.iloc[start_row, team_col] if team_col < len(df.columns) else None
    player_header = df.iloc[start_row, add_col] if add_col < len(df.columns) else None

    if (
        team_col >= len(df.columns)
        or team_header != 'Team'
        or player_header not in ('Add', 'Selection')
    ):
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

        # Check if drop column exists (some drafts don't have it)
        dropped = df.iloc[pick_row, drop_col] if drop_col < len(df.columns) else None

        # Skip if no team specified
        if pd.isna(team):
            pick_row += 1
            continue

        team = str(team).strip()

        # Handle player (could be PASS or empty)
        if pd.isna(player):
            player = 'PASS'
        else:
            player = str(player).strip()
            if not player:
                player = 'PASS'

        # Handle dropped player
        if pd.isna(dropped):
            dropped = None
        else:
            dropped = str(dropped).strip()
            if not dropped or dropped == '-':
                dropped = None

        pick_key = (draft_name, str(round_num), str(pick_num_str))
        team = PICK_TEAM_CORRECTIONS.get(pick_key, team)
        player = PICK_PLAYER_CORRECTIONS.get(pick_key, player)
        dropped = DROP_CORRECTIONS.get(pick_key, dropped)

        position_match = re.search(r'(?:^|\s)(D/ST|DEF|OL)(?:\s|$)', player, flags=re.I)
        position = PICK_POSITION_OVERRIDES.get(pick_key)
        if not position and position_match:
            position = position_match.group(1).upper().replace('DEF', 'D/ST')
        if position:
            # "Minnesota Vikings (MIN) D/ST" -> "Minnesota Vikings (MIN)": a
            # trailing position label keeps the name from matching a profile.
            player = re.sub(r'\s+(?:D/ST|DEF|OL)$', '', player, flags=re.I)

        # Create pick entry
        pick_entry = {'pick': str(pick_num_str), 'team': team, 'player': player}
        if position:
            pick_entry['position'] = position

        if dropped:
            pick_entry['dropped'] = dropped

        picks.append(pick_entry)
        pick_row += 1

    return (round_num, picks) if picks else None


def parse_2021_expansion_draft(df, sheet_name):
    """Parse the one-off snake expansion draft and its follow-up FA additions."""
    sections = {'Expansion Picks': [], 'Free Agent Additions': []}
    current_section = 'Expansion Picks'

    for row_idx in range(len(df)):
        team_value = df.iloc[row_idx, 1] if len(df.columns) > 1 else None
        if str(team_value).strip() == 'Free Agent Additions':
            current_section = 'Free Agent Additions'
            continue

        pick_value = df.iloc[row_idx, 0] if len(df.columns) > 0 else None
        player_value = df.iloc[row_idx, 2] if len(df.columns) > 2 else None
        if pd.isna(team_value) or pd.isna(player_value):
            continue
        if str(team_value).strip() == 'Team' and str(player_value).strip() == 'Player':
            continue  # column header row
        try:
            pick = str(int(float(pick_value)))
        except (TypeError, ValueError):
            # The pick column uses =A{prev}+1 formulas; re-saving the workbook
            # drops the cached values, so fall back to position in the section.
            pick = str(len(sections[current_section]) + 1)

        entry = {
            'pick': pick,
            'team': str(team_value).strip(),
            'player': expand_2021_player_name(player_value),
        }
        if entry['player'] == 'Denver Broncos':
            entry['position'] = 'D/ST'
        if current_section == 'Expansion Picks' and len(df.columns) > 3:
            first_add_rights = df.iloc[row_idx, 3]
            if pd.notna(first_add_rights) and str(first_add_rights).strip():
                entry['first_add_rights'] = str(first_add_rights).strip()
        dropped = DROP_CORRECTIONS.get((sheet_name, current_section, pick))
        if dropped:
            entry['dropped'] = dropped
        sections[current_section].append(entry)

    rounds = [{'round': label, 'picks': picks} for label, picks in sections.items() if picks]
    return [
        {
            'name': sheet_name,
            'year': 2021,
            'type': 'expansion',
            'rounds': rounds,
        }
    ]


def parse_draft_sheet(df, sheet_name):
    """Parse a single draft sheet and return the draft data structure(s).

    Returns a list of draft dictionaries (multiple if there are sub-drafts like OL).
    """
    if sheet_name == '2021 Expansion Draft':
        return parse_2021_expansion_draft(df, sheet_name)

    # Determine draft type and year from sheet name
    year_match = re.search(r'(\d{4})', sheet_name)
    year = int(year_match.group(1)) if year_match else None

    # Determine draft type
    if 'Offseason' in sheet_name or 'Founding' in sheet_name:
        draft_type = 'offseason'
    elif 'Midseason' in sheet_name:
        draft_type = 'midseason'
    elif 'Expansion' in sheet_name:
        draft_type = 'expansion'
    else:
        draft_type = 'offseason'

    # Parse all rounds from the sheet, keeping track of which sub-draft they belong to
    # Key: (sub_draft_name, round_num) -> picks
    rounds_by_draft = {}

    # Track which columns belong to which sub-draft
    # Key: col_idx -> sub_draft_name
    col_to_subdraft = {}

    # First pass: identify sub-draft sections by finding title rows
    for row_idx in range(len(df)):
        checked_cols = set()
        for col_idx in range(0, len(df.columns), 4):
            checked_cols.add(col_idx)
        for col_idx in range(0, len(df.columns), 5):
            checked_cols.add(col_idx)

        for col_idx in sorted(checked_cols):
            if col_idx >= len(df.columns):
                continue

            cell_value = df.iloc[row_idx, col_idx]
            if pd.notna(cell_value):
                cell_str = str(cell_value).strip()
                # Check for sub-draft titles (e.g., "Offensive Line Draft")
                if 'Offensive Line' in cell_str and 'Draft' in cell_str:
                    col_to_subdraft[col_idx] = 'OL'
                elif col_idx not in col_to_subdraft:
                    col_to_subdraft[col_idx] = 'main'

    # Second pass: parse rounds and associate with sub-drafts
    for row_idx in range(len(df)):
        checked_cols = set()
        for col_idx in range(0, len(df.columns), 4):
            checked_cols.add(col_idx)
        for col_idx in range(0, len(df.columns), 5):
            checked_cols.add(col_idx)

        for col_idx in sorted(checked_cols):
            if col_idx >= len(df.columns):
                continue

            result = parse_round_block(df, row_idx, col_idx, sheet_name)
            if result:
                round_num, picks = result
                if picks:
                    # Determine which sub-draft this belongs to
                    subdraft = col_to_subdraft.get(col_idx, 'main')
                    key = (subdraft, round_num)
                    rounds_by_draft[key] = picks

    # Group rounds by sub-draft
    drafts_to_return = []

    for subdraft_name in sorted(
        set(col_to_subdraft.values()), key=lambda value: (value != 'main', value)
    ):
        # Get all rounds for this sub-draft
        subdraft_rounds = {k[1]: v for k, v in rounds_by_draft.items() if k[0] == subdraft_name}

        if not subdraft_rounds:
            continue

        # Convert to list format
        rounds_list = []

        # Sort regular rounds numerically, keep TAXI rounds separate
        regular_rounds = sorted(
            [k for k in subdraft_rounds if not isinstance(k, str) or not k.startswith('TAXI')],
            key=lambda x: int(x) if isinstance(x, str) and x.isdigit() else 999,
        )
        taxi_rounds = sorted(
            [k for k in subdraft_rounds if isinstance(k, str) and k.startswith('TAXI')]
        )

        for round_num in regular_rounds:
            rounds_list.append({'round': str(round_num), 'picks': subdraft_rounds[round_num]})

        for round_num in taxi_rounds:
            rounds_list.append({'round': round_num, 'picks': subdraft_rounds[round_num]})

        # Determine draft name
        if subdraft_name == 'OL':
            draft_name = sheet_name.replace('Offseason Draft', 'OL Expansion Draft')
            draft_name = draft_name.replace('Midseason Draft', 'OL Expansion Draft')
        else:
            draft_name = sheet_name

        drafts_to_return.append(
            {'name': draft_name, 'year': year, 'type': draft_type, 'rounds': rounds_list}
        )

    return drafts_to_return


def sync_drafts_from_excel(excel_path: Path, output_path: Path):
    """Convert Drafts.xlsx to drafts.json."""
    if not excel_path.exists():
        print(f'Error: {excel_path} not found')
        return False

    print(f'Reading drafts from {excel_path}...')

    # Read all sheets
    excel_file = pd.ExcelFile(excel_path)
    sheet_names = excel_file.sheet_names

    print(f'Found {len(sheet_names)} draft sheets')

    drafts = []

    for sheet_name in sheet_names:
        print(f'\nProcessing: {sheet_name}')
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)

        try:
            # parse_draft_sheet now returns a list of drafts
            draft_data_list = parse_draft_sheet(df, sheet_name)

            for draft_data in draft_data_list:
                if draft_data['rounds']:
                    print(f'  ✓ {draft_data["name"]}: Found {len(draft_data["rounds"])} rounds')
                    drafts.append(draft_data)
                else:
                    print(f'  ⚠ {draft_data["name"]}: No rounds found')
        except Exception as e:
            print(f'  ✗ Error: {e}')
            import traceback

            traceback.print_exc()

    # Create output structure
    output_data = {'updated_at': datetime.now(timezone.utc).isoformat(), 'drafts': drafts}

    # Write to file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f'\n✓ Wrote {len(drafts)} drafts to {output_path}')

    # Summary
    print('\nSummary:')
    for draft in drafts:
        rounds_str = ', '.join([r['round'] for r in draft['rounds']])
        print(f'  {draft["name"]}: {rounds_str}')

    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Convert Drafts.xlsx to drafts.json')
    parser.add_argument('--excel', '-e', default='Drafts.xlsx', help='Path to Excel file')
    parser.add_argument('--output', '-o', default='data/drafts.json', help='Output JSON path')
    args = parser.parse_args()

    project_dir = Path(__file__).parent.parent
    excel_path = project_dir / args.excel
    output_path = project_dir / args.output

    success = sync_drafts_from_excel(excel_path, output_path)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
