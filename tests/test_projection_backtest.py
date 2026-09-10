import pytest

import qpfl.projections as projection_module
from scripts.backtest_projections import (
    BacktestMetrics,
    ErrorMetrics,
    ProjectionSettings,
    _pregame_schedule,
    _RunningMeans,
    parse_season_range,
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
    assert (
        settings.position_average_uses_plain_mean
        is projection_module.POSITION_AVERAGE_USES_PLAIN_MEAN
    )
    assert dict(settings.position_average_weight_by_position) == (
        projection_module.POSITION_AVERAGE_WEIGHT_BY_POSITION
    )


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

    summary = metrics.summary()

    assert summary['count'] == 2
    assert summary['mae'] == 3
    assert summary['rmse'] == pytest.approx(3.162)
    assert summary['bias'] == 1
    assert summary['actual_mean'] == 10
    assert summary['actual_sd'] == 0
    assert summary['mae_over_sd'] is None


def test_merged_error_metrics_weight_by_sample_size():
    small = ErrorMetrics()
    small.add(projected=10, actual=4)

    large = ErrorMetrics()
    for _ in range(9):
        large.add(projected=10, actual=10)

    pooled = ErrorMetrics()
    pooled.merge(small)
    pooled.merge(large)

    summary = pooled.summary()

    # Sample-weighted: 6 / 10, not the mean of the two MAEs (6 and 0).
    assert summary['count'] == 10
    assert summary['mae'] == 0.6
    assert summary['rmse'] == pytest.approx(1.897, abs=0.001)
    assert summary['bias'] == 0.6


def test_merged_backtest_metrics_pool_every_accumulator():
    first = BacktestMetrics()
    first.players.add(projected=10, actual=8)
    first.teams.add(projected=100, actual=90)
    first.positions['QB'].add(projected=20, actual=18)
    first.matchup_count = 4
    first.correct_winners = 3
    first.brier_total = 0.8

    second = BacktestMetrics()
    second.players.add(projected=6, actual=8)
    second.positions['RB'].add(projected=5, actual=9)
    second.matchup_count = 6
    second.correct_winners = 2
    second.brier_total = 1.2

    first.merge(second)
    summary = first.summary()

    assert summary['players']['count'] == 2
    assert summary['players']['bias'] == 0
    assert summary['teams']['count'] == 1
    assert sorted(summary['positions']) == ['QB', 'RB']
    assert summary['matchups'] == {
        'count': 10,
        'winner_accuracy': 0.5,
        'brier_score': 0.2,
    }


def test_backtest_settings_match_the_shipped_structural_defaults():
    settings = ProjectionSettings()

    assert settings.treat_unknown_team_as_bye is projection_module.TREAT_UNKNOWN_TEAM_AS_BYE
    assert settings.position_mean_starters_only is projection_module.POSITION_MEAN_STARTERS_ONLY
    assert dict(settings.prior_games_weight_by_position) == (
        projection_module.PRIOR_GAMES_WEIGHT_BY_POSITION
    )
    assert dict(settings.player_position_weight_by_position) == (
        projection_module.PLAYER_POSITION_WEIGHT_BY_POSITION
    )
    assert dict(settings.trim_fraction_by_position) == (
        projection_module.OUTLIER_TRIM_FRACTION_BY_POSITION
    )


def test_running_means_ignore_bench_and_fall_back_to_the_position():
    running = _RunningMeans()
    running.observe_week(
        {
            'teams': [
                {
                    'roster': [
                        {'name': 'Starter QB', 'position': 'QB', 'score': 20, 'starter': True},
                        {'name': 'Other QB', 'position': 'QB', 'score': 10, 'starter': True},
                        {'name': 'Bench QB', 'position': 'QB', 'score': 0, 'starter': False},
                        {
                            'name': 'Unmatched',
                            'position': 'QB',
                            'score': 99,
                            'starter': True,
                            'found': False,
                        },
                    ]
                }
            ]
        }
    )

    # Bench and unmatched rows are excluded, so the position average is 15.
    assert running.position_mean('QB') == 15
    assert running.player_mean(('starter qb', 'QB')) == 20
    # A player with no history of his own falls back to the position average.
    assert running.player_mean(('rookie qb', 'QB')) == 15
    assert running.position_mean('RB') == 0


def test_skill_summary_reports_model_error_relative_to_each_baseline():
    metrics = BacktestMetrics()
    metrics.players.add(projected=12, actual=10)
    metrics.positions['QB'].add(projected=12, actual=10)
    # Baselines miss by twice as much, so the model's error is 50% smaller.
    metrics.add_baseline('position_mean', 'QB', 14, 10)
    metrics.add_baseline('player_mean', 'QB', 6, 10)

    skill = metrics.summary()['skill_vs_baseline']

    assert skill['position_mean']['overall'] == -0.5
    assert skill['position_mean']['positions']['QB'] == -0.5
    assert skill['player_mean']['overall'] == -0.5


def test_parse_season_range_accepts_ranges_and_lists():
    assert parse_season_range('2021-2025') == [2021, 2022, 2023, 2024, 2025]
    assert parse_season_range('2024') == [2024]
    assert parse_season_range('2021, 2024-2025, 2021') == [2021, 2024, 2025]


def test_replayed_weeks_have_identical_live_and_pregame_totals(tmp_path):
    """The backtest masks the target week's results, so nothing is ever final
    inside a replay and the live line collapses onto the pregame one. Every
    number in docs/PROJECTION_BACKTEST.md depends on that."""
    import tests.test_projections as fixtures
    from qpfl.projections import calculate_week_projections

    fixtures._write_week(
        tmp_path,
        2025,
        1,
        [{'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 12}],
    )
    team, results = fixtures._team_and_results('A', 'Team A', 'Target QB', 'KC', score=25)
    rows = [
        fixtures._schedule_game(2025, 1, 'KC', 'MIA', final=True),
        fixtures._schedule_game(2026, 1, 'KC', 'BUF', final=True),
    ]

    with use_projection_settings(ProjectionSettings()):
        projections = calculate_week_projections(
            [team],
            results,
            [],
            2026,
            1,
            tmp_path,
            _pregame_schedule(rows, 2026, 1),
        )

    projection = projections.teams['A']
    assert projection.pregame_total == projection.projected_total
    assert projection.projected_total != 25
