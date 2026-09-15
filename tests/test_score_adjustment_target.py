import pytest

from scripts.score_adjustment_target import added_adjustments, target_week


def adjustment(week, *, season=2026, player='Josh Allen'):
    return {'season': season, 'week': week, 'player': player, 'points': -1}


def test_added_adjustments_handles_existing_entries():
    existing = adjustment(1)
    new = adjustment(2)

    assert added_adjustments([existing, new], [existing]) == [new]


def test_target_week_returns_the_single_current_season_addition():
    existing = adjustment(1)

    assert target_week([existing, adjustment(5)], [existing], 2026) == 5


def test_target_week_rejects_missing_or_multiple_targets():
    with pytest.raises(ValueError):
        target_week([adjustment(1)], [adjustment(1)], 2026)
    with pytest.raises(ValueError):
        target_week([adjustment(1), adjustment(2)], [], 2026)
