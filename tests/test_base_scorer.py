"""Tests for qpfl.base_scorer.BaseScorer head-coach eligibility."""

import polars as pl

from qpfl.base_scorer import BaseScorer
from qpfl.data_fetcher import NFLDataFetcher


def _scorer(home_coach: str | None, coach_overrides: dict[str, str]) -> BaseScorer:
    fetcher = NFLDataFetcher(2026, 1)
    fetcher._player_stats = pl.DataFrame([{'player_display_name': 'x'}])
    fetcher._schedules = pl.DataFrame(
        {
            'home_team': ['JAX'],
            'away_team': ['MIA'],
            'home_score': [30],
            'away_score': [17],
            'home_coach': [home_coach],
            'away_coach': ['Mike McDaniel'],
            'week': [1],
        },
        schema={
            'home_team': pl.Utf8,
            'away_team': pl.Utf8,
            'home_score': pl.Int64,
            'away_score': pl.Int64,
            'home_coach': pl.Utf8,
            'away_coach': pl.Utf8,
            'week': pl.Int64,
        },
    )
    return BaseScorer(2026, 1, data_fetcher=fetcher, coach_overrides=coach_overrides)


def test_listed_head_coach_scores_his_game():
    result = _scorer('Liam Coen', {}).score_player('Liam Coen', 'JAC', 'HC')
    assert result.found_in_stats
    assert result.total_points == 3
    assert not result.data_notes


def test_fired_head_coach_scores_zero():
    result = _scorer('Interim Coach', {}).score_player('Liam Coen', 'JAC', 'HC')
    assert result.found_in_stats
    assert result.total_points == 0
    assert result.breakdown == {}
    assert 'not the listed head coach' in result.data_notes[0]


def test_coach_override_wins_over_stale_schedule_under_either_abbreviation():
    for team_key in ('JAC', 'JAX', 'jax'):
        scorer = _scorer('Old Coach', {team_key: 'Liam Coen'})
        assert scorer.score_player('Liam Coen', 'JAC', 'HC').total_points == 3
        assert scorer.score_player('Old Coach', 'JAC', 'HC').total_points == 0


def test_missing_coach_information_fails_open():
    result = _scorer(None, {}).score_player('Liam Coen', 'JAC', 'HC')
    assert result.total_points == 3


def test_head_coach_names_match_across_curly_apostrophes():
    result = _scorer("Kevin O'Connell", {}).score_player('Kevin O’Connell', 'JAC', 'HC')
    assert result.total_points == 3
