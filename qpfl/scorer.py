"""Main scoring engine that ties everything together."""

from typing import Dict, List, Tuple

from .models import PlayerScore, FantasyTeam
from .data_fetcher import NFLDataFetcher
from .scoring import (
    score_skill_player,
    score_kicker,
    score_defense,
    score_head_coach,
    score_offensive_line,
)


class QPFLScorer:
    """Main scoring engine for QPFL fantasy football."""
    
    def __init__(self, season: int, week: int):
        self.season = season
        self.week = week
        self.data = NFLDataFetcher(season, week)
    
    def score_player(self, name: str, team: str, position: str) -> PlayerScore:
        """Score a single player."""
        result = PlayerScore(name=name, position=position, team=team)
        
        if position in ('QB', 'RB', 'WR', 'TE'):
            stats = self.data.find_player(name, team, position)
            if stats:
                result.found_in_stats = True
                # Get turnover-TD data (pick 6s, fumble 6s)
                player_id = stats.get('player_id')
                turnover_tds = {}
                if player_id:
                    turnover_tds = self.data.get_turnovers_returned_for_td(player_id)
                result.total_points, result.breakdown = score_skill_player(stats, turnover_tds)
        
        elif position == 'K':
            stats = self.data.find_player(name, team, position)
            if stats:
                result.found_in_stats = True
                result.total_points, result.breakdown = score_kicker(stats)
        
        elif position == 'D/ST':
            team_stats = self.data.get_team_stats(team)
            opponent_stats = self.data.get_opponent_stats(team)
            game_info = self.data.get_game_info(team)
            
            if team_stats and game_info:
                result.found_in_stats = True
                result.total_points, result.breakdown = score_defense(
                    team_stats, opponent_stats or {}, game_info
                )
        
        elif position == 'HC':
            game_info = self.data.get_game_info(team)
            if game_info:
                result.found_in_stats = True
                result.total_points, result.breakdown = score_head_coach(game_info)
        
        elif position == 'OL':
            team_stats = self.data.get_team_stats(team)
            if team_stats:
                result.found_in_stats = True
                result.total_points, result.breakdown = score_offensive_line(team_stats)
        
        return result
    
    def score_fantasy_team(self, team: FantasyTeam) -> Dict[str, List[PlayerScore]]:
        """Score all started players on a fantasy team."""
        results = {}
        
        for position, players in team.players.items():
            results[position] = []
            
            for player_name, nfl_team, is_started in players:
                if is_started:
                    score = self.score_player(player_name, nfl_team, position)
                    results[position].append(score)
        
        return results
    
    @staticmethod
    def calculate_team_total(scores: Dict[str, List[PlayerScore]]) -> float:
        """Calculate total score for a fantasy team."""
        total = 0.0
        for position_scores in scores.values():
            for score in position_scores:
                total += score.total_points
        return total


def score_week(
    excel_path: str,
    sheet_name: str,
    season: int,
    week: int,
    verbose: bool = True,
) -> Tuple[List[FantasyTeam], Dict[str, Tuple[float, Dict[str, List[PlayerScore]]]]]:
    """
    Score all fantasy teams for a given week.
    
    Returns:
        Tuple of (teams, results) where results maps team name to (total_score, position_scores)
    """
    from .excel_parser import parse_roster_from_excel
    
    teams = parse_roster_from_excel(excel_path, sheet_name)
    
    if verbose:
        print(f"\nFound {len(teams)} fantasy teams")
        for team in teams:
            started_count = sum(
                1 for players in team.players.values()
                for _, _, is_started in players if is_started
            )
            print(f"  - {team.name} ({team.abbreviation}): {started_count} started players")
    
    scorer = QPFLScorer(season, week)
    results = {}
    
    for team in teams:
        if verbose:
            print(f"\n{'='*60}")
            print(f"Scoring: {team.name}")
            print('='*60)
        
        scores = scorer.score_fantasy_team(team)
        total = scorer.calculate_team_total(scores)
        
        if verbose:
            for position, player_scores in scores.items():
                for ps in player_scores:
                    status = "✓" if ps.found_in_stats else "✗"
                    print(f"  {position} {ps.name} ({ps.team}): {ps.total_points:.1f} pts {status}")
                    if ps.breakdown:
                        for key, val in ps.breakdown.items():
                            print(f"      {key}: {val}")
            
            print(f"\n  TOTAL: {total:.1f} points")
        
        results[team.name] = (total, scores)
    
    return teams, results

