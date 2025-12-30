"""Schedule parsing and playoff structure for QPFL.

Starting in 2026:
- Weeks 1-15: Regular season matchups from schedule.txt
- Week 16: Playoff round 1
  - 1 seed vs 4 seed (playoffs - affects standings)
  - 2 seed vs 3 seed (playoffs - affects standings)
  - 5 seed vs 6 seed (mid bowl - no standings impact, cumulative over weeks 16-17)
  - 7 seed vs 10 seed (sewer series - no standings impact)
  - 8 seed vs 9 seed (sewer series - no standings impact)
- Week 17: Finals
  - Championship: Winners of 1v4 and 2v3 (1st/2nd place)
  - Consolation Cup: Losers of 1v4 and 2v3 (3rd/4th place)
  - Mid Bowl: Same 5v6 teams, cumulative score from weeks 16-17 (5th/6th place)
  - Toilet Bowl: Losers of sewer series matchups (9th/10th place - loser is Toilet Bowl loser)
  - 7th Place Game: Winners of sewer series matchups (7th/8th place)
"""

import re
from pathlib import Path
from typing import Optional


# Playoff structure for 2026+
PLAYOFF_STRUCTURE_2026 = {
    16: {
        'round': 'Semifinals',
        'matchups': [
            {'seed1': 1, 'seed2': 4, 'bracket': 'playoffs', 'game': 'semi_1', 'affects_standings': True},
            {'seed1': 2, 'seed2': 3, 'bracket': 'playoffs', 'game': 'semi_2', 'affects_standings': True},
            {'seed1': 5, 'seed2': 6, 'bracket': 'mid_bowl', 'game': 'mid_bowl_1', 'two_week': True, 'affects_standings': False},
            {'seed1': 7, 'seed2': 10, 'bracket': 'sewer_series', 'game': 'sewer_1', 'affects_standings': False},
            {'seed1': 8, 'seed2': 9, 'bracket': 'sewer_series', 'game': 'sewer_2', 'affects_standings': False},
        ]
    },
    17: {
        'round': 'Finals',
        'matchups': [
            {'from_games': ['semi_1', 'semi_2'], 'take': 'winners', 'bracket': 'championship', 'game': 'championship', 'determines': [1, 2]},
            {'from_games': ['semi_1', 'semi_2'], 'take': 'losers', 'bracket': 'consolation_cup', 'game': 'consolation_cup', 'determines': [3, 4]},
            {'seed1': 5, 'seed2': 6, 'bracket': 'mid_bowl', 'game': 'mid_bowl_2', 'two_week': True, 'cumulative_with': 'mid_bowl_1', 'determines': [5, 6]},
            {'from_games': ['sewer_1', 'sewer_2'], 'take': 'losers', 'bracket': 'toilet_bowl', 'game': 'toilet_bowl', 'determines': [9, 10]},
            {'from_games': ['sewer_1', 'sewer_2'], 'take': 'winners', 'bracket': '7th_place', 'game': '7th_place', 'determines': [7, 8]},
        ]
    }
}


def parse_schedule_file(schedule_path: str | Path) -> list[list[tuple[str, str]]]:
    """Parse schedule.txt file into weekly matchups.
    
    Supports format:
        Week 1: GSA versus S/T, RPA versus CWR, CGK versus AYP
        Rivalry Week 5: GSA versus RPA, CWR versus CGK
    
    Args:
        schedule_path: Path to schedule.txt file
        
    Returns:
        List of 15 weeks, each containing list of (team1, team2) tuples
    """
    schedule_path = Path(schedule_path)
    if not schedule_path.exists():
        raise FileNotFoundError(f"Schedule file not found: {schedule_path}")
    
    with open(schedule_path) as f:
        content = f.read()
    
    weeks = []
    
    for line in content.split('\n'):
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue
        
        # Parse line format: "Week N: matchups" or "Rivalry Week N: matchups"
        # Match "Week N:" or "Rivalry Week N:" etc.
        week_match = re.match(r'^(?:Rivalry\s+)?Week\s+(\d+)\s*:\s*(.+)$', line, re.IGNORECASE)
        if week_match:
            week_num = int(week_match.group(1))
            matchups_str = week_match.group(2)
            
            # Parse comma-separated matchups: "Team1 versus Team2, Team3 versus Team4"
            matchups = []
            for matchup in matchups_str.split(','):
                matchup = matchup.strip()
                # Match "Team1 versus Team2" or "Team1 vs Team2"
                teams_match = re.match(r'^([A-Z/]+)\s+(?:versus|vs)\s+([A-Z/]+)$', matchup, re.IGNORECASE)
                if teams_match:
                    team1 = teams_match.group(1).upper()
                    team2 = teams_match.group(2).upper()
                    matchups.append((team1, team2))
            
            # Ensure weeks list is long enough
            while len(weeks) < week_num:
                weeks.append([])
            
            # Store matchups (week_num is 1-indexed, list is 0-indexed)
            weeks[week_num - 1] = matchups
    
    return weeks


def get_regular_season_schedule(schedule_path: str | Path) -> list[dict]:
    """Get regular season schedule in JSON format.
    
    Args:
        schedule_path: Path to schedule.txt file
        
    Returns:
        List of week objects with matchups
    """
    weeks = parse_schedule_file(schedule_path)
    rivalry_weeks = detect_rivalry_weeks(schedule_path)
    schedule_data = []
    
    for week_num, matchups in enumerate(weeks, 1):
        week_matchups = []
        for team1, team2 in matchups:
            week_matchups.append({
                'team1': team1,
                'team2': team2,
            })
        
        schedule_data.append({
            'week': week_num,
            'is_rivalry': week_num in rivalry_weeks,
            'is_playoffs': False,
            'matchups': week_matchups,
        })
    
    return schedule_data


def detect_rivalry_weeks(schedule_path: str | Path) -> set[int]:
    """Detect which weeks are rivalry weeks from the schedule file.
    
    Args:
        schedule_path: Path to schedule.txt file
        
    Returns:
        Set of week numbers that are rivalry weeks
    """
    schedule_path = Path(schedule_path)
    if not schedule_path.exists():
        return set()
    
    rivalry_weeks = set()
    
    with open(schedule_path) as f:
        for line in f:
            line = line.strip()
            # Check for "Rivalry Week N:"
            match = re.match(r'^Rivalry\s+Week\s+(\d+)\s*:', line, re.IGNORECASE)
            if match:
                rivalry_weeks.add(int(match.group(1)))
    
    return rivalry_weeks


def get_playoff_schedule(standings: list[dict], season: int = 2026) -> list[dict]:
    """Generate playoff schedule based on standings.
    
    Args:
        standings: List of team standings (sorted by seed)
        season: Season year (affects playoff structure)
        
    Returns:
        List of week 16-17 schedule objects
    """
    if season < 2026:
        # Use legacy playoff structure for older seasons
        from .export_season import PLAYOFF_STRUCTURE
        playoff_structure = PLAYOFF_STRUCTURE
    else:
        playoff_structure = PLAYOFF_STRUCTURE_2026
    
    seed_to_team = {i + 1: team['abbrev'] for i, team in enumerate(standings)}
    schedule_data = []
    
    for week_num in [16, 17]:
        playoff_info = playoff_structure[week_num]
        week_matchups = []
        
        for game in playoff_info['matchups']:
            matchup = {
                'bracket': game['bracket'],
                'game': game['game'],
            }
            
            if 'seed1' in game:
                matchup['team1'] = seed_to_team.get(game['seed1'], 'TBD')
                matchup['team2'] = seed_to_team.get(game['seed2'], 'TBD')
                matchup['seed1'] = game['seed1']
                matchup['seed2'] = game['seed2']
            else:
                matchup['team1'] = 'TBD'
                matchup['team2'] = 'TBD'
                matchup['from_games'] = game.get('from_games', [])
                matchup['take'] = game.get('take', '')
            
            if game.get('two_week'):
                matchup['two_week'] = True
            if game.get('cumulative_with'):
                matchup['cumulative_with'] = game['cumulative_with']
            if game.get('determines'):
                matchup['determines'] = game['determines']
            if game.get('affects_standings') is not None:
                matchup['affects_standings'] = game['affects_standings']
            
            week_matchups.append(matchup)
        
        schedule_data.append({
            'week': week_num,
            'is_rivalry': False,
            'is_playoffs': True,
            'playoff_round': playoff_info['round'],
            'matchups': week_matchups,
        })
    
    return schedule_data


def get_full_schedule(schedule_path: str | Path, standings: list[dict] = None, season: int = 2026) -> list[dict]:
    """Get complete season schedule including playoffs.
    
    Args:
        schedule_path: Path to schedule.txt file
        standings: List of team standings (needed for playoff seeding)
        season: Season year
        
    Returns:
        List of all week schedule objects (weeks 1-17)
    """
    # Get regular season from schedule.txt
    schedule = get_regular_season_schedule(schedule_path)
    
    # Add playoff weeks if standings available
    if standings:
        playoff_weeks = get_playoff_schedule(standings, season)
        schedule.extend(playoff_weeks)
    
    return schedule


def resolve_playoff_matchups(week_16_results: dict, week_17_results: dict = None) -> dict:
    """Resolve playoff matchups based on week 16 results.
    
    Args:
        week_16_results: Dict mapping game name to (winner_abbrev, loser_abbrev, scores)
        week_17_results: Optional dict for week 17 results
        
    Returns:
        Dict with final standings positions for each team
    """
    final_standings = {}
    
    # Week 16 games determine week 17 matchups
    if 'semi_1' in week_16_results and 'semi_2' in week_16_results:
        semi_1 = week_16_results['semi_1']
        semi_2 = week_16_results['semi_2']
        
        # Championship: winners of semi games
        champ_teams = [semi_1['winner'], semi_2['winner']]
        # Consolation: losers of semi games
        consolation_teams = [semi_1['loser'], semi_2['loser']]
        
        # If we have week 17 results, determine final positions
        if week_17_results:
            if 'championship' in week_17_results:
                champ = week_17_results['championship']
                final_standings[champ['winner']] = 1
                final_standings[champ['loser']] = 2
            
            if 'consolation_cup' in week_17_results:
                consolation = week_17_results['consolation_cup']
                final_standings[consolation['winner']] = 3
                final_standings[consolation['loser']] = 4
    
    # Mid bowl: cumulative scores from weeks 16-17
    if 'mid_bowl_1' in week_16_results and week_17_results and 'mid_bowl_2' in week_17_results:
        mb1 = week_16_results['mid_bowl_1']
        mb2 = week_17_results['mid_bowl_2']
        
        # Calculate cumulative scores
        team1 = mb1['team1']
        team2 = mb1['team2']
        team1_total = mb1['team1_score'] + mb2.get('team1_score', 0)
        team2_total = mb1['team2_score'] + mb2.get('team2_score', 0)
        
        if team1_total > team2_total:
            final_standings[team1] = 5
            final_standings[team2] = 6
        else:
            final_standings[team2] = 5
            final_standings[team1] = 6
    
    # Sewer series -> toilet bowl and 7th place
    if 'sewer_1' in week_16_results and 'sewer_2' in week_16_results:
        sewer_1 = week_16_results['sewer_1']
        sewer_2 = week_16_results['sewer_2']
        
        if week_17_results:
            # 7th place: winners of sewer series
            if '7th_place' in week_17_results:
                seventh = week_17_results['7th_place']
                final_standings[seventh['winner']] = 7
                final_standings[seventh['loser']] = 8
            
            # Toilet bowl: losers of sewer series (loser of this game is 10th)
            if 'toilet_bowl' in week_17_results:
                toilet = week_17_results['toilet_bowl']
                final_standings[toilet['winner']] = 9
                final_standings[toilet['loser']] = 10
    
    return final_standings

