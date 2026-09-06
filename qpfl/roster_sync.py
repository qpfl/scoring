"""Roster synchronization between JSON and Excel.

For 2026+, rosters.json is the source of truth. This module provides the
roster mutation helpers plus the one Excel writer in the codebase, which emits
the same grid layout scripts/init_rosters_from_excel.py reads so the two
round-trip.
"""

import json
from pathlib import Path

import openpyxl

from .constants import (
    ALL_TEAMS,
    POSITION_ORDER,
    POSITION_ROWS,
    ROSTER_SLOTS,
    TAXI_SLOTS,
    TEAM_COLUMNS,
    TEAM_TO_OWNER,
)

# Layout geometry for the roster grid. The blocks below are derived rather than
# hard-coded so an oversized roster (legal in the offseason, when position
# limits don't apply) still gets every player written out; with roster counts at
# or under ROSTER_SLOTS the result is identical to POSITION_ROWS/TAXI_ROWS.
FIRST_HEADER_ROW = POSITION_ROWS[POSITION_ORDER[0]][0]  # 6
POSITION_BLOCK_GAP = 1  # blank rows between one position block and the next
TAXI_BLOCK_GAP = 4  # blank rows between the last position block and the taxi block


def _max_per_team(rosters: dict[str, list[dict]], position: str) -> int:
    """Largest active count at `position` on any one team."""
    return max(
        (
            len([p for p in roster if p.get('position') == position and not p.get('taxi')])
            for roster in rosters.values()
        ),
        default=0,
    )


def build_roster_layout(
    rosters: dict[str, list[dict]],
) -> tuple[dict[str, tuple[int, list[int]]], list[tuple[int, int]]]:
    """Compute (position_rows, taxi_rows) sized to the deepest roster.

    Each position block is at least ROSTER_SLOTS[position] rows tall, and grows
    to fit the team carrying the most players there — so an offseason roster
    with five RBs shows all five instead of silently dropping the last one.

    Returns the same shapes as the POSITION_ROWS / TAXI_ROWS constants:
    {position: (header_row, [player_rows])} and [(position_row, player_row)].
    """
    position_rows: dict[str, tuple[int, list[int]]] = {}
    row = FIRST_HEADER_ROW

    for position in POSITION_ORDER:
        slots = max(ROSTER_SLOTS[position], _max_per_team(rosters, position))
        position_rows[position] = (row, list(range(row + 1, row + 1 + slots)))
        row += 1 + slots + POSITION_BLOCK_GAP

    max_taxi = max((len([p for p in r if p.get('taxi')]) for r in rosters.values()), default=0)
    taxi_start = row - POSITION_BLOCK_GAP + TAXI_BLOCK_GAP
    taxi_rows = [
        (taxi_start + 2 * i, taxi_start + 2 * i + 1) for i in range(max(TAXI_SLOTS, max_taxi))
    ]
    return position_rows, taxi_rows


def _row_has_content(ws, row: int, columns) -> bool:
    return any(ws.cell(row=row, column=col).value not in (None, '') for col in columns)


def _is_position_label_row(ws, row: int, columns) -> bool:
    """True if any team's cell on this row is a bare position label.

    Used to find the taxi block, whose rows are (position label, player) pairs.
    Matching on the label rather than on "first non-empty row" keeps decorative
    rows - the commissioner export writes a 'Taxi Squad' banner above the pairs
    - from being mistaken for the start of the block.
    """
    return any(
        str(ws.cell(row=row, column=col).value or '').strip() in POSITION_ORDER for col in columns
    )


def detect_roster_layout(
    ws, team_columns, max_scan_row: int = 200
) -> tuple[dict[str, tuple[int, list[int]]], list[tuple[int, int]]] | None:
    """Recover (position_rows, taxi_rows) from a sheet's position labels.

    Position blocks are no longer a fixed height (see build_roster_layout), so a
    reader can't assume the POSITION_ROWS geometry. Each block runs from its
    header label down to the blank spacer before the next one; the taxi block is
    the run of (position label, player) pairs after the last position block.

    Returns None if the sheet doesn't carry a full set of position labels in
    POSITION_ORDER sequence, so callers can fall back to the constants.
    """
    label_col = next((col for col in team_columns if ws.cell(row=4, column=col).value), None)
    if label_col is None:
        return None

    labels = []
    for row in range(5, max_scan_row + 1):
        value = ws.cell(row=row, column=label_col).value
        if value is not None and str(value).strip() in POSITION_ORDER:
            labels.append((row, str(value).strip()))

    header_rows: dict[str, int] = {}
    cursor = 0
    for position in POSITION_ORDER:
        while cursor < len(labels) and labels[cursor][1] != position:
            cursor += 1
        if cursor >= len(labels):
            return None
        header_rows[position] = labels[cursor][0]
        cursor += 1

    position_rows: dict[str, tuple[int, list[int]]] = {}
    for index, position in enumerate(POSITION_ORDER):
        header_row = header_rows[position]
        start = header_row + 1
        if index + 1 < len(POSITION_ORDER):
            end = header_rows[POSITION_ORDER[index + 1]] - 1 - POSITION_BLOCK_GAP
        else:
            # Nothing below to bound the last block, so walk it to its last
            # populated row (the spacer before the taxi block ends the run).
            end = start - 1
            while end < max_scan_row and _row_has_content(ws, end + 1, team_columns):
                end += 1
            end = max(end, start + ROSTER_SLOTS[position] - 1)
        if end < start:
            return None
        position_rows[position] = (header_row, list(range(start, end + 1)))

    row = position_rows[POSITION_ORDER[-1]][1][-1] + 1
    while row <= max_scan_row and not _is_position_label_row(ws, row, team_columns):
        row += 1

    taxi_rows: list[tuple[int, int]] = []
    while row < max_scan_row and _is_position_label_row(ws, row, team_columns):
        taxi_rows.append((row, row + 1))
        row += 2

    return position_rows, taxi_rows


def load_rosters_json(rosters_path: str | Path) -> dict[str, list[dict]]:
    """Load rosters from JSON file."""
    rosters_path = Path(rosters_path)
    if not rosters_path.exists():
        return {}

    with open(rosters_path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def save_rosters_json(rosters_path: str | Path, rosters: dict[str, list[dict]]) -> None:
    """Save rosters to JSON file."""
    rosters_path = Path(rosters_path)
    rosters_path.parent.mkdir(parents=True, exist_ok=True)

    with open(rosters_path, 'w') as f:
        json.dump(rosters, f, indent=2)


def format_player_for_excel(player: dict) -> str:
    """Format a player dict as Excel cell value 'Name (TEAM)'."""
    name: str = str(player.get('name', ''))
    nfl_team: str = str(player.get('nfl_team', ''))
    if nfl_team:
        return f'{name} ({nfl_team})'
    return name


def load_team_metadata(teams_path: str | Path | None) -> dict[str, dict[str, str]]:
    """Load {abbrev: {'name': ..., 'owner': ...}} from data/teams.json.

    Falls back to TEAM_TO_OWNER (and the abbrev itself as the team name) for
    any team missing from the file, so the export still works if teams.json
    is absent or incomplete.
    """
    metadata: dict[str, dict[str, str]] = {}

    if teams_path:
        teams_path = Path(teams_path)
        if teams_path.exists():
            with open(teams_path) as f:
                data = json.load(f)
            for team in data.get('teams', []):
                abbrev = str(team.get('abbrev', '')).strip()
                if abbrev:
                    metadata[abbrev] = {
                        'name': str(team.get('name') or abbrev),
                        'owner': str(team.get('owner') or TEAM_TO_OWNER.get(abbrev, '')),
                    }

    for abbrev in ALL_TEAMS:
        metadata.setdefault(abbrev, {'name': abbrev, 'owner': TEAM_TO_OWNER.get(abbrev, '')})

    return metadata


def sync_rosters_to_excel(
    rosters_json_path: str | Path,
    excel_path: str | Path,
    sheet_name: str = 'Rosters',
    teams_path: str | Path | None = None,
) -> bool:
    """Write rosters.json out as a fresh Excel workbook in the QPFL grid layout.

    This is the layout scripts/init_rosters_from_excel.py reads, so the output
    round-trips back to identical JSON:

    - Teams occupy the columns in TEAM_COLUMNS, in ALL_TEAMS order
    - Row 2 = team name, row 3 = owner, row 4 = abbreviation
    - Active players sit under a header cell holding the position label
    - Taxi players follow as (position label row, player row) pairs

    Block sizes come from build_roster_layout(), so every player is written even
    when a roster is over the position limit (legal in the offseason). The
    reader detects the block boundaries from the position labels, so the two
    stay in step at any size.

    Only player names are written - no scores, formulas, or formatting. Any
    existing file at excel_path is replaced.

    Args:
        rosters_json_path: Path to rosters.json
        excel_path: Path to the workbook to write (overwritten if it exists)
        sheet_name: Sheet name for the roster grid
        teams_path: Optional path to data/teams.json for team names/owners

    Returns:
        True if the workbook was written
    """
    rosters = load_rosters_json(rosters_json_path)
    if not rosters:
        print('No rosters to sync')
        return False

    excel_path = Path(excel_path)
    teams = load_team_metadata(teams_path)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    position_rows, taxi_rows = build_roster_layout(rosters)
    written = 0

    for col, team_abbrev in zip(TEAM_COLUMNS, ALL_TEAMS, strict=True):
        team = teams[team_abbrev]
        ws.cell(row=2, column=col, value=team['name'])
        ws.cell(row=3, column=col, value=team['owner'])
        ws.cell(row=4, column=col, value=team_abbrev)

        roster = rosters.get(team_abbrev, [])

        # Active roster: position header cell, then one player per slot row.
        for position in POSITION_ORDER:
            header_row, player_rows = position_rows[position]
            ws.cell(row=header_row, column=col, value=position)

            players = [p for p in roster if p.get('position') == position and not p.get('taxi')]
            if len(players) > ROSTER_SLOTS[position]:
                # Not fatal — offseason rosters may exceed the limit — but worth
                # flagging, since it's a violation once the season starts.
                print(
                    f'  NOTE: {team_abbrev} has {len(players)} {position} '
                    f'(regular-season max {ROSTER_SLOTS[position]})'
                )

            for row, player in zip(player_rows, players, strict=False):
                ws.cell(row=row, column=col, value=format_player_for_excel(player))

            written += len(players)

        # Taxi squad: the position label lives above the player, since taxi
        # slots aren't grouped by position like the active rows are.
        taxi = [p for p in roster if p.get('taxi')]
        if len(taxi) > TAXI_SLOTS:
            print(f'  WARNING: {team_abbrev} has {len(taxi)} taxi players (max {TAXI_SLOTS})')

        taxi_position_counts: dict[str, int] = {}
        for player in taxi:
            position = str(player.get('position', ''))
            taxi_position_counts[position] = taxi_position_counts.get(position, 0) + 1
        for position, count in taxi_position_counts.items():
            if count > 1:
                print(f'  WARNING: {team_abbrev} has {count} taxi {position} (max 1 per position)')

        for (pos_row, player_row), player in zip(taxi_rows, taxi, strict=False):
            ws.cell(row=pos_row, column=col, value=player.get('position', ''))
            ws.cell(row=player_row, column=col, value=format_player_for_excel(player))

        written += len(taxi)

    wb.save(str(excel_path))
    wb.close()

    print(f'Wrote {written} players to {excel_path}')
    return True


def add_player_to_roster(
    rosters: dict[str, list[dict]],
    team_abbrev: str,
    player: dict,
    is_taxi: bool = False,
) -> dict[str, list[dict]]:
    """Add a player to a team's roster.

    Args:
        rosters: Full rosters dict
        team_abbrev: Team to add player to
        player: Player dict with name, nfl_team, position
        is_taxi: Whether to add to taxi squad

    Returns:
        Updated rosters dict
    """
    if team_abbrev not in rosters:
        rosters[team_abbrev] = []

    new_player = {
        'name': player['name'],
        'nfl_team': player['nfl_team'],
        'position': player['position'],
    }
    if is_taxi:
        new_player['taxi'] = True

    rosters[team_abbrev].append(new_player)
    return rosters


def remove_player_from_roster(
    rosters: dict[str, list[dict]],
    team_abbrev: str,
    player_name: str,
) -> tuple[dict[str, list[dict]], dict | None]:
    """Remove a player from a team's roster.

    Args:
        rosters: Full rosters dict
        team_abbrev: Team to remove player from
        player_name: Name of player to remove

    Returns:
        Tuple of (updated rosters dict, removed player dict or None)
    """
    if team_abbrev not in rosters:
        return rosters, None

    team_roster = rosters[team_abbrev]
    removed_player = None

    for i, player in enumerate(team_roster):
        if player.get('name') == player_name:
            removed_player = team_roster.pop(i)
            break

    return rosters, removed_player


def trade_players(
    rosters: dict[str, list[dict]],
    team1: str,
    team2: str,
    team1_gives: list[str],
    team2_gives: list[str],
) -> dict[str, list[dict]]:
    """Execute a trade between two teams.

    Args:
        rosters: Full rosters dict
        team1: First team abbreviation
        team2: Second team abbreviation
        team1_gives: List of player names team1 is giving
        team2_gives: List of player names team2 is giving

    Returns:
        Updated rosters dict
    """
    # Remove players from each team and collect them
    players_to_team2 = []
    for player_name in team1_gives:
        rosters, player = remove_player_from_roster(rosters, team1, player_name)
        if player:
            players_to_team2.append(player)

    players_to_team1 = []
    for player_name in team2_gives:
        rosters, player = remove_player_from_roster(rosters, team2, player_name)
        if player:
            players_to_team1.append(player)

    # Add players to new teams
    for player in players_to_team2:
        is_taxi = player.get('taxi', False)
        rosters = add_player_to_roster(rosters, team2, player, is_taxi)

    for player in players_to_team1:
        is_taxi = player.get('taxi', False)
        rosters = add_player_to_roster(rosters, team1, player, is_taxi)

    return rosters


def sync_pick_trade_to_json(
    draft_picks_path: str | Path,
    from_team: str,
    to_team: str,
    season: str,
    round_num: int,
    pick_type: str = 'offseason',
) -> bool:
    """Record a traded pick in the draft_picks.json file.

    Args:
        draft_picks_path: Path to data/draft_picks.json
        from_team: Team giving away the pick
        to_team: Team receiving the pick
        season: Season year as string (e.g., "2026")
        round_num: Round number
        pick_type: Type of pick (offseason, waiver, offseason_taxi, waiver_taxi)

    Returns:
        True if sync was successful
    """
    draft_picks_path = Path(draft_picks_path)

    if not draft_picks_path.exists():
        print(f'Warning: Draft picks file not found: {draft_picks_path}')
        return False

    with open(draft_picks_path) as f:
        data = json.load(f)

    picks = data.get('picks', {})

    # Ensure teams exist in picks
    if from_team not in picks:
        picks[from_team] = {}
    if to_team not in picks:
        picks[to_team] = {}

    # Ensure season exists for both teams
    if season not in picks[from_team]:
        picks[from_team][season] = {}
    if season not in picks[to_team]:
        picks[to_team][season] = {}

    # Ensure pick_type exists for both teams
    if pick_type not in picks[from_team][season]:
        picks[from_team][season][pick_type] = []
    if pick_type not in picks[to_team][season]:
        picks[to_team][season][pick_type] = []

    # Remove the pick from from_team
    from_picks = picks[from_team][season][pick_type]
    pick_index = None
    for i, p in enumerate(from_picks):
        # The pick might be from any original owner
        if p.get('round') == round_num:
            pick_index = i
            break

    if pick_index is not None:
        removed_pick = from_picks.pop(pick_index)
        original_owner = removed_pick.get('from', from_team)
    else:
        # Pick not found in from_team's list - they might be trading their own
        original_owner = from_team

    # Add the pick to to_team
    picks[to_team][season][pick_type].append(
        {'round': round_num, 'from': original_owner, 'own': original_owner == to_team}
    )

    # Save back
    data['picks'] = picks
    with open(draft_picks_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(
        f'Pick trade recorded in JSON: {from_team} -> {to_team}, {season} Round {round_num} ({pick_type})'
    )
    return True
