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
                player_id = stats.get('player_id')
                turnover_tds = {}
                extra_fumbles = 0
                if player_id:
                    # Get turnover-TD data (pick 6s, fumble 6s)
                    turnover_tds = self.data.get_turnovers_returned_for_td(player_id)
                    # Get fumbles from PBP not in player stats (e.g., lateral fumbles)
                    extra_fumbles = self.data.get_extra_fumbles_lost(player_id, stats)
                result.total_points, result.breakdown = score_skill_player(stats, turnover_tds, extra_fumbles)
        
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
                # Get sack counts from both sources
                sack_info = self.data.get_defensive_sacks(team)
                if sack_info['discrepancy']:
                    result.data_notes.append(
                        f"Sack discrepancy: aggregated={sack_info['aggregated']}, PBP={sack_info['pbp']} (using PBP)"
                    )
                result.total_points, result.breakdown = score_defense(
                    team_stats, opponent_stats or {}, game_info, sack_info['value']
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
                # Get OL touchdowns from play-by-play
                ol_tds = self.data.get_ol_touchdowns(team)
                result.total_points, result.breakdown = score_offensive_line(team_stats, ol_tds)
        
        return result
    
    def score_fantasy_team(self, team: FantasyTeam, starters_only: bool = False) -> Dict[str, List[Tuple[PlayerScore, bool]]]:
        """Score players on a fantasy team.
        
        Args:
            team: The fantasy team to score
            starters_only: If True, only score starters. If False, score all players.
            
        Returns:
            Dict mapping position to list of (PlayerScore, is_starter) tuples
        """
        results = {}
        
        for position, players in team.players.items():
            results[position] = []
            
            for player_name, nfl_team, is_started in players:
                if starters_only and not is_started:
                    continue
                score = self.score_player(player_name, nfl_team, position)
                results[position].append((score, is_started))
        
        return results
    
    @staticmethod
    def calculate_team_total(scores: Dict[str, List[Tuple[PlayerScore, bool]]]) -> float:
        """Calculate total score for a fantasy team (starters only)."""
        total = 0.0
        for position_scores in scores.values():
            for score, is_starter in position_scores:
                if is_starter:
                    total += score.total_points
        return total


def score_week(
    excel_path: str,
    sheet_name: str,
    season: int,
    week: int,
    verbose: bool = True,
) -> Tuple[List[FantasyTeam], Dict[str, Tuple[float, Dict[str, List[Tuple[PlayerScore, bool]]]]]]:
    """
    Score all fantasy teams for a given week.
    
    Returns:
        Tuple of (teams, results) where results maps team name to (total_score, position_scores)
        position_scores is Dict[position, List[(PlayerScore, is_starter)]]
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
        
        scores = scorer.score_fantasy_team(team)  # Now scores all players
        total = scorer.calculate_team_total(scores)  # Only counts starters
        
        if verbose:
            for position, player_scores in scores.items():
                for ps, is_starter in player_scores:
                    status = "✓" if ps.found_in_stats else "✗"
                    starter_mark = "" if is_starter else " [BENCH]"
                    print(f"  {position} {ps.name} ({ps.team}): {ps.total_points:.1f} pts {status}{starter_mark}")
                    if ps.breakdown and is_starter:
                        for key, val in ps.breakdown.items():
                            print(f"      {key}: {val}")
                    if ps.data_notes:
                        for note in ps.data_notes:
                            print(f"      ⚠️  {note}")
            
            print(f"\n  TOTAL: {total:.1f} points")
        
        results[team.name] = (total, scores)
    
    return teams, results

