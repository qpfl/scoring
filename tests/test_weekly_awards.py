from qpfl import weekly_facts as wf
from scripts import weekly_awards
from tests.test_pregame import _matchup


def _player(week, name, score, abbrev, position='WR', starter=True):
    return wf.PlayerGame(
        2026, week, f'Week {week}', wf.REGULAR, name.lower(), name, position, abbrev,
        (abbrev,), score, starter,
    )  # fmt: skip


GAMES = _matchup(2026, 3, 'GSA', 121, 'AST', 89) + _matchup(2026, 3, 'CGK', 87, 'S/T', 80)
PLAYERS = [
    _player(3, 'Love', 41, 'GSA', 'QB'),
    _player(3, 'Backup', 45, 'GSA', 'QB', starter=False),
    _player(3, 'Odunze', 12, 'CGK', starter=False),
    _player(3, 'McConkey', 0, 'CGK'),
    _player(3, 'McGowan', 10, 'AST', 'RB'),
    _player(3, 'Bills D', 9, 'AST', 'D/ST'),
]


def _awards(timeline=None):
    return {a['key']: a for a in weekly_awards.week_awards(GAMES, PLAYERS, 2026, 3, timeline)}


def test_scores_and_margins():
    awards = _awards()
    assert (awards['top_score']['team'], awards['top_score']['value']) == ('GSA', 121)
    assert awards['top_score']['detail'] == 'beat {team:AST} 121-89'
    assert (awards['bottom_score']['team'], awards['bottom_score']['value']) == ('S/T', 80)
    assert (awards['blowout']['team'], awards['blowout']['value']) == ('GSA', 32)
    assert (awards['nail_biter']['team'], awards['nail_biter']['value']) == ('CGK', 7)


def test_bench_awards_and_best_player():
    awards = _awards()
    assert (awards['bench_mvp']['subject'], awards['bench_mvp']['value']) == ('Backup', 45)
    # GSA's QB swap (4) is smaller than CGK's WR swap (12).
    blunder = awards['benching_blunder']
    assert (blunder['team'], blunder['value']) == ('CGK', 12)
    assert blunder['detail'] == 'benched Odunze (12) for McConkey (0)'
    assert awards['best_player']['subject'] == 'Love'


def test_best_pickup_needs_an_unrostered_player_and_skips_team_units():
    assert 'best_pickup' not in _awards()
    timeline = {
        (2026, 1): {'love': 'GSA', 'mcgowan': 'AST'},
        # McGowan was a free agent in Week 2.
        (2026, 2): {'love': 'GSA'},
    }
    pickup = _awards(timeline)['best_pickup']
    assert (pickup['subject'], pickup['team'], pickup['value']) == ('McGowan', 'AST', 10)
