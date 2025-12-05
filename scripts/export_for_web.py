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

def get_schedule_data() -> list[dict]:
    """Convert schedule to JSON format with team codes."""
    schedule_data = []
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

TEAM_COLUMNS = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def parse_player_name(cell_value: str) -> tuple[str, str]:
    """Parse 'Player Name (TEAM)' into (name, team)."""
    if not cell_value:
        return "", ""
    match = re.match(r'^(.+?)\s*\(([A-Z]{2,3})\)$', cell_value.strip())
    if match:
        return match.group(1).strip(), match.group(2)
    return cell_value.strip(), ""


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
        
        teams_data.append({
            'name': team_name,
            'owner': owner,
            'abbrev': abbrev,
            'roster': roster,
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


def export_all_weeks(excel_path: str) -> dict[str, Any]:
    """Export all weeks from Excel to JSON format."""
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    
    weeks = []
    # Use team code (abbrev) as unique identifier
    standings = {}  # abbrev -> {rank_points, wins, losses, ties, points_for, points_against, ...}
    
    # Find all week sheets
    week_sheets = []
    for sheet_name in wb.sheetnames:
        match = re.match(r'^Week (\d+)$', sheet_name)
        if match:
            week_sheets.append((int(match.group(1)), sheet_name))
    
    # Sort by week number
    week_sheets.sort(key=lambda x: x[0])
    
    # Export all weeks first
    for week_num, sheet_name in week_sheets:
        ws = wb[sheet_name]
        
        # Calculate bench scores for weeks with data
        bench_scores = calculate_bench_scores(excel_path, sheet_name, week_num)
        if bench_scores:
            print(f"  Calculated {len(bench_scores)} bench scores for Week {week_num}")
        
        week_data = export_week(ws, week_num, bench_scores)
        weeks.append(week_data)
    
    # Determine which weeks to include in standings
    # Only include completed weeks (before current NFL week)
    current_nfl_week = get_current_nfl_week()
    
    print(f"Current NFL week: {current_nfl_week}, standings include weeks 1-{current_nfl_week - 1}")
    
    for week_data in weeks:
        # Skip weeks without scores for standings calculation
        if not week_data.get('has_scores', False):
            continue
        
        # Only include completed weeks (before current NFL week)
        if week_data['week'] >= current_nfl_week:
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
    
    # Sort standings by rank points, then points for
    sorted_standings = sorted(
        standings.values(),
        key=lambda x: (x['rank_points'], x['points_for']),
        reverse=True
    )
    
    wb.close()
    
    # Use nflreadpy's current week for schedule highlighting and matchup default
    current_week = get_current_nfl_week()
    
    return {
        'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'season': 2025,
        'current_week': current_week,
        'weeks': weeks,
        'standings': sorted_standings,
        'schedule': get_schedule_data(),
    }


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
        data['transactions'] = parse_transactions(str(transactions_path))
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(data['weeks'])} weeks")
    print(f"Standings: {len(data['standings'])} teams")
    print(f"Updated at: {data['updated_at']}")


if __name__ == "__main__":
    main()

