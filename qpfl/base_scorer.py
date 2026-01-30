"""Base scoring engine with shared logic for both Excel and JSON scorers."""

from .data_fetcher import NFLDataFetcher
from .models import FantasyTeam, PlayerScore
from .scoring import (
    score_defense,
    score_head_coach,
    score_kicker,
    score_offensive_line,
    score_skill_player,
)


class BaseScorer:
    """
    Base class for QPFL scoring engines.

    Provides shared scoring logic that works regardless of data source
    (Excel or JSON). Subclasses implement data loading methods.
    """

    def __init__(self, season: int, week: int):
        """
        Initialize scorer.

        Args:
            season: NFL season year
            week: Week number (1-17)
        """
        self.season = season
        self.week = week
        self.data = NFLDataFetcher(season, week)

    def score_player(self, name: str, team: str, position: str) -> PlayerScore:
        """
        Score a single player.

        Args:
            name: Player name
            team: NFL team abbreviation
            position: Position code (QB, RB, WR, TE, K, D/ST, HC, OL)

        Returns:
            PlayerScore object with points and breakdown
        """
        result = PlayerScore(name=name, position=position, team=team)

        if position in ('QB', 'RB', 'WR', 'TE'):
            stats = self.data.find_player(name, team, position)
            if stats:
                result.found_in_stats = True
                player_id = stats.get('player_id')
                turnover_tds = {}
                extra_fumbles = 0
                if player_id:
                    turnover_tds = self.data.get_turnovers_returned_for_td(player_id)
                    extra_fumbles = self.data.get_extra_fumbles_lost(player_id, stats)
                result.total_points, result.breakdown = score_skill_player(
                    stats, turnover_tds, extra_fumbles
                )

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
                sack_info = self.data.get_defensive_sacks(team)
                if sack_info['discrepancy']:
                    result.data_notes.append(
                        f'Sack discrepancy: aggregated={sack_info["aggregated"]}, '
                        f'PBP={sack_info["pbp"]} (using PBP)'
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
                ol_tds = self.data.get_ol_touchdowns(team)
                result.total_points, result.breakdown = score_offensive_line(team_stats, ol_tds)

        return result

    def score_fantasy_team(
        self, team: FantasyTeam, starters_only: bool = False
    ) -> dict[str, list[tuple[PlayerScore, bool]]]:
        """
        Score all players on a fantasy team.

        Args:
            team: FantasyTeam object
            starters_only: If True, only score starters

        Returns:
            Dict mapping position to list of (PlayerScore, is_starter) tuples
        """
        results: dict[str, list[tuple[PlayerScore, bool]]] = {}

        for position, players in team.players.items():
            results[position] = []

            for player_name, nfl_team, is_started in players:
                if starters_only and not is_started:
                    continue
                score = self.score_player(player_name, nfl_team, position)
                results[position].append((score, is_started))

        return results

    def calculate_team_total(self, scores: dict[str, list[tuple[PlayerScore, bool]]]) -> float:
        """
        Calculate total fantasy points for a team (starters only).

        Args:
            scores: Position scores from score_fantasy_team()

        Returns:
            Total points (sum of starters only)
        """
        total = 0.0
        for position_scores in scores.values():
            for player_score, is_starter in position_scores:
                if is_starter:
                    total += player_score.total_points
        return total

    def score_teams(
        self, teams: list[FantasyTeam], verbose: bool = True
    ) -> dict[str, tuple[float, dict[str, list[tuple[PlayerScore, bool]]]]]:
        """
        Score multiple fantasy teams.

        This is the shared logic for scoring a full week, regardless of
        whether teams came from Excel or JSON.

        Args:
            teams: List of FantasyTeam objects to score
            verbose: Whether to print detailed output

        Returns:
            Dict mapping team name to (total_score, position_scores)
        """
        if verbose:
            print(f'\nFound {len(teams)} fantasy teams')
            for team in teams:
                started_count = sum(
                    1
                    for players in team.players.values()
                    for _, _, is_started in players
                    if is_started
                )
                print(f'  - {team.name} ({team.abbreviation}): {started_count} started players')

        results = {}

        for team in teams:
            if verbose:
                print(f'\n{"=" * 60}')
                print(f'Scoring: {team.name}')
                print('=' * 60)

            scores = self.score_fantasy_team(team)
            total = self.calculate_team_total(scores)

            if verbose:
                for position, player_scores in scores.items():
                    for ps, is_starter in player_scores:
                        status = '✓' if ps.found_in_stats else '✗'
                        starter_mark = '' if is_starter else ' [BENCH]'
                        print(
                            f'  {position} {ps.name} ({ps.team}): '
                            f'{ps.total_points:.1f} pts {status}{starter_mark}'
                        )
                        if ps.breakdown and is_starter:
                            for key, val in ps.breakdown.items():
                                print(f'      {key}: {val}')
                        if ps.data_notes:
                            for note in ps.data_notes:
                                print(f'      ⚠️  {note}')

                print(f'\n  TOTAL: {total:.1f} points')

            results[team.name] = (total, scores)

        return results
