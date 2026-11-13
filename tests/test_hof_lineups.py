from scripts import hof_lineups
from tests.test_hof_records import _owner, _player, _season, _team, _week


def _build(*seasons):
    return hof_lineups.build_lineup_superlatives(list(seasons), _owner)


def test_bench_blunder_pairs_the_swap_and_flags_a_flipped_result():
    gsa = _team(
        'GSA',
        90,
        [
            _player('Starter QB', 'QB', 5),
            _player('Bench QB', 'QB', 30, starter=False),
            _player('Starter WR', 'WR', 85),
        ],
    )
    cgk = _team('CGK', 100, [_player('Their QB', 'QB', 100)])
    block = _build(_season(2025, _week(1, (gsa, cgk))))

    blunder = block['by_season']['2025']['bench_blunders'][0]
    assert blunder['benched']['player'] == 'Bench QB'
    assert blunder['started']['player'] == 'Starter QB'
    assert blunder['margin'] == 25
    # 90 + 25 beats 100.
    assert blunder['flipped'] is True
    assert block['all_time']['bench_blunders'][0]['margin'] == 25


def test_bench_mvps_roll_up_by_player_across_seasons():
    def week(season, number, bench_points):
        gsa = _team(
            'GSA',
            50,
            [_player('Starter', 'QB', 50), _player('Backup', 'QB', bench_points, starter=False)],
        )
        return _season(season, _week(number, (gsa, _team('CGK', 40, [_player('X', 'QB', 40)]))))

    block = _build(week(2024, 1, 20), week(2025, 1, 15))
    assert block['by_season']['2025']['bench_mvps'][0]['points'] == 15
    mvp = block['all_time']['bench_mvps'][0]
    assert (mvp['player'], mvp['points'], mvp['games'], mvp['seasons']) == ('Backup', 35, 2, 2)
    assert block['all_time']['bench_games'][0]['points'] == 20


def test_ghosts_skip_team_units_and_byes_count_as_blunders():
    roster = [
        _player('Zero WR', 'WR', 0),
        _player('Bad Defense', 'D/ST', -4),
        _player('Bad Coach', 'HC', -2),
        {**_player('Bye Guy', 'RB', 0), 'on_bye': True},
        # Listed out but played anyway: no blunder.
        {**_player('Played Through', 'TE', 9), 'unavailable_reason': 'out'},
        {**_player('Sat Out', 'TE', 0), 'unavailable_reason': 'out'},
    ]
    gsa = _team('GSA', 60, roster)
    block = _build(_season(2026, _week(3, (gsa, _team('CGK', 70, [_player('Y', 'QB', 70)])))))
    season = block['by_season']['2026']

    assert [g['player'] for g in season['ghost_starters']] == ['Zero WR']
    assert sorted((u['player'], u['reason']) for u in season['unavailable_starters']) == [
        ('Bye Guy', 'bye'),
        ('Sat Out', 'out'),
    ]
    assert season['unavailable_counts'][0]['count'] == 2


def test_special_teams_decide_a_win_by_more_than_the_margin():
    gsa = _team('GSA', 101, [_player('Good K', 'K', 15), _player('QB', 'QB', 86)])
    cgk = _team('CGK', 100, [_player('Bad K', 'K', 2), _player('QB2', 'QB', 98)])
    block = _build(_season(2025, _week(2, (gsa, cgk))))
    games = block['by_season']['2025']['special_teams']
    assert games == [
        {
            **{k: games[0][k] for k in ('season', 'week', 'week_label', 'team_name', 'owner_code')},
            'team': 'GSA',
            'owner': 'Owner GSA',
            'opponent': 'CGK',
            'score': 101,
            'opponent_score': 100,
            'unit': 'K',
            'gap': 13,
            'margin': 1,
        }
    ]


def test_perfect_lineups_count_games_with_the_best_possible_score():
    perfect = _team('GSA', 50, [_player('A', 'QB', 50), _player('B', 'QB', 10, starter=False)])
    imperfect = _team('GSA', 10, [_player('A', 'QB', 10), _player('B', 'QB', 50, starter=False)])
    other = _team('CGK', 40, [_player('C', 'QB', 40)])
    block = _build(_season(2025, _week(1, (perfect, other)), _week(2, (imperfect, other))))
    row = next(r for r in block['by_season']['2025']['perfect_lineups'] if r['team'] == 'GSA')
    assert (row['count'], row['games'], row['rate']) == (1, 2, 0.5)
