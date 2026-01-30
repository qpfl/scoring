"""Unit tests for scoring functions."""

import pytest

from qpfl.scoring import (
    score_defense,
    score_head_coach,
    score_kicker,
    score_offensive_line,
    score_skill_player,
)


class TestSkillPlayerScoring:
    """Tests for QB, RB, WR, TE scoring."""

    def test_passing_yards_basic(self):
        """Test QB passing scoring: 1 pt per 25 yards."""
        stats = {
            'passing_yards': 250,
            'passing_tds': 0,
            'passing_interceptions': 0,
        }
        points, breakdown = score_skill_player(stats)
        assert points == 10.0
        assert breakdown['passing_yards'] == 10

    def test_passing_yards_rounding_down(self):
        """Test passing yards rounds down (249 yards = 9 pts, not 10)."""
        stats = {'passing_yards': 249}
        points, breakdown = score_skill_player(stats)
        assert points == 9.0
        assert breakdown['passing_yards'] == 9

    def test_rushing_yards_basic(self):
        """Test rushing scoring: 1 pt per 10 yards."""
        stats = {'rushing_yards': 120}
        points, breakdown = score_skill_player(stats)
        assert points == 12.0
        assert breakdown['rushing_yards'] == 12

    def test_receiving_yards_basic(self):
        """Test receiving scoring: 1 pt per 10 yards."""
        stats = {'receiving_yards': 85}
        points, breakdown = score_skill_player(stats)
        assert points == 8.0
        assert breakdown['receiving_yards'] == 8

    def test_touchdown_scoring(self):
        """Test TD scoring: 6 points each."""
        stats = {'rushing_tds': 2}
        points, breakdown = score_skill_player(stats)
        assert points == 12.0
        assert breakdown['touchdowns'] == 12

    def test_multiple_touchdown_types(self):
        """Test multiple TD types (passing, rushing, receiving)."""
        stats = {
            'passing_tds': 2,
            'rushing_tds': 1,
            'receiving_tds': 1,
        }
        points, breakdown = score_skill_player(stats)
        assert points == 24.0
        assert breakdown['touchdowns'] == 24

    def test_interception_penalty(self):
        """Test turnover scoring: -2 points per interception."""
        stats = {'passing_interceptions': 3}
        points, breakdown = score_skill_player(stats)
        assert points == -6.0
        assert breakdown['turnovers'] == -6

    def test_fumble_lost_penalty(self):
        """Test fumble lost: -2 points each."""
        stats = {
            'sack_fumbles_lost': 1,
            'rushing_fumbles_lost': 1,
            'receiving_fumbles_lost': 1,
        }
        points, breakdown = score_skill_player(stats)
        assert points == -6.0
        assert breakdown['turnovers'] == -6

    def test_pick_six_additional_penalty(self):
        """Test pick-6 adds -4 pts (total -6 with base turnover)."""
        stats = {'passing_interceptions': 1}
        turnover_tds = {'pick_sixes': 1, 'fumble_sixes': 0}
        points, breakdown = score_skill_player(stats, turnover_tds)
        assert points == -6.0  # -2 for INT, -4 for pick-6
        assert breakdown['turnovers'] == -2
        assert breakdown['turnover_tds'] == -4

    def test_fumble_six_additional_penalty(self):
        """Test fumble-6 adds -4 pts (total -6 with base turnover)."""
        stats = {'rushing_fumbles_lost': 1}
        turnover_tds = {'pick_sixes': 0, 'fumble_sixes': 1}
        points, breakdown = score_skill_player(stats, turnover_tds)
        assert points == -6.0  # -2 for fumble, -4 for fumble-6
        assert breakdown['turnovers'] == -2
        assert breakdown['turnover_tds'] == -4

    def test_extra_fumbles_parameter(self):
        """Test extra_fumbles parameter (lateral fumbles, etc)."""
        stats = {'rushing_fumbles_lost': 1}
        points, breakdown = score_skill_player(stats, extra_fumbles=1)
        assert points == -4.0  # -2 for each of 2 fumbles
        assert breakdown['turnovers'] == -4

    def test_two_point_conversions(self):
        """Test 2-point conversions: 2 pts each."""
        stats = {
            'passing_2pt_conversions': 1,
            'rushing_2pt_conversions': 1,
        }
        points, breakdown = score_skill_player(stats)
        assert points == 4.0
        assert breakdown['two_point_conversions'] == 4

    def test_comprehensive_qb_game(self):
        """Test realistic QB stat line."""
        stats = {
            'passing_yards': 325,  # 13 pts
            'passing_tds': 3,  # 18 pts
            'passing_interceptions': 1,  # -2 pts
            'rushing_yards': 45,  # 4 pts
            'rushing_tds': 1,  # 6 pts
        }
        points, breakdown = score_skill_player(stats)
        assert points == 39.0
        assert breakdown['passing_yards'] == 13
        assert breakdown['touchdowns'] == 24
        assert breakdown['turnovers'] == -2
        assert breakdown['rushing_yards'] == 4

    def test_comprehensive_rb_game(self):
        """Test realistic RB stat line."""
        stats = {
            'rushing_yards': 125,  # 12 pts
            'rushing_tds': 2,  # 12 pts
            'receiving_yards': 35,  # 3 pts
            'receiving_tds': 0,
            'rushing_fumbles_lost': 1,  # -2 pts
        }
        points, breakdown = score_skill_player(stats)
        assert points == 25.0

    def test_zero_stats(self):
        """Test player with no stats (DNP or zero contribution)."""
        stats = {}
        points, breakdown = score_skill_player(stats)
        assert points == 0.0
        assert breakdown == {}

    def test_none_values_handled(self):
        """Test that None values in stats are handled gracefully."""
        stats = {
            'passing_yards': None,
            'passing_tds': None,
            'rushing_yards': 100,
        }
        points, breakdown = score_skill_player(stats)
        assert points == 10.0  # Only rushing yards counted


class TestKickerScoring:
    """Tests for kicker scoring."""

    def test_pat_made(self):
        """Test PAT made: 1 point each."""
        stats = {'pat_made': 4}
        points, breakdown = score_kicker(stats)
        assert points == 4.0
        assert breakdown['pat_made'] == 4

    def test_pat_missed_penalty(self):
        """Test PAT missed: -2 points each."""
        stats = {'pat_missed': 2}
        points, breakdown = score_kicker(stats)
        assert points == -4.0
        assert breakdown['pat_missed'] == -4

    def test_pat_blocked_penalty(self):
        """Test blocked PAT: -2 points (same as missed)."""
        stats = {'pat_blocked': 1}
        points, breakdown = score_kicker(stats)
        assert points == -2.0
        assert breakdown['pat_blocked'] == -2

    def test_fg_1_29_yards(self):
        """Test FG 1-29 yards: 1 point each."""
        stats = {'fg_made_0_19': 1, 'fg_made_20_29': 2}
        points, breakdown = score_kicker(stats)
        assert points == 3.0
        assert breakdown['fg_1_29'] == 3

    def test_fg_30_39_yards(self):
        """Test FG 30-39 yards: 2 points each."""
        stats = {'fg_made_30_39': 2}
        points, breakdown = score_kicker(stats)
        assert points == 4.0
        assert breakdown['fg_30_39'] == 4

    def test_fg_40_49_yards(self):
        """Test FG 40-49 yards: 3 points each."""
        stats = {'fg_made_40_49': 3}
        points, breakdown = score_kicker(stats)
        assert points == 9.0
        assert breakdown['fg_40_49'] == 9

    def test_fg_50_59_yards(self):
        """Test FG 50-59 yards: 4 points each."""
        stats = {'fg_made_50_59': 1}
        points, breakdown = score_kicker(stats)
        assert points == 4.0
        assert breakdown['fg_50_59'] == 4

    def test_fg_60_plus_yards(self):
        """Test FG 60+ yards: 5 points each."""
        stats = {'fg_made_60_': 1}
        points, breakdown = score_kicker(stats)
        assert points == 5.0
        assert breakdown['fg_60+'] == 5

    def test_fg_missed_penalty(self):
        """Test FG missed: -1 point each."""
        stats = {'fg_missed': 2}
        points, breakdown = score_kicker(stats)
        assert points == -2.0
        assert breakdown['fg_missed'] == -2

    def test_fg_blocked_penalty(self):
        """Test blocked FG: -1 point (same as missed)."""
        stats = {'fg_blocked': 1}
        points, breakdown = score_kicker(stats)
        assert points == -1.0
        assert breakdown['fg_blocked'] == -1

    def test_comprehensive_kicker_game(self):
        """Test realistic kicker stat line."""
        stats = {
            'pat_made': 5,  # 5 pts
            'pat_missed': 1,  # -2 pts
            'fg_made_30_39': 1,  # 2 pts
            'fg_made_40_49': 2,  # 6 pts
            'fg_missed': 1,  # -1 pt
        }
        points, breakdown = score_kicker(stats)
        assert points == 10.0


class TestDefenseScoring:
    """Tests for defense/special teams scoring."""

    def test_shutout_bonus(self):
        """Test shutout (0 pts allowed): 8 points."""
        team_stats = {}
        opponent_stats = {}
        game_info = {'points_allowed': 0}
        points, breakdown = score_defense(team_stats, opponent_stats, game_info)
        assert breakdown['points_allowed'] == 8

    def test_points_allowed_tiers(self):
        """Test all point-allowed scoring tiers."""
        test_cases = [
            (0, 8),  # Shutout
            (5, 6),  # 2-9 pts
            (12, 4),  # 10-13 pts
            (16, 2),  # 14-17 pts
            (24, 0),  # 18-27 pts
            (30, -2),  # 28-31 pts
            (34, -4),  # 32-35 pts
            (40, -6),  # 36+ pts
        ]
        for pts_allowed, expected_pts in test_cases:
            game_info = {'points_allowed': pts_allowed}
            points, breakdown = score_defense({}, {}, game_info)
            assert breakdown['points_allowed'] == expected_pts

    def test_interceptions(self):
        """Test interceptions: 2 points each."""
        team_stats = {'def_interceptions': 3}
        points, breakdown = score_defense(team_stats, {}, {'points_allowed': 20})
        assert breakdown['interceptions'] == 6

    def test_fumble_recoveries(self):
        """Test fumble recoveries: 2 points each."""
        team_stats = {'fumble_recovery_opp': 2}
        opponent_stats = {}
        points, breakdown = score_defense(team_stats, opponent_stats, {'points_allowed': 20})
        assert breakdown['fumble_recoveries'] == 4

    def test_fumble_recovery_max_logic(self):
        """Test fumble recovery uses MAX of team recovery vs opponent fumbles lost."""
        # Case: Opponent lost 3 fumbles, but we only recovered 2 (1 went out of bounds)
        team_stats = {'fumble_recovery_opp': 2}
        opponent_stats = {
            'sack_fumbles_lost': 1,
            'rushing_fumbles_lost': 1,
            'receiving_fumbles_lost': 1,
        }
        points, breakdown = score_defense(team_stats, opponent_stats, {'points_allowed': 20})
        assert breakdown['fumble_recoveries'] == 6  # Uses opponent's 3, not our 2

    def test_sacks(self):
        """Test sacks: 1 point each."""
        team_stats = {'def_sacks': 5}
        points, breakdown = score_defense(team_stats, {}, {'points_allowed': 20})
        assert breakdown['sacks'] == 5

    def test_sacks_pbp_override(self):
        """Test play-by-play sacks override team stats (more accurate)."""
        team_stats = {'def_sacks': 4}  # Team stat says 4
        points, breakdown = score_defense(team_stats, {}, {'points_allowed': 20}, pbp_sacks=5)
        assert breakdown['sacks'] == 5  # PBP says 5, use that

    def test_safeties(self):
        """Test safeties: 2 points each."""
        team_stats = {'def_safeties': 1}
        points, breakdown = score_defense(team_stats, {}, {'points_allowed': 20})
        assert breakdown['safeties'] == 2

    def test_blocked_kicks(self):
        """Test blocked FG/punt: 2 points each."""
        opponent_stats = {'fg_blocked': 1}
        points, breakdown = score_defense({}, opponent_stats, {'points_allowed': 20})
        assert breakdown['blocked_kicks'] == 2

    def test_blocked_pats(self):
        """Test blocked PAT: 1 point each."""
        opponent_stats = {'pat_blocked': 1}
        points, breakdown = score_defense({}, opponent_stats, {'points_allowed': 20})
        assert breakdown['blocked_pats'] == 1

    def test_defensive_touchdowns(self):
        """Test defensive/ST TDs: 4 points each."""
        team_stats = {
            'def_tds': 1,  # Pick-6
            'fumble_recovery_tds': 1,  # Fumble return TD
            'special_teams_tds': 1,  # Kick return TD
        }
        points, breakdown = score_defense(team_stats, {}, {'points_allowed': 20})
        assert breakdown['defensive_st_tds'] == 12  # 3 TDs × 4 pts

    def test_comprehensive_defense_game(self):
        """Test realistic defense stat line."""
        team_stats = {
            'def_interceptions': 2,  # 4 pts
            'fumble_recovery_opp': 1,  # 2 pts
            'def_sacks': 4,  # 4 pts
            'def_tds': 1,  # 4 pts
        }
        opponent_stats = {'fg_blocked': 1}  # 2 pts
        game_info = {'points_allowed': 17}  # 2 pts (14-17 tier)
        points, breakdown = score_defense(team_stats, opponent_stats, game_info)
        assert points == 18.0


class TestHeadCoachScoring:
    """Tests for head coach scoring."""

    def test_win_by_less_than_10(self):
        """Test win by <10: 2 points."""
        game_info = {'team_score': 24, 'opponent_score': 21}
        points, breakdown = score_head_coach(game_info)
        assert points == 2.0
        assert 'win_margin_<10' in breakdown

    def test_win_by_10_to_19(self):
        """Test win by 10-19: 3 points."""
        game_info = {'team_score': 30, 'opponent_score': 15}
        points, breakdown = score_head_coach(game_info)
        assert points == 3.0
        assert 'win_margin_10-19' in breakdown

    def test_win_by_20_plus(self):
        """Test win by 20+: 4 points."""
        game_info = {'team_score': 42, 'opponent_score': 10}
        points, breakdown = score_head_coach(game_info)
        assert points == 4.0
        assert 'win_margin_20+' in breakdown

    def test_loss_by_less_than_10(self):
        """Test loss by <10: -1 point."""
        game_info = {'team_score': 20, 'opponent_score': 24}
        points, breakdown = score_head_coach(game_info)
        assert points == -1.0
        assert 'loss_margin_<10' in breakdown

    def test_loss_by_10_to_20(self):
        """Test loss by 10-20: -2 points."""
        game_info = {'team_score': 10, 'opponent_score': 24}
        points, breakdown = score_head_coach(game_info)
        assert points == -2.0
        assert 'loss_margin_10-20' in breakdown

    def test_loss_by_more_than_20(self):
        """Test loss by 20+: -3 points."""
        game_info = {'team_score': 7, 'opponent_score': 35}
        points, breakdown = score_head_coach(game_info)
        assert points == -3.0
        assert 'loss_margin_20+' in breakdown

    def test_tie_game(self):
        """Test tie game: 0 points (no breakdown entry)."""
        game_info = {'team_score': 20, 'opponent_score': 20}
        points, breakdown = score_head_coach(game_info)
        assert points == 0.0
        assert breakdown == {}


class TestOffensiveLineScoring:
    """Tests for offensive line scoring."""

    def test_passing_yards(self):
        """Test passing yards: 1 pt per 100 net yards."""
        team_stats = {
            'passing_yards': 350,
            'sack_yards_lost': -30,  # Net: 320 yards
        }
        points, breakdown = score_offensive_line(team_stats)
        assert breakdown['passing_yards'] == 3  # 320 / 100 = 3.2, floor to 3

    def test_rushing_yards(self):
        """Test rushing yards: 1 pt per 50 yards."""
        team_stats = {'rushing_yards': 175}
        points, breakdown = score_offensive_line(team_stats)
        assert breakdown['rushing_yards'] == 3  # 175 / 50 = 3.5, floor to 3

    def test_sacks_allowed_penalty(self):
        """Test sacks allowed: -1 point each."""
        team_stats = {'sacks_suffered': 4}
        points, breakdown = score_offensive_line(team_stats)
        assert breakdown['sacks_allowed'] == -4

    def test_ol_touchdowns(self):
        """Test OL touchdowns: 6 points each (rare)."""
        team_stats = {}
        points, breakdown = score_offensive_line(team_stats, ol_touchdowns=1)
        assert breakdown['ol_touchdowns'] == 6

    def test_comprehensive_ol_game(self):
        """Test realistic OL stat line."""
        team_stats = {
            'passing_yards': 280,
            'sack_yards_lost': -20,  # Net: 260
            'rushing_yards': 120,
            'sacks_suffered': 2,
        }
        points, breakdown = score_offensive_line(team_stats)
        # 260/100 = 2 (passing) + 120/50 = 2 (rushing) - 2 (sacks) = 2 pts
        assert points == 2.0

    def test_zero_stats(self):
        """Test OL with minimal stats."""
        team_stats = {'passing_yards': 50, 'rushing_yards': 25}
        points, breakdown = score_offensive_line(team_stats)
        assert points == 0.0  # Not enough yards to score points


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_negative_yards_handled(self):
        """Test negative rushing/receiving yards (rare but possible)."""
        stats = {'rushing_yards': -5}
        points, breakdown = score_skill_player(stats)
        assert points == 0.0  # -5 / 10 = 0 (floor)

    def test_exact_boundary_values(self):
        """Test exact boundary values for passing yards."""
        # Exactly 25 yards = 1 pt
        stats = {'passing_yards': 25}
        points, _ = score_skill_player(stats)
        assert points == 1.0

        # 24 yards = 0 pts (rounds down)
        stats = {'passing_yards': 24}
        points, _ = score_skill_player(stats)
        assert points == 0.0

    def test_large_stat_values(self):
        """Test very large stat values (record-breaking performances)."""
        stats = {'passing_yards': 550, 'passing_tds': 7}  # Record-breaking game
        points, breakdown = score_skill_player(stats)
        assert points == 64.0  # 22 (yards) + 42 (TDs)

    def test_empty_breakdown_not_added(self):
        """Test that zero-valued categories aren't added to breakdown."""
        stats = {'passing_yards': 0, 'rushing_yards': 100}
        points, breakdown = score_skill_player(stats)
        assert 'passing_yards' not in breakdown  # 0 not added
        assert 'rushing_yards' in breakdown  # 10 added
