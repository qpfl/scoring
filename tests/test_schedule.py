"""Unit tests for qpfl.schedule."""

import pytest

from qpfl.schedule import get_playoff_schedule, resolve_playoff_matchups, schedule_path_for_season


def test_schedule_path_is_owned_by_the_requested_season(tmp_path):
    assert schedule_path_for_season(tmp_path / 'data', 2027) == (
        tmp_path / 'data' / 'seasons' / '2027' / 'schedule.txt'
    )


def _standings(n=10):
    return [{'abbrev': f'T{i + 1}'} for i in range(n)]


class TestGetPlayoffSchedule:
    """P0.8: get_playoff_schedule must not crash for any supported season."""

    def test_2026_season_returns_schedule(self):
        schedule = get_playoff_schedule(_standings(), season=2026)
        assert len(schedule) == 2
        weeks = {w['week'] for w in schedule}
        assert weeks == {16, 17}

    def test_pre_2026_season_raises_clear_error(self):
        """Historical seasons are frozen/Excel-scored; this path is 2026+ only."""
        with pytest.raises(ValueError, match='2026'):
            get_playoff_schedule(_standings(), season=2024)


class TestResolvePlayoffMatchupsTiebreak:
    """P1.3: an exact tie in the mid bowl must go to the higher seed (team1)."""

    def test_mid_bowl_tie_awards_higher_seed(self):
        week_16_results = {
            'mid_bowl_1': {
                'team1': 'SEED5',
                'team2': 'SEED6',
                'team1_score': 100,
                'team2_score': 90,
            }
        }
        week_17_results = {'mid_bowl_2': {'team1_score': 0, 'team2_score': 10}}
        # Cumulative: SEED5 = 100, SEED6 = 100 -> exact tie.
        final = resolve_playoff_matchups(week_16_results, week_17_results)
        assert final['SEED5'] == 5
        assert final['SEED6'] == 6

    def test_mid_bowl_clear_winner_still_correct(self):
        week_16_results = {
            'mid_bowl_1': {'team1': 'SEED5', 'team2': 'SEED6', 'team1_score': 50, 'team2_score': 90}
        }
        week_17_results = {'mid_bowl_2': {'team1_score': 0, 'team2_score': 10}}
        # Cumulative: SEED5 = 50, SEED6 = 100 -> SEED6 clearly wins.
        final = resolve_playoff_matchups(week_16_results, week_17_results)
        assert final['SEED6'] == 5
        assert final['SEED5'] == 6
