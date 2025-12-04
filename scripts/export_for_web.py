#!/usr/bin/env python3
"""Export Excel scores to JSON for web display."""

import json
import re
import zipfile
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def export_week(ws, week_num: int) -> dict[str, Any]:
    """Export a single week's data to dict format."""
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
                    score = float(score_cell.value) if score_cell.value else 0.0
                    
                    roster.append({
                        'name': player_name,
                        'nfl_team': nfl_team,
                        'position': position,
                        'score': score,
                        'starter': is_starter,
                    })
                    
                    if is_starter:
                        total_score += score
        
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
    
    for week_num, sheet_name in week_sheets:
        ws = wb[sheet_name]
        week_data = export_week(ws, week_num)
        weeks.append(week_data)
        
        # Skip weeks without scores for standings calculation
        if not week_data.get('has_scores', False):
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
    
    return {
        'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'season': 2025,
        'current_week': weeks[-1]['week'] if weeks else 1,
        'weeks': weeks,
        'standings': sorted_standings,
        'schedule': get_schedule_data(),
    }


def parse_constitution(doc_path: str) -> list[dict]:
    """Parse constitution document into structured sections."""
    docx = get_docx_module()
    if not docx:
        return []
    
    doc = docx.Document(doc_path)
    sections = []
    current_article = None
    current_section = None
    
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
            # Normal content
            if current_section:
                current_section['content'].append({'type': 'text', 'text': text})
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
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(data['weeks'])} weeks")
    print(f"Standings: {len(data['standings'])} teams")
    print(f"Updated at: {data['updated_at']}")


if __name__ == "__main__":
    main()

