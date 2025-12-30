"""Roster synchronization between JSON and Excel.

For 2026+, rosters are the source of truth in rosters.json, but we also
maintain the Excel file for backwards compatibility and easier manual editing.

This module provides functions to sync roster changes to Excel.
"""

import json
from pathlib import Path
from typing import Optional

import openpyxl

from .constants import ALL_TEAMS, ROSTER_SLOTS, POSITION_ORDER


def load_rosters_json(rosters_path: str | Path) -> dict[str, list[dict]]:
    """Load rosters from JSON file."""
    rosters_path = Path(rosters_path)
    if not rosters_path.exists():
        return {}
    
    with open(rosters_path) as f:
        return json.load(f)


def save_rosters_json(rosters_path: str | Path, rosters: dict[str, list[dict]]) -> None:
    """Save rosters to JSON file."""
    rosters_path = Path(rosters_path)
    rosters_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(rosters_path, 'w') as f:
        json.dump(rosters, f, indent=2)


def format_player_for_excel(player: dict) -> str:
    """Format a player dict as Excel cell value 'Name (TEAM)'."""
    name = player.get('name', '')
    nfl_team = player.get('nfl_team', '')
    if nfl_team:
        return f"{name} ({nfl_team})"
    return name


def sync_rosters_to_excel(
    rosters_json_path: str | Path,
    excel_path: str | Path,
    sheet_name: str = "Rosters",
) -> bool:
    """Sync rosters from JSON to Excel file.
    
    The Excel format has:
    - Row 1: Headers (team abbreviations in columns)
    - Row 2+: Position headers and players
    
    Args:
        rosters_json_path: Path to rosters.json
        excel_path: Path to Excel file (created if doesn't exist)
        sheet_name: Sheet name for rosters
        
    Returns:
        True if sync was successful
    """
    rosters = load_rosters_json(rosters_json_path)
    if not rosters:
        print("No rosters to sync")
        return False
    
    excel_path = Path(excel_path)
    
    # Create or load workbook
    if excel_path.exists():
        wb = openpyxl.load_workbook(str(excel_path))
        if sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            ws = wb.create_sheet(sheet_name)
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
    
    # Clear existing content
    ws.delete_rows(1, ws.max_row)
    
    # Write team headers
    ws.cell(row=1, column=1, value="Position")
    for col_idx, team_abbrev in enumerate(ALL_TEAMS, start=2):
        ws.cell(row=1, column=col_idx, value=team_abbrev)
    
    # Write players by position
    current_row = 2
    
    for position in POSITION_ORDER:
        # Position header
        ws.cell(row=current_row, column=1, value=position)
        current_row += 1
        
        max_players = ROSTER_SLOTS[position]
        
        for slot in range(max_players):
            ws.cell(row=current_row, column=1, value=f"{position} {slot + 1}")
            
            for col_idx, team_abbrev in enumerate(ALL_TEAMS, start=2):
                team_roster = rosters.get(team_abbrev, [])
                # Get non-taxi players for this position
                position_players = [
                    p for p in team_roster 
                    if p.get('position') == position and not p.get('taxi')
                ]
                
                if slot < len(position_players):
                    cell_value = format_player_for_excel(position_players[slot])
                    ws.cell(row=current_row, column=col_idx, value=cell_value)
            
            current_row += 1
        
        current_row += 1  # Empty row between positions
    
    # Write taxi squad
    ws.cell(row=current_row, column=1, value="TAXI SQUAD")
    current_row += 1
    
    for slot in range(4):  # 4 taxi slots
        ws.cell(row=current_row, column=1, value=f"Taxi {slot + 1}")
        
        for col_idx, team_abbrev in enumerate(ALL_TEAMS, start=2):
            team_roster = rosters.get(team_abbrev, [])
            taxi_players = [p for p in team_roster if p.get('taxi')]
            
            if slot < len(taxi_players):
                player = taxi_players[slot]
                pos = player.get('position', '')
                name = format_player_for_excel(player)
                ws.cell(row=current_row, column=col_idx, value=f"[{pos}] {name}")
        
        current_row += 1
    
    # Save workbook
    wb.save(str(excel_path))
    wb.close()
    
    print(f"Rosters synced to {excel_path}")
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
) -> tuple[dict[str, list[dict]], Optional[dict]]:
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


def sync_pick_trade_to_excel(
    traded_picks_path: str | Path,
    holder: str,
    original_owner: str,
    season: str,
    round_num: int,
    pick_type: str = "offseason",
) -> bool:
    """Record a traded pick in the Traded Picks.xlsx file.
    
    Args:
        traded_picks_path: Path to Traded Picks.xlsx
        holder: Team that now holds the pick
        original_owner: Team that originally owned the pick
        season: Season year as string (e.g., "2026")
        round_num: Round number
        pick_type: Type of pick (offseason, waiver, offseason_taxi, waiver_taxi)
        
    Returns:
        True if sync was successful
    """
    traded_picks_path = Path(traded_picks_path)
    
    if not traded_picks_path.exists():
        # Create new workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Traded Picks"
        
        # Set up headers
        ws.cell(row=1, column=1, value="2026")
        ws.cell(row=1, column=2, value="2027")
        ws.cell(row=1, column=3, value="2028")
        ws.cell(row=1, column=4, value="2029")
        
        ws.cell(row=2, column=1, value="Offseason Draft")
        ws.cell(row=2, column=2, value="Offseason Draft")
        ws.cell(row=2, column=3, value="Offseason Draft")
        ws.cell(row=2, column=4, value="Offseason Draft")
    else:
        wb = openpyxl.load_workbook(str(traded_picks_path))
        ws = wb.active
    
    # Find the column for the season
    season_col = None
    for col in range(1, 5):
        if ws.cell(row=1, column=col).value == season:
            season_col = col
            break
    
    if season_col is None:
        print(f"Warning: Could not find season {season} in traded picks file")
        wb.close()
        return False
    
    # Format the pick string
    ordinal = {1: 'st', 2: 'nd', 3: 'rd'}.get(round_num, 'th')
    if pick_type == "offseason":
        pick_str = f"{holder} holds {original_owner} {round_num}{ordinal} rounder"
    elif pick_type == "waiver":
        pick_str = f"{holder} holds {original_owner} {round_num}{ordinal} round waiver"
    elif pick_type == "offseason_taxi":
        pick_str = f"{holder} holds {original_owner} {round_num}{ordinal} round taxi"
    elif pick_type == "waiver_taxi":
        pick_str = f"{holder} holds {original_owner} {round_num}{ordinal} round waiver taxi"
    else:
        pick_str = f"{holder} holds {original_owner} {round_num}{ordinal} rounder"
    
    # Find the first empty row in that column
    row = 5  # Start after headers
    while ws.cell(row=row, column=season_col).value:
        row += 1
    
    ws.cell(row=row, column=season_col, value=pick_str)
    
    wb.save(str(traded_picks_path))
    wb.close()
    
    print(f"Pick trade recorded: {pick_str}")
    return True

