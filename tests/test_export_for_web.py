import pytest

from scripts.export_for_web import calculate_bench_scores, calculate_team_stats, parse_player_name


def test_historical_initials_resolve_by_season_and_fantasy_team():
    assert parse_player_name('A. Brown', season=2020, team_abbrev='AYP') == (
        'A.J. Brown',
        'TEN',
    )
    assert parse_player_name('A. Brown', season=2020, team_abbrev='GSA') == (
        'A.J. Brown',
        'TEN',
    )
    assert parse_player_name('A. Brown', season=2020, team_abbrev='CWR') == (
        'Antonio Brown',
        'TB',
    )
    assert parse_player_name('J. Jones', season=2020, team_abbrev='CGK') == (
        'Julio Jones',
        'ATL',
    )
    assert parse_player_name('J. Jones', season=2020, team_abbrev='CWR') == (
        'Julio Jones',
        'ATL',
    )


def test_2021_historical_initials_follow_confirmed_players():
    assert parse_player_name('A. Brown', season=2021, team_abbrev='GSA') == (
        'A.J. Brown',
        'TEN',
    )
    assert parse_player_name('A. Brown', season=2021, team_abbrev='CWR/SLS') == (
        'Antonio Brown',
        'TB',
    )
    assert parse_player_name('J. Jones', season=2021, team_abbrev='CWR/SLS') == (
        'Julio Jones',
        'TEN',
    )


def test_bench_export_scores_def_position_as_dst(monkeypatch):
    calls = []

    class Result:
        total_points = 12

    class Scorer:
        def __init__(self, _season, _week):
            pass

        def score_player(self, name, team, position):
            calls.append((name, team, position))
            return Result()

    class Team:
        abbreviation = 'WJK'
        players = {'DEF': [('Atlanta Falcons', 'ATL', False)]}

    monkeypatch.setattr('qpfl.QPFLScorer', Scorer)
    monkeypatch.setattr('qpfl.excel_parser.parse_roster_from_excel', lambda *_args: [Team()])

    scores = calculate_bench_scores('missing.xlsx', 'Week 1', 1, 2025)

    assert scores[('WJK', 'Atlanta Falcons')] == 12
    assert calls == [('Atlanta Falcons', 'ATL', 'D/ST')]


def test_team_stats_calculate_owner_success_from_optimal_legal_lineups():
    team_a = {
        'abbrev': 'AAA',
        'total_score': 40,
        'roster': [
            {'position': 'QB', 'score': 10, 'starter': True},
            {'position': 'QB', 'score': 20, 'starter': False},
            {'position': 'RB', 'score': 30, 'starter': True},
            {'position': 'RB', 'score': 50, 'starter': False, 'taxi': True},
        ],
    }
    team_b = {
        'abbrev': 'BBB',
        'total_score': 50,
        'roster': [{'position': 'QB', 'score': 50, 'starter': True}],
    }
    weeks = [{'week': 1, 'matchups': [{'team1': team_a, 'team2': team_b}]}]
    standings = [
        {
            'abbrev': 'AAA',
            'name': 'Team A',
            'wins': 0,
            'losses': 1,
            'ties': 0,
            'points_for': 40,
            'points_against': 50,
        },
        {
            'abbrev': 'BBB',
            'name': 'Team B',
            'wins': 1,
            'losses': 0,
            'ties': 0,
            'points_for': 50,
            'points_against': 40,
        },
    ]

    stats = calculate_team_stats(weeks, standings)

    assert stats['AAA']['lineup_actual_points'] == 40
    assert stats['AAA']['lineup_optimal_points'] == 50
    assert stats['AAA']['points_left_on_table'] == 10
    assert stats['AAA']['owner_success_rate'] == pytest.approx(80)
    assert stats['AAA']['points_left_on_table_pct'] == pytest.approx(20)
    assert stats['BBB']['owner_success_rate'] == pytest.approx(100)
