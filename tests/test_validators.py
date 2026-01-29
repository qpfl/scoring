"""Unit tests for validation functions."""

import pytest

from qpfl.models import FantasyTeam, PlayerScore
from qpfl.validators import (
    validate_lineup,
    validate_player_score,
    validate_roster,
    validate_team_score,
)


class TestRosterValidation:
    """Tests for roster validation."""

    def test_valid_roster(self):
        """Test that a valid roster passes all checks."""
        team = FantasyTeam(
            name='Team Test',
            owner='Test Owner',
            abbreviation='TST',
            column_index=1,
            players={
                'QB': [('Patrick Mahomes', 'KC', True), ('Josh Allen', 'BUF', False)],
                'RB': [('Derrick Henry', 'BAL', True), ('Saquon Barkley', 'PHI', True)],
                'WR': [
                    ('Justin Jefferson', 'MIN', True),
                    ('Tyreek Hill', 'MIA', True),
                    ('CeeDee Lamb', 'DAL', True),
                ],
                'TE': [('Travis Kelce', 'KC', True)],
                'K': [('Justin Tucker', 'BAL', True)],
                'D/ST': [('Chiefs D/ST', 'KC', True)],
                'HC': [('Andy Reid', 'KC', True)],
                'OL': [('Chiefs OL', 'KC', True)],
            },
        )
        errors = validate_roster(team)
        assert errors == []

    def test_too_many_qbs(self):
        """Test roster with too many QBs (max 3)."""
        team = FantasyTeam(
            name='Team Test',
            owner='Test Owner',
            abbreviation='TST',
            column_index=1,
            players={
                'QB': [
                    ('QB1', 'KC', False),
                    ('QB2', 'BUF', False),
                    ('QB3', 'MIA', False),
                    ('QB4', 'DAL', False),  # 4th QB - over limit!
                ],
            },
        )
        errors = validate_roster(team)
        assert len(errors) == 1
        assert 'TST has 4 QB players (max 3)' in errors[0]

    def test_too_many_starters(self):
        """Test roster with too many WR starters (max 3)."""
        team = FantasyTeam(
            name='Team Test',
            owner='Test Owner',
            abbreviation='TST',
            column_index=1,
            players={
                'WR': [
                    ('WR1', 'KC', True),
                    ('WR2', 'BUF', True),
                    ('WR3', 'MIA', True),
                    ('WR4', 'DAL', True),  # 4th starter - over limit!
                ],
            },
        )
        errors = validate_roster(team)
        assert len(errors) == 1
        assert 'TST starts 4 WR (max 3)' in errors[0]

    def test_duplicate_players(self):
        """Test roster with duplicate player names."""
        team = FantasyTeam(
            name='Team Test',
            owner='Test Owner',
            abbreviation='TST',
            column_index=1,
            players={
                'RB': [('Derrick Henry', 'BAL', True)],
                'WR': [('Derrick Henry', 'BAL', True)],  # Same name!
            },
        )
        errors = validate_roster(team)
        assert len(errors) == 1
        assert 'duplicate players' in errors[0].lower()
        assert 'Derrick Henry' in errors[0]

    def test_multiple_errors(self):
        """Test roster with multiple validation errors."""
        team = FantasyTeam(
            name='Team Test',
            owner='Test Owner',
            abbreviation='TST',
            column_index=1,
            players={
                'QB': [('QB1', 'KC', False)] * 4,  # Too many QBs
                'RB': [('RB1', 'BUF', True)] * 5,  # Too many RBs
                'WR': [('WR1', 'MIA', True)] * 4,  # Too many starters
            },
        )
        errors = validate_roster(team)
        assert len(errors) >= 3  # At least 3 errors

    def test_empty_roster(self):
        """Test empty roster (edge case)."""
        team = FantasyTeam(
            name='Team Test', owner='Test Owner', abbreviation='TST', column_index=1, players={}
        )
        errors = validate_roster(team)
        assert errors == []  # Empty roster is technically valid

    def test_blank_player_names_ignored(self):
        """Test that blank player names don't cause duplicate issues."""
        team = FantasyTeam(
            name='Team Test',
            owner='Test Owner',
            abbreviation='TST',
            column_index=1,
            players={
                'RB': [('', 'KC', False), ('', 'BUF', False)],  # Empty slots
            },
        )
        errors = validate_roster(team)
        assert errors == []


class TestLineupValidation:
    """Tests for lineup validation."""

    def test_valid_lineup(self):
        """Test valid lineup submission."""
        starters = {
            'QB': ['Patrick Mahomes'],
            'RB': ['Derrick Henry', 'Saquon Barkley'],
            'WR': ['Justin Jefferson', 'Tyreek Hill', 'CeeDee Lamb'],
            'TE': ['Travis Kelce'],
            'K': ['Justin Tucker'],
            'D/ST': ['Chiefs D/ST'],
            'HC': ['Andy Reid'],
            'OL': ['Chiefs OL'],
        }
        roster = {
            'QB': [('Patrick Mahomes', 'KC', 'active')],
            'RB': [('Derrick Henry', 'BAL', 'active'), ('Saquon Barkley', 'PHI', 'active')],
            'WR': [
                ('Justin Jefferson', 'MIN', 'active'),
                ('Tyreek Hill', 'MIA', 'active'),
                ('CeeDee Lamb', 'DAL', 'active'),
            ],
            'TE': [('Travis Kelce', 'KC', 'active')],
            'K': [('Justin Tucker', 'BAL', 'active')],
            'D/ST': [('Chiefs D/ST', 'KC', 'active')],
            'HC': [('Andy Reid', 'KC', 'active')],
            'OL': [('Chiefs OL', 'KC', 'active')],
        }
        errors = validate_lineup('GSA', starters, roster)
        assert errors == []

    def test_too_many_starters_lineup(self):
        """Test lineup with too many RB starters (max 2)."""
        starters = {
            'RB': ['RB1', 'RB2', 'RB3'],  # 3 RBs, max is 2
        }
        roster = {
            'RB': [('RB1', 'KC', 'active'), ('RB2', 'BUF', 'active'), ('RB3', 'MIA', 'active')],
        }
        errors = validate_lineup('TST', starters, roster)
        assert len(errors) == 1
        assert 'TST lineup has 3 RB starters (max 2)' in errors[0]

    def test_starter_not_on_roster(self):
        """Test lineup with player not on roster."""
        starters = {
            'QB': ['Patrick Mahomes'],
        }
        roster = {
            'QB': [('Josh Allen', 'BUF', 'active')],  # Different QB
        }
        errors = validate_lineup('TST', starters, roster)
        assert len(errors) == 1
        assert 'Patrick Mahomes' in errors[0]
        assert 'not on active roster' in errors[0].lower()

    def test_starter_on_taxi_squad(self):
        """Test lineup with player on taxi squad (not active)."""
        starters = {
            'RB': ['Young RB'],
        }
        roster = {
            'RB': [('Young RB', 'KC', 'taxi')],  # On taxi, not active
        }
        errors = validate_lineup('TST', starters, roster)
        assert len(errors) == 1
        assert 'not on active roster' in errors[0].lower()

    def test_duplicate_starters(self):
        """Test lineup with same player listed twice."""
        starters = {
            'RB': ['Derrick Henry', 'Derrick Henry'],  # Same player twice
        }
        roster = {
            'RB': [('Derrick Henry', 'BAL', 'active')],
        }
        errors = validate_lineup('TST', starters, roster)
        assert len(errors) >= 1
        assert 'duplicate' in errors[0].lower()

    def test_blank_entries_ignored(self):
        """Test that blank lineup entries are ignored."""
        starters = {
            'QB': ['Patrick Mahomes'],
            'RB': ['', ''],  # All blank
        }
        roster = {
            'QB': [('Patrick Mahomes', 'KC', 'active')],
        }
        errors = validate_lineup('TST', starters, roster)
        assert errors == []


class TestPlayerScoreValidation:
    """Tests for player score validation."""

    def test_valid_score(self):
        """Test normal player score passes validation."""
        score = PlayerScore(
            name='Patrick Mahomes',
            position='QB',
            team='KC',
            total_points=22.0,
            breakdown={'passing_yards': 12, 'touchdowns': 12, 'turnovers': -2},
            found_in_stats=True,
        )
        warnings = validate_player_score(score)
        assert warnings == []

    def test_unusually_high_score(self):
        """Test score over 100 points generates warning."""
        score = PlayerScore(
            name='Test Player',
            position='QB',
            team='KC',
            total_points=120.0,
            breakdown={},
        )
        warnings = validate_player_score(score)
        assert len(warnings) == 1
        assert 'unusually high' in warnings[0].lower()
        assert '120.0' in warnings[0]

    def test_unusually_low_score(self):
        """Test score below -20 points generates warning."""
        score = PlayerScore(
            name='Bad Day QB',
            position='QB',
            team='KC',
            total_points=-25.0,
            breakdown={},
        )
        warnings = validate_player_score(score)
        assert len(warnings) == 1
        assert 'unusually low' in warnings[0].lower()

    def test_breakdown_mismatch(self):
        """Test breakdown sum != total generates warning."""
        score = PlayerScore(
            name='Test Player',
            position='QB',
            team='KC',
            total_points=25.0,
            breakdown={'passing_yards': 10, 'touchdowns': 12},  # Sum = 22, not 25
        )
        warnings = validate_player_score(score)
        assert len(warnings) == 1
        assert 'breakdown sum' in warnings[0].lower()
        assert 'difference' in warnings[0].lower()

    def test_breakdown_rounding_tolerance(self):
        """Test breakdown mismatch within 0.1 is tolerated."""
        score = PlayerScore(
            name='Test Player',
            position='QB',
            team='KC',
            total_points=25.0,
            breakdown={'passing_yards': 10, 'touchdowns': 15.05},  # Sum = 25.05
        )
        warnings = validate_player_score(score)
        assert warnings == []  # Within 0.1 tolerance

    def test_invalid_score_type(self):
        """Test non-numeric score type."""
        score = PlayerScore(
            name='Test Player',
            position='QB',
            team='KC',
            total_points='not a number',  # Invalid type
            breakdown={},
        )
        warnings = validate_player_score(score)
        assert len(warnings) == 1
        assert 'invalid score type' in warnings[0].lower()

    def test_zero_score_valid(self):
        """Test zero score is valid (DNP or no contribution)."""
        score = PlayerScore(
            name='Inactive Player',
            position='RB',
            team='KC',
            total_points=0.0,
            breakdown={},
        )
        warnings = validate_player_score(score)
        assert warnings == []

    def test_negative_score_in_range(self):
        """Test negative score within range (-20 to 0) is valid."""
        score = PlayerScore(
            name='Rough Day QB',
            position='QB',
            team='KC',
            total_points=-10.0,
            breakdown={'turnovers': -6, 'turnover_tds': -4},
        )
        warnings = validate_player_score(score)
        assert warnings == []


class TestTeamScoreValidation:
    """Tests for team score validation."""

    def test_valid_team_score(self):
        """Test normal team score passes validation."""
        warnings = validate_team_score('GSA', 125.5, 11)
        assert warnings == []

    def test_unusually_high_team_score(self):
        """Test team score over 300 generates warning."""
        warnings = validate_team_score('GSA', 350.0, 11)
        assert len(warnings) == 1
        assert 'unusually high' in warnings[0].lower()

    def test_negative_team_score(self):
        """Test negative team score generates warning."""
        warnings = validate_team_score('GSA', -10.0, 11)
        assert len(warnings) == 1
        assert 'negative total' in warnings[0].lower()

    def test_high_average_per_starter(self):
        """Test average > 50 pts/starter generates warning."""
        warnings = validate_team_score('GSA', 600.0, 11)
        assert len(warnings) >= 1
        assert any('pts/starter' in w.lower() for w in warnings)

    def test_zero_starters_no_crash(self):
        """Test that zero starters doesn't cause division by zero."""
        warnings = validate_team_score('GSA', 0.0, 0)
        assert isinstance(warnings, list)  # Should not crash

    def test_low_but_valid_score(self):
        """Test low but valid team score (bad week)."""
        warnings = validate_team_score('GSA', 45.0, 11)
        assert warnings == []

    def test_boundary_300_points(self):
        """Test exactly 300 points is valid (boundary)."""
        warnings = validate_team_score('GSA', 300.0, 11)
        assert warnings == []

    def test_boundary_301_points(self):
        """Test 301 points triggers warning."""
        warnings = validate_team_score('GSA', 301.0, 11)
        assert len(warnings) == 1
        assert 'unusually high' in warnings[0].lower()
