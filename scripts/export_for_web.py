#!/usr/bin/env python3
"""Export Excel scores to JSON for web display."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl


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
    
    # Group into matchups (teams are paired: 0v1, 2v3, etc.)
    for i in range(0, len(teams_data), 2):
        if i + 1 < len(teams_data):
            matchups.append({
                'team1': teams_data[i],
                'team2': teams_data[i + 1],
            })
    
    return {
        'week': week_num,
        'matchups': matchups,
        'teams': teams_data,
    }


def export_all_weeks(excel_path: str) -> dict[str, Any]:
    """Export all weeks from Excel to JSON format."""
    wb = openpyxl.load_workbook(excel_path)
    
    weeks = []
    standings = {}  # team_name -> {wins, losses, points_for, points_against}
    
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
        
        # Update standings
        for matchup in week_data['matchups']:
            t1, t2 = matchup['team1'], matchup['team2']
            
            for team in [t1, t2]:
                if team['name'] not in standings:
                    standings[team['name']] = {
                        'name': team['name'],
                        'owner': team['owner'],
                        'abbrev': team['abbrev'],
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'points_for': 0.0,
                        'points_against': 0.0,
                    }
            
            # Update records
            s1 = t1['total_score']
            s2 = t2['total_score']
            
            standings[t1['name']]['points_for'] += s1
            standings[t1['name']]['points_against'] += s2
            standings[t2['name']]['points_for'] += s2
            standings[t2['name']]['points_against'] += s1
            
            if s1 > s2:
                standings[t1['name']]['wins'] += 1
                standings[t2['name']]['losses'] += 1
            elif s2 > s1:
                standings[t2['name']]['wins'] += 1
                standings[t1['name']]['losses'] += 1
            else:
                standings[t1['name']]['ties'] += 1
                standings[t2['name']]['ties'] += 1
    
    # Sort standings by wins, then points for
    sorted_standings = sorted(
        standings.values(),
        key=lambda x: (x['wins'], x['points_for']),
        reverse=True
    )
    
    wb.close()
    
    return {
        'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'season': 2025,
        'current_week': weeks[-1]['week'] if weeks else 1,
        'weeks': weeks,
        'standings': sorted_standings,
    }


def main():
    """Main export function."""
    # Get paths relative to script location
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    excel_path = project_dir / "2025 Scores.xlsx"
    output_path = project_dir / "web" / "data.json"
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Exporting {excel_path} to {output_path}...")
    
    data = export_all_weeks(str(excel_path))
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(data['weeks'])} weeks")
    print(f"Standings: {len(data['standings'])} teams")
    print(f"Updated at: {data['updated_at']}")


if __name__ == "__main__":
    main()

