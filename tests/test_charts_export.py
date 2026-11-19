import json
import math

from qpfl import charts
from qpfl.weekly_facts import CONSOLATION, PLAYOFFS, REGULAR, PlayerGame, TeamGame
from scripts import export_charts


def game(season, week, a, sa, b, sb, bracket=REGULAR, optimal=None, owners=None, opp_owners=None):
    """Both sides of one game, the way the history loader yields them."""
    return [
        TeamGame(
            season=season,
            week=week,
            week_label=f'Week {week}',
            bracket=bracket,
            abbrev=a,
            franchises=(a,),
            score=sa,
            opp_abbrev=b,
            opp_franchises=(b,),
            opp_score=sb,
            optimal=optimal,
            owners=owners or (a,),
            opp_owners=opp_owners or (b,),
        ),
        TeamGame(
            season=season,
            week=week,
            week_label=f'Week {week}',
            bracket=bracket,
            abbrev=b,
            franchises=(b,),
            score=sb,
            opp_abbrev=a,
            opp_franchises=(a,),
            opp_score=sa,
            owners=opp_owners or (b,),
            opp_owners=owners or (a,),
        ),
    ]


def test_build_charts_stamps_the_season_and_week_and_every_block():
    block = charts.build_charts(
        [], [], current_season=2026, completed_through=10, names={'GSA': 'Griff'}
    )
    assert block['version'] == charts.CHARTS_VERSION == 2
    assert block['season'] == 2026 and block['completed_through'] == 10
    assert block['names'] == {'GSA': 'Griff'}
    assert set(block) >= {
        'elo',
        'fingerprints',
        'head_to_head',
        'player_nemeses',
        'streaks',
        'scores',
        'season_arcs',
    }


def test_elo_moves_by_margin_counts_each_game_once_and_regresses_between_seasons():
    history = [
        *game(2025, 1, 'A', 130, 'B', 100),
        *game(2025, 1, 'C', 90, 'D', 89),
        *game(2026, 1, 'A', 100, 'B', 100),
        *game(2026, 1, 'C', 50, 'D', 70, bracket=CONSOLATION),
    ]
    elo = charts.elo_history(history)
    assert elo['labels'] == ['2025 W1', '2026 W1']
    # Even teams: a 30-point win moves 24 × ln(31) × 2.2/2.2 × 0.5.
    gain = 24 * math.log(31) * 0.5
    assert elo['series']['A'][0] == round(1500 + gain, 1)
    assert elo['series']['B'][0] == round(1500 - gain, 1)
    # A 1-point win barely moves anyone.
    assert abs(elo['series']['C'][0] - 1500) < 10
    # 2026: a third of the way back to 1500, then a tie (multiplier 1) the
    # favorite loses ground on. The consolation game doesn't count.
    regressed = 1500 + gain * 2 / 3
    assert elo['series']['A'][1] < round(regressed, 1)
    assert elo['current']['D'] == elo['series']['D'][1]


def test_playoff_games_weigh_more():
    regular = charts.elo_history(game(2026, 1, 'A', 120, 'B', 100))
    playoff = charts.elo_history(game(2026, 16, 'A', 120, 'B', 100, bracket=PLAYOFFS))
    # Ratings are stored to one decimal.
    expected = (regular['current']['A'] - 1500) * charts.ELO_PLAYOFF_WEIGHT
    assert abs((playoff['current']['A'] - 1500) - expected) < 0.2


def test_head_to_head_streaks_scores_and_arcs():
    history = [
        *game(2025, 1, 'A', 120, 'B', 100),
        *game(2025, 2, 'A', 110, 'B', 115),
        *game(2026, 1, 'A', 130, 'B', 90),
        *game(2026, 2, 'A', 100, 'B', 95),
        *game(2026, 16, 'A', 100, 'B', 90, bracket=PLAYOFFS),
    ]
    assert charts.head_to_head(history)['A']['B'] == [4, 1, 0, 560.0, 490.0]

    streaks = charts.streaks(history)
    # Regular season only, carried across seasons: A's last two wins.
    assert streaks['wins'][0] == {
        'franchise': 'A',
        'kind': 'W',
        'length': 2,
        'start': [2026, 1],
        'end': [2026, 2],
        'active': True,
    }
    assert streaks['current'] == {'A': ['W', 2], 'B': ['L', 2]}

    assert charts.score_distributions(history)['B'] == [100.0, 115.0, 90.0, 95.0]
    assert charts.season_arcs(history)['A'] == {'2025': [1.0, 1.0], '2026': [1.0, 2.0]}


def test_fingerprints_rank_owners_on_six_traits():
    history = []
    for week in range(1, 15):
        history += game(2026, week, 'A', 120, 'B', 100 + (week % 2) * 30, optimal=120)
    fp = charts.manager_fingerprints(history, {'A': 'Ay', 'B': 'Bee'})
    assert [t['id'] for t in fp['traits']] == [
        'scoring',
        'consistency',
        'lineup_iq',
        'luck',
        'clutch',
        'playoffs',
    ]
    by = {o['code']: o for o in fp['owners']}
    assert by['A']['name'] == 'Ay' and by['A']['games'] == 14
    # B averages 115 to A's 120, but swings 30 points week to week.
    assert by['A']['pct']['scoring'] == 1 and by['B']['pct']['scoring'] == 0
    assert by['A']['values']['consistency'] == 0 and by['B']['values']['consistency'] == 15
    assert by['A']['values']['lineup_iq'] == 1.0 and by['B']['values']['lineup_iq'] is None
    assert by['A']['values']['playoffs'] is None


def test_player_nemeses_count_opposing_starters_only():
    def p(name, score, starter=True):
        return PlayerGame(
            season=2026,
            week=1,
            week_label='Week 1',
            bracket=REGULAR,
            player_key=name.lower(),
            name=name,
            position='QB',
            abbrev='B',
            franchises=('B',),
            score=score,
            starter=starter,
            opp_franchises=('A',),
        )

    result = charts.player_nemeses(
        [p('Josh Allen', 40), p('Josh Allen', 30), p('Benchwarmer', 50, False)]
    )
    assert result == {'A': [['Josh Allen', 'QB', 70.0, 2]]}


def test_export_writes_charts_json(tmp_path, monkeypatch):
    output = tmp_path / 'charts.json'
    monkeypatch.setattr(export_charts, 'load_history', lambda season, week: ([], [], {}, {}))
    monkeypatch.setattr(export_charts, 'owner_names', lambda season: {'GSA': 'Griff'})
    monkeypatch.setattr(
        'sys.argv',
        [
            'export_charts.py',
            '--current-season',
            '2026',
            '--completed-through',
            '3',
            '--output',
            str(output),
        ],
    )
    export_charts.main()
    written = json.loads(output.read_text())
    assert written['completed_through'] == 3 and 'generated_at' in written
    assert written['names']['GSA'] == 'Griff' and written['names']['JRW'] == 'Joe W.'

    # A rerun with the same data leaves the file (and its timestamp) alone.
    stamp = written['generated_at']
    export_charts.main()
    assert json.loads(output.read_text())['generated_at'] == stamp


def test_real_charts_json_stays_small():
    path = export_charts.CHARTS_PATH
    if path.exists():
        assert path.stat().st_size < 300_000
