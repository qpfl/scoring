"""Integration tests for end-to-end workflows."""

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from qpfl.base_scorer import BaseScorer
from qpfl.json_scorer import (
    build_fantasy_team_from_json,
    load_lineup,
    load_rosters,
    score_week_from_json,
)
from qpfl.models import FantasyTeam
from qpfl.validators import validate_all_scores, validate_roster


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directory with test files."""
    data_dir = tmp_path / 'data'
    data_dir.mkdir()

    # Create test rosters.json
    rosters = {
        'GSA': [
            {'name': 'Patrick Mahomes', 'nfl_team': 'KC', 'position': 'QB', 'taxi': False},
            {'name': 'Derrick Henry', 'nfl_team': 'BAL', 'position': 'RB', 'taxi': False},
            {'name': 'Saquon Barkley', 'nfl_team': 'PHI', 'position': 'RB', 'taxi': False},
            {'name': 'Justin Jefferson', 'nfl_team': 'MIN', 'position': 'WR', 'taxi': False},
            {'name': 'Tyreek Hill', 'nfl_team': 'MIA', 'position': 'WR', 'taxi': False},
            {'name': 'CeeDee Lamb', 'nfl_team': 'DAL', 'position': 'WR', 'taxi': False},
            {'name': 'Travis Kelce', 'nfl_team': 'KC', 'position': 'TE', 'taxi': False},
            {'name': 'Justin Tucker', 'nfl_team': 'BAL', 'position': 'K', 'taxi': False},
            {'name': 'Chiefs D/ST', 'nfl_team': 'KC', 'position': 'D/ST', 'taxi': False},
            {'name': 'Andy Reid', 'nfl_team': 'KC', 'position': 'HC', 'taxi': False},
            {'name': 'Chiefs OL', 'nfl_team': 'KC', 'position': 'OL', 'taxi': False},
        ],
        'CGK': [
            {'name': 'Josh Allen', 'nfl_team': 'BUF', 'position': 'QB', 'taxi': False},
            {'name': 'Christian McCaffrey', 'nfl_team': 'SF', 'position': 'RB', 'taxi': False},
            {'name': 'Breece Hall', 'nfl_team': 'NYJ', 'position': 'RB', 'taxi': False},
            {'name': 'Amon-Ra St. Brown', 'nfl_team': 'DET', 'position': 'WR', 'taxi': False},
            {'name': 'Garrett Wilson', 'nfl_team': 'NYJ', 'position': 'WR', 'taxi': False},
            {'name': 'Puka Nacua', 'nfl_team': 'LAR', 'position': 'WR', 'taxi': False},
            {'name': 'Trey McBride', 'nfl_team': 'ARI', 'position': 'TE', 'taxi': False},
            {'name': 'Harrison Butker', 'nfl_team': 'KC', 'position': 'K', 'taxi': False},
            {'name': '49ers D/ST', 'nfl_team': 'SF', 'position': 'D/ST', 'taxi': False},
            {'name': 'Kyle Shanahan', 'nfl_team': 'SF', 'position': 'HC', 'taxi': False},
            {'name': '49ers OL', 'nfl_team': 'SF', 'position': 'OL', 'taxi': False},
        ],
    }
    rosters_path = data_dir / 'rosters.json'
    with open(rosters_path, 'w') as f:
        json.dump(rosters, f, indent=2)

    # Create test lineups directory and file
    lineups_dir = data_dir / 'lineups' / '2025'
    lineups_dir.mkdir(parents=True)

    lineups = {
        'week': 1,
        'lineups': {
            'GSA': {
                'QB': ['Patrick Mahomes'],
                'RB': ['Derrick Henry', 'Saquon Barkley'],
                'WR': ['Justin Jefferson', 'Tyreek Hill', 'CeeDee Lamb'],
                'TE': ['Travis Kelce'],
                'K': ['Justin Tucker'],
                'D/ST': ['Chiefs D/ST'],
                'HC': ['Andy Reid'],
                'OL': ['Chiefs OL'],
            },
            'CGK': {
                'QB': ['Josh Allen'],
                'RB': ['Christian McCaffrey', 'Breece Hall'],
                'WR': ['Amon-Ra St. Brown', 'Garrett Wilson', 'Puka Nacua'],
                'TE': ['Trey McBride'],
                'K': ['Harrison Butker'],
                'D/ST': ['49ers D/ST'],
                'HC': ['Kyle Shanahan'],
                'OL': ['49ers OL'],
            },
        },
    }
    lineup_path = lineups_dir / 'week_1.json'
    with open(lineup_path, 'w') as f:
        json.dump(lineups, f, indent=2)

    return data_dir


@pytest.fixture
def mock_nfl_data():
    """Mock NFL stats data for testing."""
    return {
        'player_stats': {
            'Patrick Mahomes': {
                'player_id': 'mahomes_pat',
                'passing_yards': 300,
                'passing_tds': 3,
                'passing_interceptions': 1,
                'rushing_yards': 20,
            },
            'Derrick Henry': {
                'player_id': 'henry_der',
                'rushing_yards': 150,
                'rushing_tds': 2,
                'receiving_yards': 20,
            },
            'Justin Tucker': {
                'player_id': 'tucker_jus',
                'pat_made': 4,
                'fg_made_40_49': 2,
            },
        },
        'team_stats': {
            'KC': {
                'def_interceptions': 2,
                'def_sacks': 4,
                'passing_yards': 280,
                'rushing_yards': 150,
                'sacks_suffered': 2,
            },
        },
        'game_info': {
            'KC': {
                'team_score': 31,
                'opponent_score': 20,
                'points_allowed': 20,
            },
        },
    }


class TestFullWeekScoring:
    """Integration tests for complete week scoring workflow."""

    def test_load_rosters(self, temp_data_dir):
        """Test loading rosters from JSON file."""
        rosters_path = temp_data_dir / 'rosters.json'
        rosters = load_rosters(rosters_path)

        assert len(rosters) == 2
        assert 'GSA' in rosters
        assert 'CGK' in rosters
        assert len(rosters['GSA']) == 11  # 11 roster spots

    def test_load_lineup(self, temp_data_dir):
        """Test loading lineup from JSON file."""
        lineup_path = temp_data_dir / 'lineups' / '2025' / 'week_1.json'
        lineups = load_lineup(lineup_path, week=1)

        assert 'GSA' in lineups
        assert 'CGK' in lineups
        assert lineups['GSA']['QB'] == ['Patrick Mahomes']
        assert len(lineups['GSA']['RB']) == 2

    def test_build_fantasy_team(self, temp_data_dir):
        """Test building FantasyTeam from JSON data."""
        rosters_path = temp_data_dir / 'rosters.json'
        lineup_path = temp_data_dir / 'lineups' / '2025' / 'week_1.json'

        rosters = load_rosters(rosters_path)
        lineups = load_lineup(lineup_path, week=1)

        team = build_fantasy_team_from_json('GSA', rosters, lineups)

        assert team.abbreviation == 'GSA'
        assert 'QB' in team.players
        assert len(team.players['QB']) == 1
        # Check Patrick Mahomes is marked as starter
        assert any(
            name == 'Patrick Mahomes' and is_started for name, _, is_started in team.players['QB']
        )

    def test_roster_validation_passes(self, temp_data_dir):
        """Test that valid rosters pass validation."""
        rosters_path = temp_data_dir / 'rosters.json'
        lineup_path = temp_data_dir / 'lineups' / '2025' / 'week_1.json'

        rosters = load_rosters(rosters_path)
        lineups = load_lineup(lineup_path, week=1)

        team = build_fantasy_team_from_json('GSA', rosters, lineups)
        errors = validate_roster(team)

        assert errors == []

    @patch('qpfl.data_fetcher.NFLDataFetcher')
    def test_score_week_workflow(self, mock_fetcher_class, temp_data_dir, mock_nfl_data):
        """Test end-to-end week scoring workflow with mocked NFL data."""
        # Setup mock NFLDataFetcher
        mock_fetcher = MagicMock()
        mock_fetcher_class.return_value = mock_fetcher

        # Mock find_player to return test data
        def mock_find_player(name, team, position):
            return mock_nfl_data['player_stats'].get(name)

        mock_fetcher.find_player = mock_find_player
        mock_fetcher.get_turnovers_returned_for_td = Mock(return_value={})
        mock_fetcher.get_extra_fumbles_lost = Mock(return_value=0)
        mock_fetcher.get_team_stats = Mock(return_value=mock_nfl_data['team_stats'].get('KC'))
        mock_fetcher.get_opponent_stats = Mock(return_value={})
        mock_fetcher.get_game_info = Mock(return_value=mock_nfl_data['game_info'].get('KC'))
        mock_fetcher.get_defensive_sacks = Mock(return_value={'value': 4, 'discrepancy': False})
        mock_fetcher.get_ol_touchdowns = Mock(return_value=0)

        # Run scoring
        rosters_path = temp_data_dir / 'rosters.json'
        lineup_path = temp_data_dir / 'lineups' / '2025' / 'week_1.json'

        teams, results = score_week_from_json(
            rosters_path, lineup_path, season=2025, week=1, verbose=False
        )

        # Verify results
        assert len(teams) == 2
        assert 'GSA' in [t.name for t in teams]
        assert len(results) == 2

        # Check that GSA's team has scores
        gsa_team = next(t for t in teams if t.abbreviation == 'GSA')
        gsa_total, gsa_scores = results[gsa_team.name]

        # Total should be sum of starters' points
        assert gsa_total >= 0  # Should have positive score
        assert 'QB' in gsa_scores
        assert len(gsa_scores['QB']) > 0

    @patch('qpfl.data_fetcher.NFLDataFetcher')
    def test_scoring_validation(self, mock_fetcher_class, temp_data_dir):
        """Test that scoring results pass validation checks."""
        # Setup minimal mock
        mock_fetcher = MagicMock()
        mock_fetcher_class.return_value = mock_fetcher
        mock_fetcher.find_player = Mock(return_value={'passing_yards': 250, 'passing_tds': 2})
        mock_fetcher.get_turnovers_returned_for_td = Mock(return_value={})
        mock_fetcher.get_extra_fumbles_lost = Mock(return_value=0)
        mock_fetcher.get_team_stats = Mock(
            return_value={'passing_yards': 250, 'rushing_yards': 100}
        )
        mock_fetcher.get_opponent_stats = Mock(return_value={})
        mock_fetcher.get_game_info = Mock(
            return_value={'team_score': 24, 'opponent_score': 17, 'points_allowed': 17}
        )
        mock_fetcher.get_defensive_sacks = Mock(return_value={'value': 3, 'discrepancy': False})
        mock_fetcher.get_ol_touchdowns = Mock(return_value=0)

        # Score week
        rosters_path = temp_data_dir / 'rosters.json'
        lineup_path = temp_data_dir / 'lineups' / '2025' / 'week_1.json'

        teams, results = score_week_from_json(
            rosters_path, lineup_path, season=2025, week=1, verbose=False
        )

        # Convert results format for validation
        team_scores = {}
        for team in teams:
            total, scores = results[team.name]
            team_scores[team.abbreviation] = {
                player_score.name: player_score
                for position_scores in scores.values()
                for player_score, _ in position_scores
            }

        # Validate all scores
        errors, warnings = validate_all_scores(team_scores)

        # Should have no critical errors
        assert errors == []
        # May have warnings (e.g., players not found) but that's ok


class TestLineupToScoringFlow:
    """Test the flow from lineup submission to final scores."""

    def test_lineup_validation_before_scoring(self, temp_data_dir):
        """Test that lineups are validated before scoring."""
        from qpfl.validators import validate_lineup

        rosters_path = temp_data_dir / 'rosters.json'
        lineup_path = temp_data_dir / 'lineups' / '2025' / 'week_1.json'

        rosters = load_rosters(rosters_path)
        lineups = load_lineup(lineup_path, week=1)

        # Convert roster format for validation
        gsa_roster = {
            pos: [(p['name'], p['nfl_team'], 'active') for p in players if p['position'] == pos]
            for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL']
            for players in [rosters['GSA']]
        }

        # Validate lineup
        errors = validate_lineup('GSA', lineups['GSA'], gsa_roster)

        assert errors == []  # Valid lineup should have no errors


class TestConfigIntegration:
    """Test configuration integration with scoring."""

    def test_config_loaded_in_scorer(self):
        """Test that configuration is loaded correctly."""
        from qpfl.config import get_current_season, get_roster_slots

        season = get_current_season()
        assert season == 2025

        roster_slots = get_roster_slots()
        assert roster_slots['QB'] == 3
        assert roster_slots['RB'] == 4

    def test_scorer_uses_config(self):
        """Test that scorer can use config values."""
        from qpfl.config import get_current_season

        scorer = BaseScorer(season=get_current_season(), week=1)
        assert scorer.season == 2025
        assert scorer.week == 1
