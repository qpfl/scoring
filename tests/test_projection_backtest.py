import pytest

import qpfl.projections as projection_module
from scripts.backtest_projections import (
    ErrorMetrics,
    ProjectionSettings,
    _pregame_schedule,
    use_projection_settings,
)


def test_backtest_defaults_match_production_projection_settings():
    settings = ProjectionSettings()

    assert settings.prior_games_weight == projection_module.PRIOR_GAMES_WEIGHT
    assert settings.player_position_weight == projection_module.PLAYER_POSITION_WEIGHT
    assert settings.trim_fraction == projection_module.OUTLIER_TRIM_FRACTION
    assert settings.minimum_trim_samples == projection_module.MIN_OUTLIER_SAMPLES
    assert settings.opponent_cap == pytest.approx(projection_module.MAX_OPPONENT_MULTIPLIER - 1)
    assert settings.opponent_full_weight_samples == projection_module.OPPONENT_FULL_WEIGHT_SAMPLES
    assert settings.exclude_legacy_bench_zeroes is True


def test_pregame_schedule_hides_only_the_week_being_projected():
    rows = [
        {'season': 2025, 'week': 1, 'result': 'final'},
        {'season': 2025, 'week': 2, 'result': 'final'},
        {'season': 2024, 'week': 1, 'result': 'final'},
    ]

    pregame = _pregame_schedule(rows, 2025, 1)

    assert pregame[0]['result'] is None
    assert pregame[1]['result'] == 'final'
    assert pregame[2]['result'] == 'final'
    assert rows[0]['result'] == 'final'


def test_projection_settings_are_restored_after_backtest_override():
    original = projection_module.PRIOR_GAMES_WEIGHT

    with use_projection_settings(ProjectionSettings(prior_games_weight=99)):
        assert projection_module.PRIOR_GAMES_WEIGHT == 99

    assert original == projection_module.PRIOR_GAMES_WEIGHT


def test_error_metrics_report_mae_rmse_and_bias():
    metrics = ErrorMetrics()
    metrics.add(projected=8, actual=10)
    metrics.add(projected=14, actual=10)

    assert metrics.summary() == {
        'count': 2,
        'mae': 3,
        'rmse': pytest.approx(3.162),
        'bias': 1,
    }
