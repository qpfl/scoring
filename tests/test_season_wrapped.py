from scripts import season_wrapped
from scripts.export_weekly_facts import flatten_season, roster_timeline
from tests.test_hof_owners import _player, _season, _team, _week


def _gsa(score, *players):
    return _team('GSA', score, list(players))


def _built():
    weeks = [
        _week(
            1, (_gsa(90, _player('Star', 'QB', 30)), _team('CGK', 100, [_player('Foe', 'QB', 40)]))
        ),
        _week(2, (_gsa(130, _player('Star', 'QB', 50)), _team('RPA', 60))),
        _week(
            3,
            (
                _gsa(110, _player('Star', 'QB', 20), _player('New Guy', 'WR', 25)),
                _team('CGK', 100, [_player('Foe', 'QB', 35)]),
            ),
        ),
    ]
    season = _season(2025, *weeks)
    team_games, player_games = flatten_season(season)
    return season_wrapped.build_season_wrapped(
        season, team_games, player_games, roster_timeline(season, {}), {}
    )['teams']['GSA']


def test_wrapped_collects_the_highs_and_lows():
    gsa = _built()
    assert gsa['record'] == '2-1'
    assert (gsa['best_week']['week'], gsa['best_week']['score']) == (2, 130)
    assert gsa['worst_week']['week'] == 1
    assert gsa['biggest_win']['opponent'] == 'RPA'
    assert gsa['worst_loss']['opponent'] == 'CGK'
    assert (gsa['mvp']['player'], gsa['mvp']['points'], gsa['mvp']['starts']) == ('Star', 100, 3)


def test_revenge_top_add_and_nemesis():
    gsa = _built()
    # Lost to CGK in Week 1, beat them in Week 3.
    assert [g['week'] for g in gsa['revenge_wins']] == [3]
    # New Guy wasn't on any roster in Week 2.
    assert (gsa['top_add']['player'], gsa['top_add']['week']) == ('New Guy', 3)
    assert (gsa['nemesis']['player'], gsa['nemesis']['points']) == ('Foe', 75)
