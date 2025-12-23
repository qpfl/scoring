#!/usr/bin/env python3
"""Export Excel scores to JSON for web display."""

import json
import re
import zipfile
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nflreadpy as nfl
import openpyxl

def get_docx_module():
    """Try to import docx module."""
    try:
        import docx
        return docx
    except ImportError:
        return None

# Owner name to team code mapping
OWNER_TO_CODE = {
    'Griffin': 'GSA',
    'Bill': 'WJK',
    'Ryan': 'RPA',
    'Spencer/Tim': 'S/T',
    'Kaminska': 'CGK',
    'Anagh': 'AST',
    'Connor': 'CWR',
    'Joe/Joe': 'J/J',
    'Stephen': 'SLS',
    'Arnav': 'AYP',
}

# All team codes
ALL_TEAMS = ['GSA', 'WJK', 'RPA', 'S/T', 'CGK', 'AST', 'CWR', 'J/J', 'SLS', 'AYP']

# Team code aliases (for parsing variations)
TEAM_ALIASES = {
    'T/S': 'S/T',
    'SPY': 'AYP',
}

# Global cache for canonical player names from rosters.json
_CANONICAL_NAMES: dict[str, str] = {}  # lowercase normalized -> canonical name


def _normalize_for_matching(name: str) -> str:
    """Normalize a name for fuzzy matching by removing suffixes and lowercasing."""
    # Remove common suffixes
    normalized = re.sub(r'\s+(Sr\.?|Jr\.?|II|III|IV|V)$', '', name.strip(), flags=re.IGNORECASE)
    return normalized.lower()


def _load_canonical_names() -> dict[str, str]:
    """Load canonical player names from rosters.json."""
    global _CANONICAL_NAMES
    if _CANONICAL_NAMES:
        return _CANONICAL_NAMES
    
    script_dir = Path(__file__).parent
    rosters_path = script_dir.parent / "data" / "rosters.json"
    
    if not rosters_path.exists():
        return {}
    
    try:
        with open(rosters_path) as f:
            rosters = json.load(f)
        
        for team_abbrev, players in rosters.items():
            for player in players:
                canonical_name = player.get("name", "")
                if canonical_name:
                    # Map the normalized version to the canonical name
                    normalized = _normalize_for_matching(canonical_name)
                    _CANONICAL_NAMES[normalized] = canonical_name
    except Exception:
        pass
    
    return _CANONICAL_NAMES


def _match_canonical_name(name: str) -> str:
    """Match a player name to its canonical version from rosters.json."""
    canonical_names = _load_canonical_names()
    if not canonical_names:
        return name
    
    normalized = _normalize_for_matching(name)
    
    # Try exact match on normalized name
    if normalized in canonical_names:
        return canonical_names[normalized]
    
    # Try matching by last name only if first name/initial matches
    # This handles cases like "J. Cook" -> "James Cook III"
    name_parts = normalized.split()
    if len(name_parts) >= 2:
        first_part = name_parts[0].rstrip('.')  # Remove trailing dot from initials
        last_name = name_parts[-1]
        
        for canonical_normalized, canonical_name in canonical_names.items():
            canonical_parts = canonical_normalized.split()
            if len(canonical_parts) >= 2:
                canonical_first = canonical_parts[0]
                canonical_last = canonical_parts[-1]
                
                # Last names must match
                if canonical_last != last_name:
                    continue
                
                # First name must match or be an initial of the canonical first name
                if first_part == canonical_first:
                    return canonical_name
                if len(first_part) == 1 and canonical_first.startswith(first_part):
                    return canonical_name
    
    # No match found, return original
    return name

# Schedule data (parsed from 2025 Schedule.docx)
SCHEDULE = [
    # Week 1-15 matchups as (team1, team2) tuples using owner names
    [('Griffin', 'Bill'), ('Ryan', 'Spencer/Tim'), ('Kaminska', 'Anagh'), ('Connor', 'Joe/Joe'), ('Stephen', 'Arnav')],
    [('Griffin', 'Anagh'), ('Ryan', 'Kaminska'), ('Connor', 'Bill'), ('Stephen', 'Joe/Joe'), ('Spencer/Tim', 'Arnav')],
    [('Griffin', 'Joe/Joe'), ('Ryan', 'Arnav'), ('Kaminska', 'Bill'), ('Connor', 'Stephen'), ('Spencer/Tim', 'Anagh')],
    [('Griffin', 'Stephen'), ('Ryan', 'Joe/Joe'), ('Kaminska', 'Spencer/Tim'), ('Connor', 'Anagh'), ('Bill', 'Arnav')],
    [('Griffin', 'Ryan'), ('Connor', 'Kaminska'), ('Bill', 'Joe/Joe'), ('Arnav', 'Anagh'), ('Spencer/Tim', 'Stephen')],  # Rivalry Week
    [('Griffin', 'Arnav'), ('Ryan', 'Anagh'), ('Kaminska', 'Joe/Joe'), ('Connor', 'Spencer/Tim'), ('Stephen', 'Bill')],
    [('Griffin', 'Kaminska'), ('Ryan', 'Stephen'), ('Connor', 'Arnav'), ('Spencer/Tim', 'Bill'), ('Joe/Joe', 'Anagh')],
    [('Griffin', 'Connor'), ('Ryan', 'Bill'), ('Kaminska', 'Arnav'), ('Stephen', 'Anagh'), ('Spencer/Tim', 'Joe/Joe')],
    [('Griffin', 'Spencer/Tim'), ('Ryan', 'Connor'), ('Kaminska', 'Stephen'), ('Joe/Joe', 'Arnav'), ('Anagh', 'Bill')],
    [('Griffin', 'Stephen'), ('Ryan', 'Kaminska'), ('Connor', 'Spencer/Tim'), ('Joe/Joe', 'Bill'), ('Anagh', 'Arnav')],
    [('Griffin', 'Connor'), ('Ryan', 'Arnav'), ('Kaminska', 'Bill'), ('Stephen', 'Joe/Joe'), ('Spencer/Tim', 'Anagh')],
    [('Griffin', 'Arnav'), ('Ryan', 'Anagh'), ('Kaminska', 'Connor'), ('Stephen', 'Bill'), ('Spencer/Tim', 'Joe/Joe')],
    [('Griffin', 'Ryan'), ('Kaminska', 'Joe/Joe'), ('Connor', 'Bill'), ('Stephen', 'Anagh'), ('Spencer/Tim', 'Arnav')],
    [('Griffin', 'Kaminska'), ('Ryan', 'Spencer/Tim'), ('Connor', 'Joe/Joe'), ('Stephen', 'Arnav'), ('Anagh', 'Bill')],
    [('Griffin', 'Bill'), ('Ryan', 'Stephen'), ('Kaminska', 'Spencer/Tim'), ('Connor', 'Arnav'), ('Joe/Joe', 'Anagh')],
]

# Playoff bracket structure for weeks 16-17
# Week 16: Semifinals - matchups based on final regular season standings
# Week 17: Finals - matchups based on week 16 results
PLAYOFF_STRUCTURE = {
    16: {
        'is_playoffs': True,
        'round': 'Semifinals',
        'matchups': [
            # Playoffs (1-4 seeds)
            {'seed1': 1, 'seed2': 4, 'bracket': 'playoffs', 'game': 'semi_1'},
            {'seed1': 2, 'seed2': 3, 'bracket': 'playoffs', 'game': 'semi_2'},
            # Mid Bowl (two-week total points matchup)
            {'seed1': 5, 'seed2': 6, 'bracket': 'mid_bowl', 'game': 'mid_bowl_week1', 'two_week': True},
            # Sewer Series (7-10 seeds)
            {'seed1': 7, 'seed2': 10, 'bracket': 'sewer_series', 'game': 'sewer_1'},
            {'seed1': 8, 'seed2': 9, 'bracket': 'sewer_series', 'game': 'sewer_2'},
        ]
    },
    17: {
        'is_playoffs': True,
        'round': 'Finals',
        'matchups': [
            # Championship: winners of semi_1 and semi_2
            {'from_games': ['semi_1', 'semi_2'], 'take': 'winners', 'bracket': 'championship', 'game': 'championship'},
            # Consolation Cup: losers of semi_1 and semi_2
            {'from_games': ['semi_1', 'semi_2'], 'take': 'losers', 'bracket': 'consolation_cup', 'game': 'consolation_cup'},
            # Mid Bowl Week 2 (continuation of two-week matchup)
            {'seed1': 5, 'seed2': 6, 'bracket': 'mid_bowl', 'game': 'mid_bowl_week2', 'two_week': True},
            # Toilet Bowl: losers of sewer_1 and sewer_2
            {'from_games': ['sewer_1', 'sewer_2'], 'take': 'losers', 'bracket': 'toilet_bowl', 'game': 'toilet_bowl'},
        ]
    }
}


def get_playoff_matchups(standings: list[dict], week_num: int, week_16_results: dict = None) -> list[dict]:
    """Generate playoff matchups based on standings and week 16 results.
    
    Args:
        standings: List of team standings sorted by rank (index 0 = seed 1)
        week_num: Week number (16 or 17)
        week_16_results: Dict of game_id -> {'winner': abbrev, 'loser': abbrev} for week 17
    
    Returns:
        List of matchup dicts with team1, team2, and playoff metadata
    """
    if week_num not in PLAYOFF_STRUCTURE:
        return []
    
    playoff_info = PLAYOFF_STRUCTURE[week_num]
    matchups = []
    
    # Create seed to team mapping
    seed_to_team = {i + 1: team['abbrev'] for i, team in enumerate(standings)}
    
    for game in playoff_info['matchups']:
        matchup = {
            'bracket': game['bracket'],
            'game': game['game'],
        }
        
        if 'seed1' in game:
            # Seeded matchup (week 16)
            matchup['team1'] = seed_to_team.get(game['seed1'])
            matchup['team2'] = seed_to_team.get(game['seed2'])
            matchup['seed1'] = game['seed1']
            matchup['seed2'] = game['seed2']
        elif 'from_games' in game and week_16_results:
            # Bracket-based matchup (week 17)
            teams = []
            for from_game in game['from_games']:
                if from_game in week_16_results:
                    team = week_16_results[from_game].get(game['take'][:-1])  # 'winners' -> 'winner'
                    if team:
                        teams.append(team)
            
            if len(teams) == 2:
                matchup['team1'] = teams[0]
                matchup['team2'] = teams[1]
            else:
                matchup['team1'] = 'TBD'
                matchup['team2'] = 'TBD'
        else:
            matchup['team1'] = 'TBD'
            matchup['team2'] = 'TBD'
        
        matchups.append(matchup)
    
    return matchups


def get_schedule_data(standings: list[dict] = None, weeks: list[dict] = None) -> list[dict]:
    """Convert schedule to JSON format with team codes."""
    schedule_data = []
    
    # Regular season weeks 1-15
    for week_num, matchups in enumerate(SCHEDULE, 1):
        week_matchups = []
        for owner1, owner2 in matchups:
            week_matchups.append({
                'team1': OWNER_TO_CODE.get(owner1, owner1),
                'team2': OWNER_TO_CODE.get(owner2, owner2),
            })
        schedule_data.append({
            'week': week_num,
            'is_rivalry': week_num == 5,
            'is_playoffs': False,
            'matchups': week_matchups,
        })
    
    # Calculate week 16 results for week 17 matchups
    week_16_results = {}
    if weeks:
        for week_data in weeks:
            if week_data.get('week') == 16:
                for matchup in week_data.get('matchups', []):
                    t1 = matchup.get('team1', {})
                    t2 = matchup.get('team2', {})
                    game_id = matchup.get('game')
                    
                    if game_id and t1.get('total_score') is not None and t2.get('total_score') is not None:
                        s1, s2 = t1['total_score'], t2['total_score']
                        if s1 > s2:
                            week_16_results[game_id] = {'winner': t1['abbrev'], 'loser': t2['abbrev']}
                        elif s2 > s1:
                            week_16_results[game_id] = {'winner': t2['abbrev'], 'loser': t1['abbrev']}
                        # If tied, don't set winner/loser (TBD)
                break
    
    # Playoff weeks 16-17
    if standings:
        for week_num in [16, 17]:
            playoff_info = PLAYOFF_STRUCTURE[week_num]
            week_matchups = get_playoff_matchups(standings, week_num, week_16_results if week_num == 17 else None)
            
            schedule_data.append({
                'week': week_num,
                'is_rivalry': False,
                'is_playoffs': True,
                'playoff_round': playoff_info['round'],
                'matchups': week_matchups,
            })
    
    return schedule_data


def normalize_team_code(team: str) -> str:
    """Normalize team code variations."""
    team = team.strip()
    return TEAM_ALIASES.get(team, team)


def parse_draft_picks(excel_path: str) -> dict[str, dict]:
    """Parse traded picks and calculate what picks each team owns.
    
    Returns:
        Dict mapping team_code -> {
            '2026': {'offseason': [...], 'offseason_taxi': [...], 'waiver': [...], 'waiver_taxi': [...]},
            '2027': {...},
            ...
        }
    """
    # Default picks per team per draft type
    # Offseason: Rounds 1-6, Taxi: Rounds 1-4, Waiver: Rounds 1-4, Waiver Taxi: Rounds 1-4
    DEFAULT_OFFSEASON = list(range(1, 7))  # 1-6
    DEFAULT_TAXI = list(range(1, 5))  # 1-4
    DEFAULT_WAIVER = list(range(1, 5))  # 1-4
    
    SEASONS = ['2026', '2027', '2028', '2029']
    
    # Initialize picks - each team owns their own picks by default
    picks = {}
    for team in ALL_TEAMS:
        picks[team] = {}
        for season in SEASONS:
            picks[team][season] = {
                'offseason': [(r, team) for r in DEFAULT_OFFSEASON],  # (round, original_owner)
                'offseason_taxi': [(r, team) for r in DEFAULT_TAXI],
                'waiver': [(r, team) for r in DEFAULT_WAIVER],
                'waiver_taxi': [(r, team) for r in DEFAULT_TAXI],
            }
    
    # Parse trades from Excel
    try:
        wb = openpyxl.load_workbook(excel_path)
        ws = wb.active
    except Exception as e:
        print(f"Warning: Could not load traded picks: {e}")
        return picks
    
    # Pattern: '[HOLDER] holds [OWNER] [ROUND] rounder/round taxi/round waiver'
    pattern = r'([A-Z/]+)\s+holds\s+([A-Z/]+)\s+(\d+)(?:st|nd|rd|th)\s+(rounder|round taxi|round waiver)'
    
    # Map columns to seasons
    season_cols = {1: '2026', 2: '2027', 3: '2028', 4: '2029'}
    
    # Track draft type context per column
    draft_type = {1: 'offseason', 2: 'offseason', 3: 'offseason', 4: 'offseason'}
    
    trades = []  # (season, holder, original_owner, round, pick_type)
    
    for row_num in range(5, 50):
        for col in range(1, 5):
            cell_val = ws.cell(row=row_num, column=col).value
            if not cell_val:
                continue
            
            cell_str = str(cell_val).strip()
            
            # Check for draft type headers
            if cell_str == 'Offseason Draft':
                draft_type[col] = 'offseason'
                continue
            elif cell_str == 'Waiver Draft':
                draft_type[col] = 'waiver'
                continue
            
            # Skip notes (starting with *)
            if cell_str.startswith('*'):
                continue
            
            # Parse the transaction
            match = re.search(pattern, cell_str, re.IGNORECASE)
            if match:
                holder = normalize_team_code(match.group(1))
                original = normalize_team_code(match.group(2))
                round_num = int(match.group(3))
                pick_type_str = match.group(4).lower()
                
                season = season_cols.get(col, '2026')
                
                # Determine full pick type
                if pick_type_str == 'rounder':
                    pick_type = draft_type[col]  # 'offseason' or 'waiver'
                elif pick_type_str == 'round taxi':
                    pick_type = f'{draft_type[col]}_taxi'
                elif pick_type_str == 'round waiver':
                    pick_type = 'waiver'
                else:
                    continue
                
                trades.append((season, holder, original, round_num, pick_type))
    
    wb.close()
    
    # Apply trades
    for season, holder, original, round_num, pick_type in trades:
        if holder not in ALL_TEAMS or original not in ALL_TEAMS:
            continue
        if season not in SEASONS:
            continue
        
        # Remove from original owner
        original_picks = picks[original][season][pick_type]
        pick_to_remove = None
        for i, (r, owner) in enumerate(original_picks):
            if r == round_num and owner == original:
                pick_to_remove = i
                break
        if pick_to_remove is not None:
            original_picks.pop(pick_to_remove)
        
        # Add to holder
        picks[holder][season][pick_type].append((round_num, original))
    
    # Sort picks and format for output
    formatted = {}
    for team in ALL_TEAMS:
        formatted[team] = {}
        for season in SEASONS:
            formatted[team][season] = {}
            for draft_type_key in ['offseason', 'offseason_taxi', 'waiver', 'waiver_taxi']:
                # Sort by round number, then by original owner
                team_picks = sorted(picks[team][season][draft_type_key], key=lambda x: (x[0], x[1]))
                # Format as list of {round, from} objects
                formatted[team][season][draft_type_key] = [
                    {'round': r, 'from': owner, 'own': owner == team}
                    for r, owner in team_picks
                ]
    
    return formatted


# Excel structure constants
POSITION_ROWS = {
    'QB': (6, [7, 8, 9]),
    'RB': (11, [12, 13, 14, 15]),
    'WR': (17, [18, 19, 20, 21, 22]),
    'TE': (24, [25, 26, 27]),
    'K': (29, [30, 31]),
    'D/ST': (33, [34, 35]),
    'HC': (37, [38, 39]),
    'OL': (41, [42, 43]),
}

# Taxi squad rows: position header on even rows (48, 50, 52, 54), player on odd rows (49, 51, 53, 55)
TAXI_ROWS = [(48, 49), (50, 51), (52, 53), (54, 55)]  # (position_row, player_row) pairs

# FA Pool location (column W = 23, rows 12-21)
FA_POOL_COLUMN = 23
FA_POOL_ROWS = range(12, 22)

# FA Pool player positions (manually mapped since not in Excel)
FA_POOL_POSITIONS = {
    'Shedeur Sanders': 'QB',
    'Dylan Sampson': 'RB',
    'Trevor Etienne': 'RB',
    'Ray Davis': 'RB',
    'Braelon Allen': 'RB',
    'Jack Bech': 'WR',
    'Isaac TeSlaa': 'WR',
    'Tez Johnson': 'WR',
    'Gunnar Helm': 'TE',
    'New York Jets': 'D/ST',
}

TEAM_COLUMNS = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]

# Trade deadline
TRADE_DEADLINE_WEEK = 12


def parse_player_name(cell_value: str) -> tuple[str, str]:
    """Parse 'Player Name (TEAM)' into (name, team)."""
    if not cell_value:
        return "", ""
    match = re.match(r'^(.+?)\s*\(([A-Z]{2,3})\)$', cell_value.strip())
    if match:
        name = match.group(1).strip()
        team = match.group(2)
    else:
        name = cell_value.strip()
        team = ""
    
    # Apply fuzzy matching to get canonical name from rosters.json
    name = _match_canonical_name(name)
    return name, team


def parse_fa_pool(ws) -> list[dict]:
    """Parse the FA pool from the Excel worksheet."""
    fa_pool = []
    for row in FA_POOL_ROWS:
        cell_value = ws.cell(row=row, column=FA_POOL_COLUMN).value
        if cell_value:
            player_name, nfl_team = parse_player_name(str(cell_value))
            if player_name:
                position = FA_POOL_POSITIONS.get(player_name, 'Unknown')
                fa_pool.append({
                    'name': player_name,
                    'nfl_team': nfl_team,
                    'position': position,
                    'available': True  # Will be set to False if activated
                })
    return fa_pool


def export_week(ws, week_num: int, bench_scores: dict = None) -> dict[str, Any]:
    """Export a single week's data to dict format.
    
    Args:
        ws: Excel worksheet
        week_num: Week number
        bench_scores: Optional dict mapping (team_abbrev, player_name) -> score for bench players
    """
    matchups = []
    teams_data = []
    
    # Get all team info
    for i, col in enumerate(TEAM_COLUMNS):
        team_name = ws.cell(row=2, column=col).value
        if not team_name:
            continue
        
        team_name = str(team_name).strip().strip('*')
        owner = ws.cell(row=3, column=col).value or ""
        abbrev = ws.cell(row=4, column=col).value or ""
        
        # Get all players and scores
        roster = []
        total_score = 0.0
        
        for position, (header_row, player_rows) in POSITION_ROWS.items():
            for row in player_rows:
                player_cell = ws.cell(row=row, column=col)
                score_cell = ws.cell(row=row, column=col + 1)
                
                if player_cell.value:
                    player_name, nfl_team = parse_player_name(str(player_cell.value))
                    is_starter = player_cell.font.bold if player_cell.font else False
                    excel_score = float(score_cell.value) if score_cell.value else 0.0
                    
                    # For bench players, use calculated score if available
                    if is_starter:
                        score = excel_score
                    elif bench_scores and (abbrev, player_name) in bench_scores:
                        score = bench_scores[(abbrev, player_name)]
                    else:
                        score = excel_score
                    
                    roster.append({
                        'name': player_name,
                        'nfl_team': nfl_team,
                        'position': position,
                        'score': score,
                        'starter': is_starter,
                    })
                    
                    if is_starter:
                        total_score += excel_score  # Always use Excel score for total
        
        # Get taxi squad players
        taxi_squad = []
        for pos_row, player_row in TAXI_ROWS:
            pos_cell = ws.cell(row=pos_row, column=col)
            player_cell = ws.cell(row=player_row, column=col)
            
            if pos_cell.value and player_cell.value:
                position = str(pos_cell.value).strip()
                player_name, nfl_team = parse_player_name(str(player_cell.value))
                if player_name:
                    taxi_squad.append({
                        'name': player_name,
                        'nfl_team': nfl_team,
                        'position': position,
                    })
        
        teams_data.append({
            'name': team_name,
            'owner': owner,
            'abbrev': abbrev,
            'roster': roster,
            'taxi_squad': taxi_squad,
            'total_score': round(total_score, 1),
        })
    
    # Calculate score_rank from total_scores (1 = highest score)
    sorted_by_score = sorted(teams_data, key=lambda t: t['total_score'], reverse=True)
    for rank, team in enumerate(sorted_by_score, 1):
        team['score_rank'] = rank
    
    # Group into matchups (teams are paired: 0v1, 2v3, etc.)
    for i in range(0, len(teams_data), 2):
        if i + 1 < len(teams_data):
            matchups.append({
                'team1': teams_data[i],
                'team2': teams_data[i + 1],
            })
    
    # Check if week has valid scores (at least one non-zero score)
    has_scores = any(t['total_score'] > 0 for t in teams_data)
    
    return {
        'week': week_num,
        'matchups': matchups,
        'teams': teams_data,
        'has_scores': has_scores,
    }


def get_current_nfl_week() -> int:
    """Get the current NFL week from nflreadpy."""
    return nfl.get_current_week()


def get_game_times(season: int = 2025) -> dict[int, dict[str, str]]:
    """Get game kickoff times for each team by week.
    
    Returns:
        Dict mapping week -> {team_abbrev -> kickoff_datetime_iso}
    """
    try:
        schedule = nfl.load_schedules(seasons=season)
        game_times = {}
        
        for week in range(1, 19):
            week_games = schedule.filter(schedule['week'] == week)
            if week_games.height == 0:
                continue
                
            game_times[week] = {}
            
            for row in week_games.iter_rows(named=True):
                # Get game datetime
                game_date = row.get('gameday', '')
                game_time = row.get('gametime', '')
                
                if game_date and game_time:
                    # Combine date and time into ISO format
                    # gametime is typically in "HH:MM" format (ET)
                    try:
                        dt_str = f"{game_date} {game_time}"
                        # Parse and convert to ISO format with timezone
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                        # NFL times are Eastern, add timezone info
                        # Store as ISO string (frontend will handle timezone)
                        kickoff_iso = dt.strftime("%Y-%m-%dT%H:%M:00-05:00")
                        
                        home_team = row.get('home_team', '')
                        away_team = row.get('away_team', '')
                        
                        if home_team:
                            game_times[week][home_team] = kickoff_iso
                        if away_team:
                            game_times[week][away_team] = kickoff_iso
                    except (ValueError, TypeError):
                        pass
        
        return game_times
    except Exception as e:
        print(f"Warning: Could not load game times: {e}")
        return {}


def calculate_bench_scores(excel_path: str, sheet_name: str, week_num: int) -> dict:
    """Calculate scores for bench players using the scorer.
    
    Returns:
        Dict mapping (team_abbrev, player_name) -> score
    """
    import sys
    # Ensure parent directory is in path for qpfl import
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    
    try:
        from qpfl import QPFLScorer
        from qpfl.excel_parser import parse_roster_from_excel
    except ImportError:
        return {}
    
    try:
        teams = parse_roster_from_excel(excel_path, sheet_name)
        scorer = QPFLScorer(2025, week_num)
        
        bench_scores = {}
        for team in teams:
            for position, players in team.players.items():
                for player_name, nfl_team, is_started in players:
                    if not is_started:  # Only calculate for bench players
                        try:
                            result = scorer.score_player(player_name, nfl_team, position)
                            bench_scores[(team.abbreviation, player_name)] = result.total_points
                        except Exception:
                            pass  # Skip if scoring fails
        
        return bench_scores
    except Exception as e:
        print(f"Warning: Could not calculate bench scores for week {week_num}: {e}")
        return {}


def merge_json_lineup(week_data: dict, lineup_file: Path, week_num: int) -> dict:
    """Merge JSON lineup data into Excel week data.
    
    This allows teams using the website to submit lineups that get merged
    with the Excel data for other teams.
    """
    try:
        with open(lineup_file) as f:
            lineup_data = json.load(f)
    except Exception as e:
        print(f"Warning: Could not read lineup file {lineup_file}: {e}")
        return week_data
    
    json_teams = set(lineup_data.get("lineups", {}).keys())
    if not json_teams:
        return week_data
    
    # Filter out teams with empty lineups (they use Excel, not website)
    active_json_teams = set()
    for team_code, starters in lineup_data.get("lineups", {}).items():
        total_starters = sum(len(v) for v in starters.values())
        if total_starters > 0:
            active_json_teams.add(team_code)
    
    if active_json_teams:
        print(f"  Merging JSON lineups for Week {week_num}: {', '.join(sorted(active_json_teams))}")
    
    # Update starter flags in roster based on JSON lineup data
    for team in week_data.get("teams", []):
        abbrev = team.get("abbrev")
        if abbrev not in active_json_teams:
            continue
        
        json_starters = lineup_data["lineups"][abbrev]
        
        # Update starter flags in roster
        for player in team.get("roster", []):
            position = player.get("position")
            player_name = player.get("name")
            
            # Check if this player is a starter according to JSON
            position_starters = json_starters.get(position, [])
            player["starter"] = player_name in position_starters
        
        # Recalculate total score from starters
        team["total_score"] = sum(
            p["score"] for p in team.get("roster", []) if p.get("starter")
        )
    
    # Rebuild matchups with updated team data
    teams_by_abbrev = {t["abbrev"]: t for t in week_data.get("teams", [])}
    
    new_matchups = []
    if week_num <= len(SCHEDULE):
        # Regular season - use SCHEDULE for matchups
        for owner1, owner2 in SCHEDULE[week_num - 1]:
            t1_abbrev = OWNER_TO_CODE.get(owner1)
            t2_abbrev = OWNER_TO_CODE.get(owner2)
            
            t1 = teams_by_abbrev.get(t1_abbrev)
            t2 = teams_by_abbrev.get(t2_abbrev)
            
            if t1 and t2:
                new_matchups.append({"team1": t1, "team2": t2})
        week_data["matchups"] = new_matchups
    else:
        # Playoff weeks - update existing matchups in place with updated team data
        for matchup in week_data.get("matchups", []):
            t1_abbrev = matchup["team1"]["abbrev"]
            t2_abbrev = matchup["team2"]["abbrev"]
            if t1_abbrev in teams_by_abbrev:
                matchup["team1"] = teams_by_abbrev[t1_abbrev]
            if t2_abbrev in teams_by_abbrev:
                matchup["team2"] = teams_by_abbrev[t2_abbrev]
    
    # Recalculate has_scores
    week_data["has_scores"] = any(t.get("total_score", 0) > 0 for t in week_data.get("teams", []))
    
    # Recalculate score_rank
    sorted_by_score = sorted(week_data.get("teams", []), key=lambda t: t.get("total_score", 0), reverse=True)
    for rank, team in enumerate(sorted_by_score, 1):
        team["score_rank"] = rank
    
    return week_data


def add_playoff_metadata_to_week(weeks: list[dict], standings: list[dict], week_num: int):
    """Add playoff metadata (game, bracket) to week 16 matchups based on standings.
    
    This allows us to determine week 17 matchups from week 16 results.
    """
    if week_num not in PLAYOFF_STRUCTURE:
        return
    
    # Find the week data
    week_data = None
    for w in weeks:
        if w.get('week') == week_num:
            week_data = w
            break
    
    if not week_data:
        return
    
    # Create seed to team and team to seed mappings
    team_to_seed = {}
    for i, team in enumerate(standings):
        team_to_seed[team['abbrev']] = i + 1
    
    # Get expected matchups from playoff structure
    playoff_info = PLAYOFF_STRUCTURE[week_num]
    expected_matchups = playoff_info['matchups']
    
    # Match actual matchups to expected playoff matchups
    # We need to be flexible - match by seed RANGE (1-4 = playoffs, 5-6 = mid bowl, 7-10 = sewer)
    semi_game_counter = 0
    sewer_game_counter = 0
    
    for matchup in week_data.get('matchups', []):
        t1 = matchup.get('team1', {})
        t2 = matchup.get('team2', {})
        t1_abbrev = t1.get('abbrev') if isinstance(t1, dict) else t1
        t2_abbrev = t2.get('abbrev') if isinstance(t2, dict) else t2
        
        t1_seed = team_to_seed.get(t1_abbrev, 99)
        t2_seed = team_to_seed.get(t2_abbrev, 99)
        
        # Determine bracket by seed ranges
        seeds = sorted([t1_seed, t2_seed])
        
        if seeds[0] <= 4 and seeds[1] <= 4:
            # Playoff matchup (seeds 1-4)
            semi_game_counter += 1
            matchup['game'] = f'semi_{semi_game_counter}'
            matchup['bracket'] = 'playoffs'
        elif seeds[0] == 5 and seeds[1] == 6:
            # Mid bowl
            matchup['game'] = 'mid_bowl_week1'
            matchup['bracket'] = 'mid_bowl'
            matchup['two_week'] = True
        elif seeds[0] >= 7 and seeds[1] >= 7:
            # Sewer series (seeds 7-10)
            sewer_game_counter += 1
            matchup['game'] = f'sewer_{sewer_game_counter}'
            matchup['bracket'] = 'sewer_series'


def export_all_weeks(excel_path: str) -> dict[str, Any]:
    """Export all weeks from Excel to JSON format."""
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    
    weeks = []
    # Use team code (abbrev) as unique identifier
    standings = {}  # abbrev -> {rank_points, wins, losses, ties, points_for, points_against, ...}
    
    # Find all week sheets (including playoff sheets with special names)
    week_sheets = []
    playoff_sheet_names = {
        'Semi-Finals': 16,
        'Championship': 17,
    }
    for sheet_name in wb.sheetnames:
        match = re.match(r'^Week (\d+)$', sheet_name)
        if match:
            week_sheets.append((int(match.group(1)), sheet_name))
        elif sheet_name in playoff_sheet_names:
            week_sheets.append((playoff_sheet_names[sheet_name], sheet_name))
    
    # Sort by week number
    week_sheets.sort(key=lambda x: x[0])
    
    # Check for JSON lineup files to merge
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    lineups_dir = project_dir / "data" / "lineups" / "2025"
    
    # Load team name overrides
    team_names_path = project_dir / "data" / "team_names.json"
    team_name_overrides = {}
    if team_names_path.exists():
        with open(team_names_path) as f:
            team_name_overrides = json.load(f).get("team_names", {})
    
    # Export all weeks first
    for week_num, sheet_name in week_sheets:
        ws = wb[sheet_name]
        
        # Calculate bench scores for weeks with data
        bench_scores = calculate_bench_scores(excel_path, sheet_name, week_num)
        if bench_scores:
            print(f"  Calculated {len(bench_scores)} bench scores for Week {week_num}")
        
        week_data = export_week(ws, week_num, bench_scores)
        
        # Check for JSON lineup file and merge if present
        lineup_file = lineups_dir / f"week_{week_num}.json"
        if lineup_file.exists():
            week_data = merge_json_lineup(week_data, lineup_file, week_num)
        
        # Apply team name overrides for this week
        if team_name_overrides:
            for team in week_data.get("teams", []):
                team["name"] = get_team_name_for_week(
                    team["abbrev"], week_num, team_name_overrides, team.get("name", team["abbrev"])
                )
            # Also update matchups
            for matchup in week_data.get("matchups", []):
                for team_key in ["team1", "team2"]:
                    team = matchup.get(team_key, {})
                    if isinstance(team, dict) and "abbrev" in team:
                        team["name"] = get_team_name_for_week(
                            team["abbrev"], week_num, team_name_overrides, team.get("name", team["abbrev"])
                        )
        
        weeks.append(week_data)
    
    # Determine which weeks to include in standings
    # Only include completed weeks (before current NFL week)
    current_nfl_week = get_current_nfl_week()
    
    print(f"Current NFL week: {current_nfl_week}, standings include weeks 1-{current_nfl_week - 1}")
    
    for week_data in weeks:
        # Skip weeks without scores for standings calculation
        if not week_data.get('has_scores', False):
            continue
        
        # Only include regular season weeks (1-15) for standings
        # Playoff weeks (16+) don't affect regular season standings
        if week_data['week'] > 15:
            continue
        
        # Update standings using team code as unique ID
        for matchup in week_data['matchups']:
            t1, t2 = matchup['team1'], matchup['team2']
            
            for team in [t1, t2]:
                abbrev = team['abbrev']
                if abbrev not in standings:
                    standings[abbrev] = {
                        'name': team['name'],
                        'owner': team['owner'],
                        'abbrev': abbrev,
                        'rank_points': 0.0,
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'top_half': 0,
                        'points_for': 0.0,
                        'points_against': 0.0,
                    }
                else:
                    # Update name/owner to latest (they may change)
                    standings[abbrev]['name'] = team['name']
                    standings[abbrev]['owner'] = team['owner']
            
            # Get scores
            s1 = t1['total_score']
            s2 = t2['total_score']
            
            # Update points for/against
            standings[t1['abbrev']]['points_for'] += s1
            standings[t1['abbrev']]['points_against'] += s2
            standings[t2['abbrev']]['points_for'] += s2
            standings[t2['abbrev']]['points_against'] += s1
            
            # Calculate rank points for matchup result
            # Win = 1 point, Tie = 0.5 points each
            if s1 > s2:
                standings[t1['abbrev']]['rank_points'] += 1.0
                standings[t1['abbrev']]['wins'] += 1
                standings[t2['abbrev']]['losses'] += 1
            elif s2 > s1:
                standings[t2['abbrev']]['rank_points'] += 1.0
                standings[t2['abbrev']]['wins'] += 1
                standings[t1['abbrev']]['losses'] += 1
            else:
                standings[t1['abbrev']]['rank_points'] += 0.5
                standings[t2['abbrev']]['rank_points'] += 0.5
                standings[t1['abbrev']]['ties'] += 1
                standings[t2['abbrev']]['ties'] += 1
        
        # Calculate top 5 bonus for each team based on their score_rank
        # Group teams by score to handle ties
        teams_by_score = sorted(week_data['teams'], key=lambda x: x['total_score'], reverse=True)
        
        # Assign ranks handling ties (teams with same score share the rank)
        current_rank = 1
        i = 0
        while i < len(teams_by_score):
            # Find all teams with the same score
            current_score = teams_by_score[i]['total_score']
            tied_teams = []
            while i < len(teams_by_score) and teams_by_score[i]['total_score'] == current_score:
                tied_teams.append(teams_by_score[i])
                i += 1
            
            # Check if any of these tied positions are in top 5
            tied_positions = list(range(current_rank, current_rank + len(tied_teams)))
            positions_in_top5 = [p for p in tied_positions if p <= 5]
            
            if positions_in_top5:
                # Calculate points: 0.5 points shared among tied teams that span top 5
                # If some positions are in top 5 and some aren't, split proportionally
                points_per_team = (0.5 * len(positions_in_top5)) / len(tied_teams)
                
                for team in tied_teams:
                    standings[team['abbrev']]['rank_points'] += points_per_team
                    standings[team['abbrev']]['top_half'] += 1
            
            current_rank += len(tied_teams)
    
    # Sort standings by: 1) rank_points, 2) wins (tiebreaker), 3) points_for (second tiebreaker)
    sorted_standings = sorted(
        standings.values(),
        key=lambda x: (x['rank_points'], x['wins'], x['points_for']),
        reverse=True
    )
    
    wb.close()
    
    # Add playoff metadata to week 16 matchups
    add_playoff_metadata_to_week(weeks, sorted_standings, 16)
    
    # Use nflreadpy's current week for schedule highlighting and matchup default
    current_week = get_current_nfl_week()
    
    # Apply team name overrides to canonical teams
    teams_data = load_teams()
    current_teams_data = apply_team_name_overrides(teams_data, current_week, team_name_overrides)
    
    return {
        'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'season': 2025,
        'current_week': current_week,
        'teams': current_teams_data,  # Canonical team info (with current week names)
        'rosters': load_rosters(),  # Full roster for each team
        'weeks': weeks,
        'standings': sorted_standings,
        'schedule': get_schedule_data(sorted_standings, weeks),
        'game_times': get_game_times(2025),
        'fa_pool': parse_fa_pool(wb[week_sheets[-1][1]]) if week_sheets else [],
        'pending_trades': load_pending_trades(),
        'trade_deadline_week': TRADE_DEADLINE_WEEK,
    }


def load_pending_trades() -> list[dict]:
    """Load pending trades from JSON file."""
    pending_trades_path = Path(__file__).parent.parent / 'data' / 'pending_trades.json'
    if pending_trades_path.exists():
        with open(pending_trades_path) as f:
            return json.load(f).get("trades", [])
    return []


def load_teams() -> list[dict]:
    """Load canonical team info from teams.json."""
    teams_path = Path(__file__).parent.parent / 'data' / 'teams.json'
    if teams_path.exists():
        with open(teams_path) as f:
            return json.load(f).get("teams", [])
    return []


def load_rosters() -> dict[str, list[dict]]:
    """Load full rosters from rosters.json."""
    rosters_path = Path(__file__).parent.parent / 'data' / 'rosters.json'
    if rosters_path.exists():
        with open(rosters_path) as f:
            return json.load(f)
    return {}


def parse_constitution(doc_path: str) -> list[dict]:
    """Parse constitution document into structured sections with nested lists."""
    docx = get_docx_module()
    if not docx:
        return []
    
    doc = docx.Document(doc_path)
    sections = []
    current_article = None
    current_section = None
    
    # Indentation thresholds (in EMUs)
    LEVEL_1 = 800000   # Section headers
    LEVEL_2 = 1200000  # List items
    LEVEL_3 = 1600000  # Sub-list items
    
    def get_indent_level(para):
        """Get indentation level based on left indent."""
        left_indent = para.paragraph_format.left_indent
        if left_indent is None:
            return 0
        if left_indent >= LEVEL_3:
            return 3
        if left_indent >= LEVEL_2:
            return 2
        if left_indent >= LEVEL_1:
            return 1
        return 0
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        style = para.style.name if para.style else ''
        
        if style == 'Title':
            continue  # Skip title
        elif style == 'Heading 1':
            # New article
            current_article = {'title': text, 'sections': []}
            sections.append(current_article)
            current_section = None
        elif style == 'Heading 2':
            # New section
            if current_article:
                current_section = {'title': text, 'content': []}
                current_article['sections'].append(current_section)
        elif style == 'Heading 3':
            # Sub-section header
            if current_section:
                current_section['content'].append({'type': 'subheader', 'text': text})
        else:
            # Normal content with indentation
            if current_section:
                indent = get_indent_level(para)
                if indent >= 3:
                    current_section['content'].append({'type': 'subitem', 'text': text})
                elif indent >= 2:
                    current_section['content'].append({'type': 'item', 'text': text})
                else:
                    current_section['content'].append({'type': 'header', 'text': text})
            elif current_article:
                # Content directly under article
                if not current_article.get('intro'):
                    current_article['intro'] = []
                current_article['intro'].append(text)
    
    return sections


def parse_hall_of_fame(doc_path: str) -> dict:
    """Parse Hall of Fame document."""
    docx = get_docx_module()
    if not docx:
        return {}
    
    doc = docx.Document(doc_path)
    
    result = {
        'finishes_by_year': [],
        'mvps': [],
        'team_records': [],
        'player_records': [],
        'owner_stats': [],
    }
    
    current_year = None
    current_section = None
    current_subsection = None
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        style = para.style.name if para.style else ''
        
        if style == 'Title':
            continue
        elif style == 'Heading 1':
            if 'Summary' in text:
                current_section = 'summary'
            elif 'Finishes' in text:
                current_section = 'finishes'
            elif 'Team Records' in text:
                current_section = 'team_records'
            elif 'Player Records' in text:
                current_section = 'player_records'
            else:
                current_section = text
        elif style == 'Heading 2':
            if current_section == 'finishes':
                # Year header
                current_year = {'year': text, 'results': []}
                result['finishes_by_year'].append(current_year)
            elif current_section in ['team_records', 'player_records']:
                # Check if this looks like a record (contains "over" and parentheses with year)
                # This handles the "Largest Margin of Victory" records that are styled as Heading 2
                if ' over ' in text and '(' in text and ')' in text:
                    # This is actually a record, add to previous subsection
                    if current_subsection:
                        current_subsection['records'].append(text)
                else:
                    current_subsection = {'title': text, 'records': []}
                    result[current_section].append(current_subsection)
            elif 'MVP' in text:
                current_section = 'mvps'
        elif style == 'Heading 3':
            if current_section in ['team_records', 'player_records']:
                current_subsection = {'title': text, 'records': []}
                result[current_section].append(current_subsection)
        else:
            if current_section == 'finishes' and current_year:
                current_year['results'].append(text)
            elif current_section == 'mvps':
                result['mvps'].append(text)
            elif current_subsection:
                current_subsection['records'].append(text)
    
    # Parse owner stats table
    if doc.tables:
        table = doc.tables[0]
        headers = [cell.text.strip() for cell in table.rows[0].cells]
        for row in table.rows[1:]:
            cells = [cell.text.strip() for cell in row.cells]
            if cells[0]:  # Has owner name
                owner_data = dict(zip(headers, cells))
                result['owner_stats'].append(owner_data)
    
    # Clean up empty sections
    result['team_records'] = [s for s in result['team_records'] if s['records']]
    result['player_records'] = [s for s in result['player_records'] if s['records']]
    
    return result


def parse_transactions(doc_path: str) -> list[dict]:
    """Parse transactions document into structured seasons/weeks with indentation."""
    docx = get_docx_module()
    if not docx:
        return []
    
    doc = docx.Document(doc_path)
    seasons = []
    current_season = None
    current_week = None
    current_transaction = None
    
    # Indentation thresholds (in EMUs: 914400 = 1 inch)
    LEVEL_1 = 400000   # ~0.44 inch - transaction header
    LEVEL_2 = 800000   # ~0.87 inch - sub-header (date, "To X:")
    LEVEL_3 = 1200000  # ~1.31 inch - list items
    
    def get_indent_level(para):
        """Get indentation level (0-3) based on left indent."""
        left_indent = para.paragraph_format.left_indent
        if left_indent is None:
            return 0
        if left_indent >= LEVEL_3:
            return 3
        if left_indent >= LEVEL_2:
            return 2
        if left_indent >= LEVEL_1:
            return 1
        return 0
    
    def save_transaction():
        nonlocal current_transaction
        if current_transaction and current_week:
            current_week['transactions'].append(current_transaction)
            current_transaction = None
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        style = para.style.name if para.style else ''
        
        if style == 'Title':
            continue
        elif style == 'Heading 1':
            # New season
            save_transaction()
            current_season = {'season': text, 'weeks': []}
            seasons.append(current_season)
            current_week = None
        elif style == 'Heading 2':
            # New week/event
            save_transaction()
            if current_season:
                current_week = {'title': text, 'transactions': []}
                current_season['weeks'].append(current_week)
        else:
            # Transaction content with indentation
            if text.lower() == 'none':
                continue
            
            indent = get_indent_level(para)
            
            if indent <= 1:
                # New transaction block
                save_transaction()
                current_transaction = {'title': text, 'items': []}
            elif indent == 2:
                # Sub-header within transaction
                if current_transaction:
                    current_transaction['items'].append({'type': 'header', 'text': text})
            else:
                # List item (indent level 3)
                if current_transaction:
                    current_transaction['items'].append({'type': 'item', 'text': text})
    
    # Save any remaining transaction
    save_transaction()
    
    # Filter out empty weeks
    for season in seasons:
        season['weeks'] = [w for w in season['weeks'] if w['transactions']]
    
    return seasons


def load_transaction_log() -> list[dict]:
    """Load transactions from the JSON log file."""
    log_path = Path(__file__).parent.parent / 'data' / 'transaction_log.json'
    if log_path.exists():
        with open(log_path) as f:
            return json.load(f).get("transactions", [])
    return []


def format_transaction_for_display(tx: dict) -> dict:
    """Format a JSON transaction into the display format."""
    items = []
    
    if tx["type"] == "trade":
        # Format trade transaction
        items.append({"type": "header", "text": tx.get("timestamp", "")[:10].replace("-", "/")})
        items.append({"type": "header", "text": f"To {tx.get('partner', 'Unknown')}:"})
        for player in tx.get("proposer_gives", {}).get("players", []):
            items.append({"type": "item", "text": player})
        for pick in tx.get("proposer_gives", {}).get("picks", []):
            items.append({"type": "item", "text": pick})
        items.append({"type": "header", "text": f"To {tx.get('proposer', 'Unknown')}:"})
        for player in tx.get("proposer_receives", {}).get("players", []):
            items.append({"type": "item", "text": player})
        for pick in tx.get("proposer_receives", {}).get("picks", []):
            items.append({"type": "item", "text": pick})
        
        return {
            "title": f"Trade between {tx.get('proposer', '?')} and {tx.get('partner', '?')}",
            "items": items
        }
    
    elif tx["type"] == "taxi_activation":
        items.append({"type": "header", "text": tx.get("timestamp", "")[:10].replace("-", "/")})
        items.append({"type": "header", "text": f"Activated {tx.get('activated', 'Unknown')}, released {tx.get('released', 'Unknown')}"})
        return {
            "title": tx.get("team", "Unknown"),
            "items": items
        }
    
    elif tx["type"] == "fa_activation":
        items.append({"type": "header", "text": tx.get("timestamp", "")[:10].replace("-", "/")})
        items.append({"type": "header", "text": f"Added {tx.get('added', 'Unknown')} from FA Pool, released {tx.get('released', 'Unknown')}"})
        return {
            "title": tx.get("team", "Unknown"),
            "items": items
        }
    
    return {"title": "Unknown Transaction", "items": items}


def merge_transaction_log(doc_transactions: list[dict]) -> list[dict]:
    """Merge JSON log transactions with document transactions."""
    json_transactions = load_transaction_log()
    
    if not json_transactions:
        return doc_transactions
    
    # Group JSON transactions by week
    week_transactions = {}
    for tx in json_transactions:
        week = tx.get("week", 0)
        if week not in week_transactions:
            week_transactions[week] = []
        week_transactions[week].append(format_transaction_for_display(tx))
    
    # Find or create current season (2025 Season)
    current_season = None
    for season in doc_transactions:
        if "2025" in season.get("season", ""):
            current_season = season
            break
    
    if not current_season:
        current_season = {"season": "2025 Season", "weeks": []}
        doc_transactions.insert(0, current_season)
    
    # Add JSON transactions to appropriate weeks
    for week_num, txs in week_transactions.items():
        # Find existing week
        week_title = f"Week {week_num}"
        existing_week = None
        for w in current_season["weeks"]:
            if f"Week {week_num}" in w.get("title", ""):
                existing_week = w
                break
        
        if existing_week:
            # Add to existing week (at the beginning - newest first)
            existing_week["transactions"] = txs + existing_week["transactions"]
        else:
            # Create new week
            new_week = {"title": week_title, "transactions": txs}
            # Insert in order (higher week numbers first for most recent)
            inserted = False
            for i, w in enumerate(current_season["weeks"]):
                # Extract week number from title
                try:
                    existing_week_num = int(''.join(filter(str.isdigit, w["title"].split()[0:2][1])) or 0)
                    if week_num > existing_week_num:
                        current_season["weeks"].insert(i, new_week)
                        inserted = True
                        break
                except (ValueError, IndexError, KeyError):
                    continue
            if not inserted:
                current_season["weeks"].append(new_week)
    
    return doc_transactions


def extract_banner_images(doc_path: str, output_dir: str) -> list[str]:
    """Extract banner images from docx."""
    os.makedirs(output_dir, exist_ok=True)
    images = []
    
    with zipfile.ZipFile(doc_path, 'r') as z:
        for name in z.namelist():
            if name.startswith('word/media/'):
                img_name = name.split('/')[-1]
                data = z.read(name)
                out_path = os.path.join(output_dir, img_name)
                with open(out_path, 'wb') as f:
                    f.write(data)
                images.append(img_name)
    
    return sorted(images)


def main():
    """Main export function."""
    # Get paths relative to script location
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    excel_path = project_dir / "2025 Scores.xlsx"
    output_path = project_dir / "web" / "data.json"
    web_dir = project_dir / "web"
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Exporting {excel_path} to {output_path}...")
    
    data = export_all_weeks(str(excel_path))
    
    # Parse additional documents if available (check docs folder first, then root)
    docs_dir = project_dir / "docs"
    
    def find_doc(name: str) -> Path:
        """Find document in docs folder or root."""
        docs_path = docs_dir / name
        root_path = project_dir / name
        if docs_path.exists():
            return docs_path
        return root_path
    
    constitution_path = find_doc("Constitution of the QPFL.docx")
    hof_path = find_doc("QPFL Hall of Fame.docx")
    banner_path = find_doc("Banner Room.docx")
    
    if constitution_path.exists() and get_docx_module():
        print("Parsing constitution...")
        data['constitution'] = parse_constitution(str(constitution_path))
    
    if hof_path.exists() and get_docx_module():
        print("Parsing Hall of Fame...")
        data['hall_of_fame'] = parse_hall_of_fame(str(hof_path))
        # Extract HOF images
        extract_banner_images(str(hof_path), str(web_dir / "images" / "hof"))
    
    # Check for existing properly-named banner files first
    banners_dir = web_dir / "images" / "banners"
    existing_banners = sorted([f.name for f in banners_dir.glob("*_banner.png")]) if banners_dir.exists() else []
    
    if existing_banners:
        print(f"Using {len(existing_banners)} existing banner images...")
        data['banners'] = existing_banners
    elif banner_path.exists():
        print("Extracting banner images from docx...")
        banner_images = extract_banner_images(str(banner_path), str(banners_dir))
        data['banners'] = sorted(banner_images)
    
    # Parse traded picks
    traded_picks_path = project_dir / "Traded Picks.xlsx"
    if traded_picks_path.exists():
        print("Parsing draft picks...")
        data['draft_picks'] = parse_draft_picks(str(traded_picks_path))
    
    # Parse transactions
    transactions_path = find_doc("Transactions.docx")
    if transactions_path.exists() and get_docx_module():
        print("Parsing transactions...")
        doc_transactions = parse_transactions(str(transactions_path))
        data['transactions'] = merge_transaction_log(doc_transactions)
    else:
        # Even without the Word doc, include JSON log transactions
        data['transactions'] = merge_transaction_log([])
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(data['weeks'])} weeks")
    print(f"Standings: {len(data['standings'])} teams")
    print(f"Updated at: {data['updated_at']}")


def get_team_name_for_week(abbrev: str, week: int, team_name_overrides: dict, default_name: str) -> str:
    """Get the team name for a specific week, applying any overrides."""
    if abbrev not in team_name_overrides:
        return default_name
    
    # Find the most recent name that's effective for this week
    name_entries = team_name_overrides[abbrev]
    current_name = default_name
    
    for entry in name_entries:
        if entry.get("effective_week", 1) <= week:
            current_name = entry.get("name", default_name)
    
    return current_name


def apply_team_name_overrides(teams_data: list, week: int, team_name_overrides: dict) -> list:
    """Apply team name overrides for a specific week."""
    if not team_name_overrides:
        return teams_data
    
    updated_teams = []
    for team in teams_data:
        team_copy = team.copy()
        team_copy["name"] = get_team_name_for_week(
            team["abbrev"], week, team_name_overrides, team.get("name", team["abbrev"])
        )
        updated_teams.append(team_copy)
    
    return updated_teams


def export_from_json(data_dir: Path, season: int = 2025) -> dict[str, Any]:
    """Export data from JSON files instead of Excel.
    
    This reads from:
    - data/teams.json - team info
    - data/rosters.json - player rosters
    - data/lineups/{season}/week_X.json - weekly lineups
    
    And uses the scorer to calculate player scores.
    """
    import sys
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    
    # Load teams
    with open(data_dir / "teams.json") as f:
        teams_data = json.load(f)["teams"]
    
    # Load team name overrides
    team_names_path = data_dir / "team_names.json"
    team_name_overrides = {}
    if team_names_path.exists():
        with open(team_names_path) as f:
            team_name_overrides = json.load(f).get("team_names", {})
    
    teams_by_abbrev = {t["abbrev"]: t for t in teams_data}
    
    # Load rosters
    with open(data_dir / "rosters.json") as f:
        rosters = json.load(f)
    
    # Find all lineup files
    lineups_dir = data_dir / "lineups" / str(season)
    lineup_files = sorted(lineups_dir.glob("week_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    
    if not lineup_files:
        print(f"No lineup files found in {lineups_dir}")
        return {}
    
    # Import scorer
    try:
        from qpfl import QPFLScorer
        scorer_available = True
    except ImportError:
        scorer_available = False
        print("Warning: QPFLScorer not available, scores will be 0")
    
    weeks = []
    standings = {}
    current_nfl_week = get_current_nfl_week()
    
    print(f"Current NFL week: {current_nfl_week}")
    
    for lineup_file in lineup_files:
        week_num = int(lineup_file.stem.split("_")[1])
        
        with open(lineup_file) as f:
            lineup_data = json.load(f)
        
        # Create scorer for this week
        scorer = QPFLScorer(season, week_num) if scorer_available else None
        
        teams_for_week = []
        
        for abbrev, starters in lineup_data["lineups"].items():
            team_info = teams_by_abbrev.get(abbrev, {})
            roster = rosters.get(abbrev, [])
            
            # Build roster with scores
            roster_with_scores = []
            total_score = 0.0
            
            for player in roster:
                player_name = player["name"]
                position = player["position"]
                nfl_team = player["nfl_team"]
                
                # Check if player is starting
                is_starter = player_name in starters.get(position, [])
                
                # Calculate score
                score = 0.0
                if scorer:
                    try:
                        result = scorer.score_player(player_name, nfl_team, position)
                        score = result.total_points
                    except Exception:
                        pass  # Score stays 0
                
                roster_with_scores.append({
                    "name": player_name,
                    "nfl_team": nfl_team,
                    "position": position,
                    "score": score,
                    "starter": is_starter
                })
                
                if is_starter:
                    total_score += score
            
            # Apply team name override for this week
            team_name = get_team_name_for_week(
                abbrev, week_num, team_name_overrides, team_info.get("name", abbrev)
            )
            
            teams_for_week.append({
                "name": team_name,
                "owner": team_info.get("owner", ""),
                "abbrev": abbrev,
                "roster": roster_with_scores,
                "total_score": round(total_score, 1)
            })
        
        # Calculate score_rank
        sorted_by_score = sorted(teams_for_week, key=lambda t: t["total_score"], reverse=True)
        for rank, team in enumerate(sorted_by_score, 1):
            team["score_rank"] = rank
        
        # Check if week has scores
        has_scores = any(t["total_score"] > 0 for t in teams_for_week)
        
        # Create matchups based on schedule
        week_matchups = []
        if week_num <= len(SCHEDULE):
            for owner1, owner2 in SCHEDULE[week_num - 1]:
                t1_abbrev = OWNER_TO_CODE.get(owner1)
                t2_abbrev = OWNER_TO_CODE.get(owner2)
                
                t1 = next((t for t in teams_for_week if t["abbrev"] == t1_abbrev), None)
                t2 = next((t for t in teams_for_week if t["abbrev"] == t2_abbrev), None)
                
                if t1 and t2:
                    week_matchups.append({"team1": t1, "team2": t2})
        
        weeks.append({
            "week": week_num,
            "matchups": week_matchups,
            "teams": teams_for_week,
            "has_scores": has_scores
        })
        
        # Update standings only for completed weeks
        if has_scores and week_num < current_nfl_week:
            for matchup in week_matchups:
                t1, t2 = matchup["team1"], matchup["team2"]
                
                for team in [t1, t2]:
                    abbrev = team["abbrev"]
                    if abbrev not in standings:
                        standings[abbrev] = {
                            "name": team["name"],
                            "owner": team["owner"],
                            "abbrev": abbrev,
                            "rank_points": 0.0,
                            "wins": 0,
                            "losses": 0,
                            "ties": 0,
                            "top_half": 0,
                            "points_for": 0.0,
                            "points_against": 0.0,
                        }
                
                # Determine winner and award rank points
                # Win = 1 point, Tie = 0.5 points each
                s1, s2 = t1["total_score"], t2["total_score"]
                if s1 > s2:
                    standings[t1["abbrev"]]["rank_points"] += 1.0
                    standings[t1["abbrev"]]["wins"] += 1
                    standings[t2["abbrev"]]["losses"] += 1
                elif s2 > s1:
                    standings[t2["abbrev"]]["rank_points"] += 1.0
                    standings[t2["abbrev"]]["wins"] += 1
                    standings[t1["abbrev"]]["losses"] += 1
                else:
                    standings[t1["abbrev"]]["rank_points"] += 0.5
                    standings[t2["abbrev"]]["rank_points"] += 0.5
                    standings[t1["abbrev"]]["ties"] += 1
                    standings[t2["abbrev"]]["ties"] += 1
                
                standings[t1["abbrev"]]["points_for"] += s1
                standings[t1["abbrev"]]["points_against"] += s2
                standings[t2["abbrev"]]["points_for"] += s2
                standings[t2["abbrev"]]["points_against"] += s1
            
            # Calculate top 5 bonus for each team based on their score_rank
            # Group teams by score to handle ties
            teams_by_score = sorted(teams_for_week, key=lambda x: x["total_score"], reverse=True)
            
            # Assign ranks handling ties (teams with same score share the rank)
            current_rank = 1
            i = 0
            while i < len(teams_by_score):
                current_score = teams_by_score[i]["total_score"]
                tied_teams = []
                while i < len(teams_by_score) and teams_by_score[i]["total_score"] == current_score:
                    tied_teams.append(teams_by_score[i])
                    i += 1
                
                # Check if any of these tied positions are in top 5
                tied_positions = list(range(current_rank, current_rank + len(tied_teams)))
                positions_in_top5 = [p for p in tied_positions if p <= 5]
                
                if positions_in_top5:
                    points_per_team = (0.5 * len(positions_in_top5)) / len(tied_teams)
                    
                    for team in tied_teams:
                        abbrev = team["abbrev"]
                        if abbrev in standings:
                            standings[abbrev]["rank_points"] += points_per_team
                            standings[abbrev]["top_half"] += 1
                
                current_rank += len(tied_teams)
    
    # Sort standings
    standings_list = sorted(
        standings.values(),
        key=lambda s: (s["rank_points"], s["wins"], s["points_for"]),
        reverse=True
    )
    
    # Determine current week
    latest_week = max(w["week"] for w in weeks) if weeks else 1
    
    # Load FA pool from JSON file
    fa_pool_path = data_dir / "fa_pool.json"
    fa_pool = []
    if fa_pool_path.exists():
        with open(fa_pool_path) as f:
            fa_pool = json.load(f).get("players", [])
    
    # Load pending trades
    pending_trades_path = data_dir / "pending_trades.json"
    pending_trades = []
    if pending_trades_path.exists():
        with open(pending_trades_path) as f:
            pending_trades = json.load(f).get("trades", [])
    
    # Apply team name overrides to canonical teams (using current week)
    current_teams_data = apply_team_name_overrides(teams_data, latest_week, team_name_overrides)
    
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "current_week": latest_week,
        "teams": current_teams_data,  # Canonical team info (with current week names)
        "rosters": rosters,  # Full roster for each team
        "weeks": weeks,
        "standings": standings_list,
        "schedule": get_schedule_data(standings_list, weeks),
        "game_times": get_game_times(season),
        "fa_pool": fa_pool,
        "pending_trades": pending_trades,
        "trade_deadline_week": TRADE_DEADLINE_WEEK,
    }


def main_json():
    """Main function using JSON-based data."""
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    data_dir = project_dir / "data"
    web_dir = project_dir / "web"
    output_path = web_dir / "data.json"
    
    print("Exporting from JSON files...")
    data = export_from_json(data_dir)
    
    # Parse additional documents
    docs_dir = project_dir / "docs"
    
    def find_doc(name: str) -> Path:
        docs_path = docs_dir / name
        root_path = project_dir / name
        return docs_path if docs_path.exists() else root_path
    
    constitution_path = find_doc("Constitution of the QPFL.docx")
    hof_path = find_doc("QPFL Hall of Fame.docx")
    banner_path = find_doc("Banner Room.docx")
    
    if constitution_path.exists() and get_docx_module():
        print("Parsing constitution...")
        data['constitution'] = parse_constitution(str(constitution_path))
    
    if hof_path.exists() and get_docx_module():
        print("Parsing Hall of Fame...")
        data['hall_of_fame'] = parse_hall_of_fame(str(hof_path))
        extract_banner_images(str(hof_path), str(web_dir / "images" / "hof"))
    
    banners_dir = web_dir / "images" / "banners"
    existing_banners = sorted([f.name for f in banners_dir.glob("*_banner.png")]) if banners_dir.exists() else []
    
    if existing_banners:
        print(f"Using {len(existing_banners)} existing banner images...")
        data['banners'] = existing_banners
    elif banner_path.exists():
        print("Extracting banner images from docx...")
        banner_images = extract_banner_images(str(banner_path), str(banners_dir))
        data['banners'] = sorted(banner_images)
    
    traded_picks_path = project_dir / "Traded Picks.xlsx"
    if traded_picks_path.exists():
        print("Parsing draft picks...")
        data['draft_picks'] = parse_draft_picks(str(traded_picks_path))
    
    transactions_path = find_doc("Transactions.docx")
    if transactions_path.exists() and get_docx_module():
        print("Parsing transactions...")
        doc_transactions = parse_transactions(str(transactions_path))
        data['transactions'] = merge_transaction_log(doc_transactions)
    else:
        # Even without the Word doc, include JSON log transactions
        data['transactions'] = merge_transaction_log([])
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(data['weeks'])} weeks")
    print(f"Standings: {len(data['standings'])} teams")
    print(f"Updated at: {data['updated_at']}")


def export_historical_season(excel_path: str, season: int) -> dict[str, Any]:
    """Export a historical season from Excel to JSON format.
    
    This is a simplified version for past seasons where:
    - All weeks are completed
    - No live game times needed
    - No lineup merging from JSON files
    - No FA pool or pending trades
    """
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    
    weeks = []
    standings = {}
    
    # Find all week sheets (including playoff sheets with special names)
    week_sheets = []
    playoff_sheet_names = {
        'Semi-Finals': 16,
        'Championship': 17,
    }
    for sheet_name in wb.sheetnames:
        match = re.match(r'^Week (\d+)$', sheet_name)
        if match:
            week_sheets.append((int(match.group(1)), sheet_name))
        elif sheet_name in playoff_sheet_names:
            week_sheets.append((playoff_sheet_names[sheet_name], sheet_name))
    
    # Sort by week number
    week_sheets.sort(key=lambda x: x[0])
    
    # Export all weeks
    for week_num, sheet_name in week_sheets:
        ws = wb[sheet_name]
        week_data = export_week(ws, week_num, bench_scores=None)
        weeks.append(week_data)
    
    # Calculate standings from all weeks (all are completed for historical seasons)
    for week_data in weeks:
        if not week_data.get('has_scores', False):
            continue
        
        # Skip playoff weeks for standings calculation
        if week_data['week'] > 15:
            continue
        
        for matchup in week_data['matchups']:
            t1, t2 = matchup['team1'], matchup['team2']
            
            for team in [t1, t2]:
                abbrev = team['abbrev']
                if abbrev not in standings:
                    standings[abbrev] = {
                        'name': team['name'],
                        'owner': team['owner'],
                        'abbrev': abbrev,
                        'rank_points': 0.0,
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'top_half': 0,
                        'points_for': 0.0,
                        'points_against': 0.0,
                    }
                else:
                    standings[abbrev]['name'] = team['name']
                    standings[abbrev]['owner'] = team['owner']
            
            s1 = t1['total_score']
            s2 = t2['total_score']
            
            standings[t1['abbrev']]['points_for'] += s1
            standings[t1['abbrev']]['points_against'] += s2
            standings[t2['abbrev']]['points_for'] += s2
            standings[t2['abbrev']]['points_against'] += s1
            
            if s1 > s2:
                standings[t1['abbrev']]['rank_points'] += 1.0
                standings[t1['abbrev']]['wins'] += 1
                standings[t2['abbrev']]['losses'] += 1
            elif s2 > s1:
                standings[t2['abbrev']]['rank_points'] += 1.0
                standings[t2['abbrev']]['wins'] += 1
                standings[t1['abbrev']]['losses'] += 1
            else:
                standings[t1['abbrev']]['rank_points'] += 0.5
                standings[t2['abbrev']]['rank_points'] += 0.5
                standings[t1['abbrev']]['ties'] += 1
                standings[t2['abbrev']]['ties'] += 1
        
        # Calculate top 5 bonus
        teams_by_score = sorted(week_data['teams'], key=lambda x: x['total_score'], reverse=True)
        
        current_rank = 1
        i = 0
        while i < len(teams_by_score):
            current_score = teams_by_score[i]['total_score']
            tied_teams = []
            while i < len(teams_by_score) and teams_by_score[i]['total_score'] == current_score:
                tied_teams.append(teams_by_score[i])
                i += 1
            
            tied_positions = list(range(current_rank, current_rank + len(tied_teams)))
            positions_in_top5 = [p for p in tied_positions if p <= 5]
            
            if positions_in_top5:
                points_per_team = (0.5 * len(positions_in_top5)) / len(tied_teams)
                
                for team in tied_teams:
                    standings[team['abbrev']]['rank_points'] += points_per_team
                    standings[team['abbrev']]['top_half'] += 1
            
            current_rank += len(tied_teams)
    
    # Sort standings by: 1) rank_points, 2) wins (tiebreaker), 3) points_for (second tiebreaker)
    sorted_standings = sorted(
        standings.values(),
        key=lambda x: (x['rank_points'], x['wins'], x['points_for']),
        reverse=True
    )
    
    wb.close()
    
    # Get the final week number
    final_week = max(w['week'] for w in weeks) if weeks else 17
    
    # Extract team info from the final week's data
    teams_data = []
    if weeks:
        final_week_data = weeks[-1]
        for team in final_week_data.get('teams', []):
            teams_data.append({
                'name': team['name'],
                'owner': team['owner'],
                'abbrev': team['abbrev'],
            })
    
    return {
        'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'season': season,
        'current_week': final_week,
        'is_historical': True,
        'teams': teams_data,
        'weeks': weeks,
        'standings': sorted_standings,
        'schedule': [],  # No schedule needed for historical seasons
        'game_times': {},  # No game times for historical
    }


def export_historical(season: int):
    """Export a historical season to JSON."""
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    
    excel_path = project_dir / "previous_seasons" / f"{season} Scores.xlsx"
    output_path = project_dir / "web" / f"data_{season}.json"
    
    if not excel_path.exists():
        print(f"Error: {excel_path} not found")
        return
    
    print(f"Exporting historical season {season}...")
    data = export_historical_season(str(excel_path), season)
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(data['weeks'])} weeks to {output_path}")
    print(f"Standings: {len(data['standings'])} teams")


def export_all_seasons():
    """Export current season and all available historical seasons."""
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    
    # Export current season (2025)
    print("=== Exporting 2025 (current season) ===")
    main()
    
    # Find and export all historical seasons
    previous_dir = project_dir / "previous_seasons"
    if previous_dir.exists():
        for excel_file in sorted(previous_dir.glob("*Scores.xlsx")):
            match = re.match(r'^(\d{4})\s+Scores\.xlsx$', excel_file.name)
            if match:
                season = int(match.group(1))
                print(f"\n=== Exporting {season} (historical) ===")
                export_historical(season)


if __name__ == "__main__":
    import sys
    
    if "--json" in sys.argv:
        main_json()
    elif "--all" in sys.argv:
        export_all_seasons()
    elif "--season" in sys.argv:
        try:
            idx = sys.argv.index("--season")
            season = int(sys.argv[idx + 1])
            if season == 2025:
                main()
            else:
                export_historical(season)
        except (IndexError, ValueError):
            print("Usage: python export_for_web.py --season YEAR")
            sys.exit(1)
    else:
        main()

