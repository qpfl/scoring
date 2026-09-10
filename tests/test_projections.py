import json
from pathlib import Path

import pytest

import qpfl.projections as projection_module
from qpfl.json_scorer import save_week_scores
from qpfl.models import FantasyTeam, PlayerScore
from qpfl.projections import calculate_week_projections


def _schedule_game(
    season: int,
    week: int,
    home: str,
    away: str,
    *,
    final: bool = False,
) -> dict:
    return {
        'season': season,
        'week': week,
        'game_type': 'REG',
        'home_team': home,
        'away_team': away,
        'gameday': f'{season}-09-{week + 1:02d}',
        'gametime': '13:00',
        'result': f'{home} 24-17 {away}' if final else None,
    }


@pytest.fixture(autouse=True)
def fixed_projection_parameters(monkeypatch):
    """Pin the mechanics tests to the documented global parameters.

    These tests assert exact arithmetic, so they must not move every time the
    shipped per-position tuning is refreshed. The tuned values are covered by
    the backtest instead.
    """
    monkeypatch.setattr(projection_module, 'PRIOR_GAMES_WEIGHT', 2)
    monkeypatch.setattr(projection_module, 'PLAYER_POSITION_WEIGHT', 8)
    monkeypatch.setattr(projection_module, 'OUTLIER_TRIM_FRACTION', 0.1)
    monkeypatch.setattr(projection_module, 'PRIOR_GAMES_WEIGHT_BY_POSITION', {})
    monkeypatch.setattr(projection_module, 'PLAYER_POSITION_WEIGHT_BY_POSITION', {})
    monkeypatch.setattr(projection_module, 'OUTLIER_TRIM_FRACTION_BY_POSITION', {})
    monkeypatch.setattr(projection_module, 'POSITION_AVERAGE_WEIGHT_BY_POSITION', {})


def _write_week(root: Path, season: int, week: int, players: list[dict]) -> None:
    path = root / str(season) / 'weeks' / f'week_{week}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            # A history entry with no explicit slot represents a player who
            # started, which is what the position average is built from.
            {
                'week': week,
                'teams': [
                    {
                        'abbrev': 'HIST',
                        'roster': [{'starter': True, **player} for player in players],
                        'total_score': sum(player['score'] for player in players),
                    }
                ],
            }
        ),
        encoding='utf-8',
    )


def _team_and_results(
    abbrev: str,
    name: str,
    player_name: str,
    nfl_team: str,
    score: float = 0,
    starter: bool = True,
):
    team = FantasyTeam(
        name=name,
        owner='',
        abbreviation=abbrev,
        column_index=0,
        players={'QB': [(player_name, nfl_team, starter)]},
    )
    player_score = PlayerScore(
        name=player_name,
        position='QB',
        team=nfl_team,
        total_points=score,
        found_in_stats=score != 0,
    )
    return team, {name: (score, {'QB': [(player_score, starter)]})}


def test_blends_current_average_with_two_games_of_prior_history(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    _write_week(
        tmp_path,
        2025,
        1,
        [{'name': 'Player One Jr.', 'position': 'QB', 'nfl_team': 'KC', 'score': 12}],
    )
    _write_week(
        tmp_path,
        2026,
        1,
        [
            {
                'name': 'Player One',
                'position': 'QB',
                'nfl_team': 'KC',
                'score': 20,
                'found': True,
            }
        ],
    )
    team, results = _team_and_results('A', 'Team A', 'Player One', 'KC')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'BUF', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF', final=True),
        _schedule_game(2026, 2, 'KC', 'BUF'),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 2, tmp_path, schedules)

    player = projections.players[('A', 'player one', 'QB')]
    assert player.projected_points == pytest.approx(14.7)
    assert player.sample_size == 2


def test_prior_player_average_is_stabilized_toward_position_average(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    _write_week(
        tmp_path,
        2025,
        1,
        [
            {'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 30},
            {'name': 'Other QB', 'position': 'QB', 'nfl_team': 'NYJ', 'score': 10},
        ],
    )
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2025, 1, 'NYJ', 'DEN', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF'),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'target qb', 'QB')]
    assert player.projected_points == pytest.approx(21.1)


def test_opponent_adjustment_uses_position_points_allowed_and_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    monkeypatch.setattr(projection_module, 'OPPONENT_FULL_WEIGHT_SAMPLES', 1)
    monkeypatch.setattr(projection_module, 'PLAYER_POSITION_WEIGHT', 0)
    _write_week(
        tmp_path,
        2025,
        1,
        [
            {'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 10},
            {'name': 'Other QB', 'position': 'QB', 'nfl_team': 'NYJ', 'score': 20},
        ],
    )
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2025, 1, 'NYJ', 'BUF', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF'),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'target qb', 'QB')]
    assert player.opponent_multiplier == pytest.approx(1.2)
    assert player.projected_points == pytest.approx(12.0)


def test_small_opponent_sample_is_shrunk_toward_neutral(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    monkeypatch.setattr(projection_module, 'PLAYER_POSITION_WEIGHT', 0)
    _write_week(
        tmp_path,
        2025,
        1,
        [
            {'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 10},
            {'name': 'Other QB', 'position': 'QB', 'nfl_team': 'NYJ', 'score': 20},
        ],
    )
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2025, 1, 'NYJ', 'BUF', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF'),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'target qb', 'QB')]
    assert player.opponent_multiplier == pytest.approx(1.00625)
    assert player.projected_points == pytest.approx(10.1)


def test_opponent_adjustment_preserves_direction_for_negative_positions(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'HC': 1})
    monkeypatch.setattr(projection_module, 'OPPONENT_FULL_WEIGHT_SAMPLES', 1)
    monkeypatch.setattr(projection_module, 'PLAYER_POSITION_WEIGHT', 0)
    _write_week(
        tmp_path,
        2025,
        1,
        [
            {'name': 'Target Coach', 'position': 'HC', 'nfl_team': 'KC', 'score': -2},
            {'name': 'Other Coach', 'position': 'HC', 'nfl_team': 'NYJ', 'score': 4},
        ],
    )
    team = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='A',
        column_index=0,
        players={'HC': [('Target Coach', 'KC', True)]},
    )
    player_score = PlayerScore(name='Target Coach', position='HC', team='KC')
    results = {'Team A': (0, {'HC': [(player_score, True)]})}
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2025, 1, 'NYJ', 'BUF', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF'),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'target coach', 'HC')]
    assert player.opponent_multiplier == pytest.approx(1.2)
    assert player.projected_points == pytest.approx(-1.6)


def test_legacy_bench_zero_is_excluded_but_confirmed_or_started_zeroes_remain(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    # Isolate the bench-zero rule: with the position average also restricted to
    # starters, the arithmetic below would be measuring two rules at once.
    monkeypatch.setattr(projection_module, 'POSITION_MEAN_STARTERS_ONLY', False)
    historical = [
        {'score': 0, 'starter': False},
        {'score': 0, 'starter': True},
        {'score': 0, 'starter': False, 'found': True},
        {'score': 12, 'starter': False},
    ]
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week, details in enumerate(historical, 1):
        _write_week(
            tmp_path,
            2025,
            week,
            [{'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', **details}],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'target qb', 'QB')]
    assert player.sample_size == 3
    assert player.projected_points == 4


def test_projection_trims_highest_and_lowest_ten_percent(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    historical_scores = [0, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 100]
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week, score in enumerate(historical_scores, 1):
        _write_week(
            tmp_path,
            2025,
            week,
            [
                {
                    'name': 'Target QB',
                    'position': 'QB',
                    'nfl_team': 'KC',
                    'score': score,
                    'starter': score != 0,
                }
            ],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'target qb', 'QB')]
    assert player.sample_size == 11
    assert player.projected_points == 15


def test_rookie_uses_position_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    _write_week(
        tmp_path,
        2025,
        1,
        [
            {'name': 'Veteran One', 'position': 'QB', 'nfl_team': 'KC', 'score': 10},
            {'name': 'Veteran Two', 'position': 'QB', 'nfl_team': 'BUF', 'score': 20},
        ],
    )
    team, results = _team_and_results('A', 'Team A', 'Rookie QB', 'LV')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2025, 1, 'BUF', 'NYJ', final=True),
        _schedule_game(2026, 1, 'LV', 'DEN'),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'rookie qb', 'QB')]
    assert player.on_bye is False
    assert player.projected_points == 15
    assert projections.teams['A'].projected_total == 15
    assert projections.teams['A'].starters_remaining == 1


def test_bye_player_has_zero_projection_and_no_remaining_variance(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    team, results = _team_and_results('A', 'Team A', 'Bye QB', 'LV')
    # LV plays in week 2, so week 1 is a real bye rather than an unknown team.
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF'), _schedule_game(2026, 2, 'LV', 'KC')]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'bye qb', 'QB')]
    assert player.on_bye is True
    assert player.projected_points == 0
    assert projections.teams['A'].projected_total == 0
    assert projections.teams['A'].starters_remaining == 0


def test_unknown_nfl_team_keeps_its_projection_instead_of_zeroing(tmp_path, monkeypatch):
    """A team that never appears in the schedule is unknown, not on a bye.

    Blank ``nfl_team`` values in the archives used to make a player project 0
    every week, which is how the D/ST bias in the 2021-2022 replays arose.
    """
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week in range(1, 4):
        _write_week(
            tmp_path,
            2025,
            week,
            [{'name': 'Known QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 12}],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'Mystery QB', '')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'mystery qb', 'QB')]
    assert player.on_bye is False
    # Falls back to the position average rather than a guaranteed zero.
    assert player.projected_points == 12
    # Nothing is known about the matchup, so no opponent adjustment is applied.
    assert player.opponent_multiplier == 1.0


def test_head_coach_projection_follows_the_market_spread(tmp_path, monkeypatch):
    """Coach scoring is a step function of the final margin, so use the line."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'HC': 1})
    game = _schedule_game(2026, 1, 'KC', 'BUF')
    # KC favoured by 14: a 10-19 point win, worth 3.
    game['spread_line'] = 14.0
    game['total_line'] = 48.0
    team, results = _team_and_results('A', 'Team A', 'Andy Reid', 'KC', starter=True)
    team.players['HC'] = team.players.pop('QB')
    results['Team A'][1]['HC'] = results['Team A'][1].pop('QB')
    for player_score, _ in results['Team A'][1]['HC']:
        object.__setattr__(player_score, 'position', 'HC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, [game])

    assert projections.players[('A', 'andy reid', 'HC')].projected_points == 3
    # The underdog is projected to lose by the same margin: -2, give or take the
    # deliberate smoothing around the line.
    assert projection_module._expected_head_coach_points(-14.0) == pytest.approx(-2, abs=0.05)


def test_market_lines_are_optional(tmp_path, monkeypatch):
    """A game with no posted line must fall back to history, not to zero."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week in range(1, 4):
        _write_week(
            tmp_path,
            2025,
            week,
            [{'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 18}],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    assert projections.players[('A', 'target qb', 'QB')].projected_points == 18


def test_team_total_uses_the_unbiased_estimate_not_the_player_projection(tmp_path, monkeypatch):
    """Trimming lowers a player projection; team totals must not inherit that."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    monkeypatch.setattr(projection_module, 'OUTLIER_TRIM_FRACTION_BY_POSITION', {'QB': 0.1})
    monkeypatch.setattr(projection_module, 'PRIOR_GAMES_WEIGHT_BY_POSITION', {'QB': 0})
    monkeypatch.setattr(projection_module, 'PLAYER_POSITION_WEIGHT_BY_POSITION', {'QB': 0})
    # One big week that trimming discards from the player projection.
    scores = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week, score in enumerate(scores, 1):
        _write_week(
            tmp_path,
            2025,
            week,
            [{'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': score}],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    player = projections.players[('A', 'target qb', 'QB')]
    total = projections.teams['A'].projected_total
    assert player.projected_points == 10
    # The team total keeps the outlier, so it sits above the player projection.
    assert total is not None and total > player.projected_points


def test_position_average_ignores_bench_appearances(tmp_path, monkeypatch):
    """The anchor a thin-history player is shrunk toward is the starter average."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week in range(1, 4):
        _write_week(
            tmp_path,
            2025,
            week,
            [
                {'name': 'Starter QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 20},
                {
                    'name': 'Bench QB',
                    'position': 'QB',
                    'nfl_team': 'KC',
                    'score': 0,
                    'starter': False,
                    'found': True,
                },
            ],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'Rookie QB', 'KC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    # A rookie falls back to the position average: the starters' 20, not the
    # 10 that averaging the bench zeroes in would produce.
    assert projections.players[('A', 'rookie qb', 'QB')].projected_points == 20


def test_incomplete_lineup_withholds_team_projection(tmp_path):
    team, results = _team_and_results('A', 'Team A', 'Player One', 'KC')
    projections = calculate_week_projections(
        [team],
        results,
        [],
        2026,
        1,
        tmp_path,
        [_schedule_game(2026, 1, 'KC', 'BUF')],
    )

    assert projections.teams['A'].ready is False
    assert projections.teams['A'].projected_total is None
    assert projections.teams['A'].win_probability is None


def test_incomplete_matchup_withholds_both_team_projections(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    team_a, results_a = _team_and_results('A', 'Team A', 'QB A', 'KC')
    team_b, results_b = _team_and_results('B', 'Team B', 'QB B', 'BUF', starter=False)

    projections = calculate_week_projections(
        [team_a, team_b],
        {**results_a, **results_b},
        [{'team1': 'A', 'team2': 'B'}],
        2026,
        1,
        tmp_path,
        [_schedule_game(2026, 1, 'KC', 'BUF')],
    )

    assert projections.teams['A'].ready is False
    assert projections.teams['A'].projected_total is None
    assert projections.teams['A'].win_probability is None
    assert projections.teams['B'].ready is False
    assert projections.teams['B'].projected_total is None
    assert projections.teams['B'].win_probability is None


def test_final_players_replace_projections_and_set_final_probability(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    team_a, results_a = _team_and_results('A', 'Team A', 'QB A', 'KC', score=30)
    team_b, results_b = _team_and_results('B', 'Team B', 'QB B', 'BUF', score=20)
    results = {**results_a, **results_b}

    projections = calculate_week_projections(
        [team_a, team_b],
        results,
        [{'team1': 'A', 'team2': 'B'}],
        2026,
        1,
        tmp_path,
        [_schedule_game(2026, 1, 'KC', 'BUF', final=True)],
    )

    assert projections.teams['A'].projected_total == 30
    assert projections.teams['B'].projected_total == 20
    assert projections.teams['A'].starters_remaining == 0
    assert projections.teams['A'].win_probability == 1
    assert projections.teams['B'].win_probability == 0


def test_finished_player_uses_actual_while_opponent_keeps_projection(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    for historical_week, score in ((1, 10), (2, 20)):
        _write_week(
            tmp_path,
            2025,
            historical_week,
            [
                {'name': 'QB A', 'position': 'QB', 'nfl_team': 'KC', 'score': score},
                {'name': 'QB B', 'position': 'QB', 'nfl_team': 'NYJ', 'score': score},
            ],
        )
    team_a, results_a = _team_and_results('A', 'Team A', 'QB A', 'KC', score=30)
    team_b, results_b = _team_and_results('B', 'Team B', 'QB B', 'NYJ')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'LA', final=True),
        _schedule_game(2025, 1, 'NYJ', 'MIA', final=True),
        _schedule_game(2025, 2, 'KC', 'LA', final=True),
        _schedule_game(2025, 2, 'NYJ', 'MIA', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF', final=True),
        _schedule_game(2026, 1, 'NYJ', 'MIA'),
    ]

    projections = calculate_week_projections(
        [team_a, team_b],
        {**results_a, **results_b},
        [{'team1': 'A', 'team2': 'B'}],
        2026,
        1,
        tmp_path,
        schedules,
    )

    assert projections.players[('A', 'qb a', 'QB')].projected_points == 15
    assert projections.teams['A'].projected_total == 30
    assert projections.teams['A'].starters_remaining == 0
    assert projections.teams['B'].projected_total == 15
    assert projections.teams['B'].starters_remaining == 1
    assert projections.teams['A'].win_probability > 0.5
    assert projections.teams['A'].win_probability + projections.teams['B'].win_probability == 1


def test_unresolved_probability_is_symmetric_and_live_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    _write_week(
        tmp_path,
        2025,
        1,
        [
            {'name': 'QB A', 'position': 'QB', 'nfl_team': 'KC', 'score': 10},
            {'name': 'QB B', 'position': 'QB', 'nfl_team': 'BUF', 'score': 10},
        ],
    )
    _write_week(
        tmp_path,
        2025,
        2,
        [
            {'name': 'QB A', 'position': 'QB', 'nfl_team': 'KC', 'score': 20},
            {'name': 'QB B', 'position': 'QB', 'nfl_team': 'BUF', 'score': 20},
        ],
    )
    team_a, results_a = _team_and_results('A', 'Team A', 'QB A', 'KC')
    team_b, results_b = _team_and_results('B', 'Team B', 'QB B', 'BUF')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2025, 1, 'BUF', 'NYJ', final=True),
        _schedule_game(2025, 2, 'KC', 'MIA', final=True),
        _schedule_game(2025, 2, 'BUF', 'NYJ', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF'),
    ]

    projections = calculate_week_projections(
        [team_a, team_b],
        {**results_a, **results_b},
        [{'team1': 'A', 'team2': 'B'}],
        2026,
        1,
        tmp_path,
        schedules,
    )

    assert projections.teams['A'].win_probability == pytest.approx(0.5)
    assert projections.teams['B'].win_probability == pytest.approx(0.5)
    assert projections.teams['A'].starters_remaining == 1


def test_save_week_scores_publishes_projection_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    team_a, results_a = _team_and_results('A', 'Team A', 'QB A', 'KC')
    team_b, results_b = _team_and_results('B', 'Team B', 'QB B', 'BUF')
    results = {**results_a, **results_b}
    matchups = [{'team1': 'A', 'team2': 'B'}]
    projections = calculate_week_projections(
        [team_a, team_b],
        results,
        matchups,
        2026,
        1,
        tmp_path,
        [_schedule_game(2026, 1, 'KC', 'BUF')],
    )
    output = tmp_path / 'week_1.json'

    save_week_scores(output, 1, [team_a, team_b], results, matchups, projections)

    saved = json.loads(output.read_text(encoding='utf-8'))
    team = saved['teams'][0]
    player = team['roster'][0]
    assert team['projection_ready'] is True
    assert team['projected_total'] == 0
    assert team['win_probability'] == 0.5
    assert team['starters_remaining'] == 1
    assert player['projected_points'] == 0
    assert player['nfl_opponent'] == 'BUF'
    assert player['nfl_is_home'] is True
    assert player['game_final'] is False
    assert player['on_bye'] is False
    assert player['kickoff'].endswith('+00:00')


def _availability_scenario(tmp_path, *, position='QB', nfl_team='KC', score_history=20):
    """A single-starter team with enough history to project a non-zero score."""
    for week in (1, 2):
        _write_week(
            tmp_path,
            2025,
            week,
            [
                {
                    'name': 'Star Player',
                    'position': position,
                    'nfl_team': nfl_team,
                    'score': score_history,
                }
            ],
        )
    team = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='A',
        column_index=0,
        players={position: [('Star Player', nfl_team, True)]},
    )
    player_score = PlayerScore(name='Star Player', position=position, team=nfl_team)
    results = {'Team A': (0.0, {position: [(player_score, True)]})}
    schedules = [
        _schedule_game(2025, 1, nfl_team, 'MIA', final=True),
        _schedule_game(2025, 2, nfl_team, 'MIA', final=True),
        _schedule_game(2026, 1, nfl_team, 'BUF'),
    ]
    return team, results, schedules


def _project_one(tmp_path, monkeypatch, *, position='QB', **kwargs):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {position: 1})
    team, results, schedules = _availability_scenario(tmp_path, position=position)
    schedules = kwargs.pop('schedule_rows', schedules)
    projections = calculate_week_projections(
        [team],
        results,
        [],
        2026,
        1,
        tmp_path,
        schedules,
        **kwargs,
    )
    return projections, projections.players[('A', 'star player', position)]


def test_projects_zero_for_a_player_ruled_out(tmp_path, monkeypatch):
    _, baseline = _project_one(tmp_path, monkeypatch)
    assert baseline.projected_points > 0

    _, projection = _project_one(
        tmp_path,
        monkeypatch,
        availability={'QB|star player': 'out'},
    )

    assert projection.projected_points == 0
    assert projection.standard_deviation == 0
    assert projection.unavailable_reason == 'out'


def test_questionable_players_keep_their_full_projection(tmp_path, monkeypatch):
    _, baseline = _project_one(tmp_path, monkeypatch)
    # 'questionable' is deliberately absent from the availability lookup.
    _, projection = _project_one(tmp_path, monkeypatch, availability={})

    assert projection.projected_points == baseline.projected_points
    assert projection.unavailable_reason is None


def test_unknown_players_keep_their_projection(tmp_path, monkeypatch):
    _, baseline = _project_one(tmp_path, monkeypatch)
    _, projection = _project_one(
        tmp_path,
        monkeypatch,
        availability={'QB|somebody else': 'out'},
    )

    assert projection.projected_points == baseline.projected_points
    assert projection.unavailable_reason is None


def test_unavailable_starter_contributes_zero_and_is_already_resolved(tmp_path, monkeypatch):
    projections, _ = _project_one(
        tmp_path,
        monkeypatch,
        availability={'QB|star player': 'ir'},
    )
    team_projection = projections.teams['A']

    assert team_projection.projected_total == 0
    assert team_projection.variance == 0
    assert team_projection.starters_remaining == 0


def test_finished_game_beats_a_stale_designation(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    team, results, schedules = _availability_scenario(tmp_path)
    results['Team A'] = (
        18.0,
        {
            'QB': [
                (PlayerScore(name='Star Player', position='QB', team='KC', total_points=18.0), True)
            ]
        },
    )
    schedules[-1] = _schedule_game(2026, 1, 'KC', 'BUF', final=True)

    projections = calculate_week_projections(
        [team],
        results,
        [],
        2026,
        1,
        tmp_path,
        schedules,
        availability={'QB|star player': 'out'},
    )

    # He was listed out but the game is final, so his real points count.
    assert projections.teams['A'].projected_total == 18.0


def test_head_coach_who_is_not_listed_projects_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'HC': 1})
    team, results, schedules = _availability_scenario(tmp_path, position='HC', score_history=3)
    schedules[-1]['home_coach'] = 'New Guy'

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)
    projection = projections.players[('A', 'star player', 'HC')]

    assert projection.projected_points == 0
    assert projection.unavailable_reason == 'not_head_coach'


def test_head_coach_who_is_listed_projects_normally(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'HC': 1})
    team, results, schedules = _availability_scenario(tmp_path, position='HC')
    schedules[-1]['home_coach'] = 'Star Player'

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)
    projection = projections.players[('A', 'star player', 'HC')]

    assert projection.projected_points > 0
    assert projection.unavailable_reason is None


def test_coach_override_beats_a_stale_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'HC': 1})
    team, results, schedules = _availability_scenario(tmp_path, position='HC')
    # nflverse still lists the fired coach; the override names the promoted one.
    schedules[-1]['home_coach'] = 'Fired Coach'

    projections = calculate_week_projections(
        [team],
        results,
        [],
        2026,
        1,
        tmp_path,
        schedules,
        coach_overrides={'KC': 'Star Player'},
    )
    projection = projections.players[('A', 'star player', 'HC')]

    assert projection.projected_points > 0
    assert projection.unavailable_reason is None


def test_coach_check_is_skipped_when_the_schedule_has_no_coaches(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'HC': 1})
    team, results, schedules = _availability_scenario(tmp_path, position='HC')
    # An older snapshot compacted the schedule without the coach columns.
    for row in schedules:
        row.pop('home_coach', None)
        row.pop('away_coach', None)

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    assert projections.players[('A', 'star player', 'HC')].unavailable_reason is None


def test_save_week_scores_publishes_the_unavailable_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    team, results, schedules = _availability_scenario(tmp_path)
    projections = calculate_week_projections(
        [team],
        results,
        [],
        2026,
        1,
        tmp_path,
        schedules,
        availability={'QB|star player': 'exempt'},
    )
    output = tmp_path / 'week_1.json'

    save_week_scores(output, 1, [team], results, [], projections)

    saved = json.loads(output.read_text(encoding='utf-8'))
    player = saved['teams'][0]['roster'][0]
    assert player['projected_points'] == 0
    assert player['unavailable_reason'] == 'exempt'


def test_coach_override_accepts_either_spelling_of_a_team(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'HC': 1})
    team, results, schedules = _availability_scenario(tmp_path, position='HC', nfl_team='LA')
    schedules[-1]['home_coach'] = 'Fired Coach'

    projections = calculate_week_projections(
        [team],
        results,
        [],
        2026,
        1,
        tmp_path,
        schedules,
        coach_overrides={'LAR': 'Star Player'},
    )

    assert projections.players[('A', 'star player', 'HC')].unavailable_reason is None


def test_pregame_total_ignores_results_while_the_live_total_folds_them_in(tmp_path, monkeypatch):
    """The two team lines differ by exactly one thing: whether a finished game's
    real points replace that starter's projection."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    _write_week(
        tmp_path,
        2025,
        1,
        [{'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 10}],
    )
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC', score=31)
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF', final=True),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    projection = projections.teams['A']
    player = projections.players[('A', 'target qb', 'QB')]
    # His game is over, so the live line is his actual 31 and nothing is left
    # to resolve; the pregame line still carries the projection.
    assert projection.projected_total == 31
    assert projection.starters_remaining == 0
    assert projection.pregame_total == pytest.approx(player.projected_points, abs=0.6)
    assert projection.pregame_total != projection.projected_total


def test_pregame_total_matches_the_live_total_before_any_game_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    _write_week(
        tmp_path,
        2025,
        1,
        [{'name': 'Target QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 10}],
    )
    team, results = _team_and_results('A', 'Team A', 'Target QB', 'KC')
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF'),
    ]

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    projection = projections.teams['A']
    assert projection.pregame_total == projection.projected_total
    assert projection.starters_remaining == 1


def test_a_position_the_model_cannot_beat_is_projected_at_the_position_average(
    tmp_path, monkeypatch
):
    """D/ST and OL lose to their own position average, so they are projected at
    it: two starters with opposite histories get the same number."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    monkeypatch.setattr(projection_module, 'POSITION_AVERAGE_WEIGHT_BY_POSITION', {'QB': 1.0})
    monkeypatch.setattr(projection_module, 'OPPONENT_FULL_WEIGHT_SAMPLES', 10**6)
    _write_week(
        tmp_path,
        2025,
        1,
        [
            {'name': 'Hot QB', 'position': 'QB', 'nfl_team': 'KC', 'score': 30},
            {'name': 'Cold QB', 'position': 'QB', 'nfl_team': 'NYJ', 'score': 10},
        ],
    )
    schedules = [
        _schedule_game(2025, 1, 'KC', 'MIA', final=True),
        _schedule_game(2025, 1, 'NYJ', 'DEN', final=True),
        _schedule_game(2026, 1, 'KC', 'BUF'),
        _schedule_game(2026, 1, 'NYJ', 'BUF'),
    ]
    hot_team, hot_results = _team_and_results('A', 'Team A', 'Hot QB', 'KC')
    cold_team, cold_results = _team_and_results('B', 'Team B', 'Cold QB', 'NYJ')

    projections = calculate_week_projections(
        [hot_team, cold_team],
        hot_results | cold_results,
        [],
        2026,
        1,
        tmp_path,
        schedules,
    )

    hot = projections.players[('A', 'hot qb', 'QB')].projected_points
    cold = projections.players[('B', 'cold qb', 'QB')].projected_points
    assert hot == cold == pytest.approx(20.0)


def test_position_average_fallback_uses_the_plain_mean_not_the_blended_one(tmp_path, monkeypatch):
    """The point of the fallback is to match the naive predictor the backtest
    measures against, so it anchors on the untrimmed mean of every starter
    observation rather than the model's own trimmed, prior-blended estimate."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    monkeypatch.setattr(projection_module, 'POSITION_AVERAGE_WEIGHT_BY_POSITION', {'QB': 1.0})
    monkeypatch.setattr(projection_module, 'OUTLIER_TRIM_FRACTION_BY_POSITION', {'QB': 0.1})
    monkeypatch.setattr(projection_module, 'OPPONENT_FULL_WEIGHT_SAMPLES', 10**6)
    # Twelve starter results whose top and bottom would be trimmed away.
    scores = [0, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week, score in enumerate(scores, 1):
        _write_week(
            tmp_path,
            2025,
            week,
            [{'name': f'QB {week}', 'position': 'QB', 'nfl_team': 'KC', 'score': score}],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'New QB', 'KC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    # Plain mean of all twelve is 200/12 = 16.7; trimming the 0 and the 100
    # would give 10.0 instead.
    assert projections.players[('A', 'new qb', 'QB')].projected_points == pytest.approx(16.7)


def test_position_average_fallback_can_anchor_on_the_blended_mean(tmp_path, monkeypatch):
    """The other half of the flag, so the choice stays measurable."""
    monkeypatch.setattr(projection_module, 'STARTER_SLOTS', {'QB': 1})
    monkeypatch.setattr(projection_module, 'POSITION_AVERAGE_WEIGHT_BY_POSITION', {'QB': 1.0})
    monkeypatch.setattr(projection_module, 'POSITION_AVERAGE_USES_PLAIN_MEAN', False)
    monkeypatch.setattr(projection_module, 'OUTLIER_TRIM_FRACTION_BY_POSITION', {'QB': 0.1})
    monkeypatch.setattr(projection_module, 'OPPONENT_FULL_WEIGHT_SAMPLES', 10**6)
    scores = [0, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
    schedules = [_schedule_game(2026, 1, 'KC', 'BUF')]
    for week, score in enumerate(scores, 1):
        _write_week(
            tmp_path,
            2025,
            week,
            [{'name': f'QB {week}', 'position': 'QB', 'nfl_team': 'KC', 'score': score}],
        )
        schedules.append(_schedule_game(2025, week, 'KC', 'MIA', final=True))
    team, results = _team_and_results('A', 'Team A', 'New QB', 'KC')

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, schedules)

    assert projections.players[('A', 'new qb', 'QB')].projected_points == pytest.approx(10.0)
