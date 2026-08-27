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


def _write_week(root: Path, season: int, week: int, players: list[dict]) -> None:
    path = root / str(season) / 'weeks' / f'week_{week}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                'week': week,
                'teams': [
                    {
                        'abbrev': 'HIST',
                        'roster': players,
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

    projections = calculate_week_projections([team], results, [], 2026, 1, tmp_path, [])

    player = projections.players[('A', 'bye qb', 'QB')]
    assert player.on_bye is True
    assert player.projected_points == 0
    assert projections.teams['A'].projected_total == 0
    assert projections.teams['A'].starters_remaining == 0


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
