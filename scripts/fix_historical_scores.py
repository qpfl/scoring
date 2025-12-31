#!/usr/bin/env python3
"""
Fix scores in web/data_XXXX.json files from the authoritative Excel sources.

This script ONLY updates scores - it preserves all other data like banners,
transactions, constitution, etc.

Usage:
    python scripts/fix_historical_scores.py 2024
    python scripts/fix_historical_scores.py --all
"""

import json
import sys
from pathlib import Path


def load_correct_scores(historical_path: Path) -> dict:
    """Load scores from historical JSON file."""
    with open(historical_path) as f:
        data = json.load(f)
    
    # Build a map of week -> team -> score
    scores = {}
    for week in data.get('weeks', []):
        week_num = week['week']
        scores[week_num] = {}
        
        for team in week.get('teams', []):
            abbrev = team['abbrev']
            scores[week_num][abbrev] = {
                'total_score': team.get('total_score', 0),
                'roster': team.get('roster', []),
            }
    
    return scores


def fix_data_file(data_file: Path, correct_scores: dict) -> int:
    """Fix scores in a data file. Returns number of fixes made."""
    with open(data_file) as f:
        data = json.load(f)
    
    fixes = 0
    
    for week in data.get('weeks', []):
        week_num = week['week']
        if week_num not in correct_scores:
            continue
        
        week_correct = correct_scores[week_num]
        
        # Fix matchups
        for matchup in week.get('matchups', []):
            for team_key in ['team1', 'team2']:
                team = matchup.get(team_key, {})
                abbrev = team.get('abbrev')
                
                if abbrev in week_correct:
                    correct = week_correct[abbrev]
                    old_score = team.get('total_score', 0)
                    new_score = correct['total_score']
                    
                    if old_score != new_score:
                        print(f"  Week {week_num}, {abbrev}: {old_score} -> {new_score}")
                        team['total_score'] = new_score
                        fixes += 1
                    
                    # Also fix roster scores if available
                    if correct.get('roster'):
                        correct_roster_scores = {
                            p['name']: p['score'] 
                            for p in correct['roster']
                        }
                        for player in team.get('roster', []):
                            if player['name'] in correct_roster_scores:
                                old_player_score = player.get('score', 0)
                                new_player_score = correct_roster_scores[player['name']]
                                if old_player_score != new_player_score:
                                    player['score'] = new_player_score
                                    fixes += 1
        
        # Fix teams array if present
        for team in week.get('teams', []):
            abbrev = team.get('abbrev')
            if abbrev in week_correct:
                old_score = team.get('total_score', 0)
                new_score = week_correct[abbrev]['total_score']
                if old_score != new_score:
                    team['total_score'] = new_score
                    fixes += 1
    
    # Write updated file
    with open(data_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    return fixes


def fix_season(season: int) -> None:
    """Fix scores for a single season."""
    historical_file = Path(f'web/data/historical/{season}.json')
    data_file = Path(f'web/data_{season}.json')
    
    if not historical_file.exists():
        print(f"ERROR: Historical file not found: {historical_file}")
        print("  Run: python scripts/export_historical.py {season}")
        return
    
    if not data_file.exists():
        print(f"ERROR: Data file not found: {data_file}")
        return
    
    print(f"Fixing {season} scores...")
    
    correct_scores = load_correct_scores(historical_file)
    fixes = fix_data_file(data_file, correct_scores)
    
    print(f"  Made {fixes} corrections")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/fix_historical_scores.py <year> | --all")
        sys.exit(1)
    
    if sys.argv[1] == '--all':
        for season in range(2020, 2025):
            fix_season(season)
    else:
        try:
            season = int(sys.argv[1])
            fix_season(season)
        except ValueError:
            print(f"Invalid season: {sys.argv[1]}")
            sys.exit(1)


if __name__ == '__main__':
    main()

