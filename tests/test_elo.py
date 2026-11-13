import math

import pytest

from qpfl import elo
from qpfl import weekly_facts as wf
from tests.test_pregame import _matchup, _run, _upcoming


def test_expected_and_margin_multiplier():
    assert elo.expected(1500, 1500) == 0.5
    assert elo.expected(1600, 1500) == pytest.approx(0.640, abs=0.001)
    # A favourite's blowout counts for less than the same margin as an upset.
    assert elo.mov_multiplier(20, 100) < elo.mov_multiplier(20, -100)
    assert elo.mov_multiplier(20, 0) == pytest.approx(math.log(21))


def test_a_game_moves_both_ratings_by_the_same_amount():
    history = elo.EloHistory(_matchup(2024, 1, 'GSA', 120, 'CGK', 100))
    change = elo.K * math.log(21) * 0.5
    assert history.ratings['GSA'] == pytest.approx(1500 + change)
    assert history.ratings['CGK'] == pytest.approx(1500 - change)
    # One point per franchise per week, from both rows of the game counted once.
    assert history.series['GSA'] == [(2024, 1, round(1500 + change, 1))]


def test_playoffs_weigh_more_and_ties_dont_move_equal_teams():
    regular = elo.EloHistory(_matchup(2024, 16, 'GSA', 120, 'CGK', 100))
    playoff = elo.EloHistory(_matchup(2024, 16, 'GSA', 120, 'CGK', 100, wf.PLAYOFFS))
    assert playoff.ratings['GSA'] - 1500 == pytest.approx(1.25 * (regular.ratings['GSA'] - 1500))
    tied = elo.EloHistory(_matchup(2024, 1, 'GSA', 100, 'CGK', 100))
    assert tied.ratings['GSA'] == 1500


def test_ratings_regress_a_third_toward_1500_between_seasons():
    games = _matchup(2024, 1, 'GSA', 150, 'CGK', 50) + _matchup(2025, 1, 'GSA', 100, 'CGK', 100)
    first = elo.EloHistory(games[:2]).ratings['GSA']
    history = elo.EloHistory(games)
    # The 2025 tie between the regressed ratings nudges the favourite down.
    regressed = 1500 + (first - 1500) * elo.CARRYOVER
    assert history.ratings['GSA'] < regressed
    # A new season's rating going in applies the regression before any game.
    assert elo.EloHistory(games[:2]).rating(('GSA',), 2025) == pytest.approx(regressed)


def test_pregame_matchups_carry_elo_coming_in():
    games = _matchup(2026, 1, 'GSA', 150, 'CGK', 50)
    result = _run(games, _upcoming(2026, 2, 'GSA', 'CGK'))
    block = result['matchups'][0]['elo']
    assert block['team1'] > 1500 > block['team2']
    assert 0.5 < block['team1_win_prob'] < 1
