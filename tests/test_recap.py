import dataclasses

from qpfl import recap
from qpfl import weekly_facts as wf
from tests.test_weekly_facts import _matchup


def _texts(recaps, a, b):
    match = next(r for r in recaps if {r['team1'], r['team2']} == {a, b})
    return [wf.render(n['template'], {}) for n in match['notes']]


def _owned(games, owners):
    """Give each side its owner codes, so series follow the people."""
    return [
        dataclasses.replace(g, owners=(owners[g.abbrev],), opp_owners=(owners[g.opp_abbrev],))
        for g in games
    ]


OWNERS = {'GSA': 'griff', 'CGK': 'connor', 'SLS': 'stephen', 'WJK': 'wojo', 'NEW': 'griff'}


def test_series_record_streak_and_blowout_rank():
    games = []
    for week, (gsa, cgk) in enumerate([(100, 90), (95, 90), (80, 70), (99, 98), (90, 85)], 1):
        games += _matchup(2026, week, 'GSA', gsa, 'CGK', cgk)
        games += _matchup(2026, week, 'SLS', 70, 'WJK', 60 + week)
    # Week 6: a 60-point rout, under a new team code for the same owner.
    games += _matchup(2026, 6, 'NEW', 140, 'CGK', 80)
    games += _matchup(2026, 6, 'SLS', 70, 'WJK', 66)
    texts = _texts(recap.generate_recaps(_owned(games, OWNERS), [], 2026, 6), 'NEW', 'CGK')

    assert 'NEW leads the series 6-0 after 6 meetings.' in texts
    # Every meeting is a win, so a streak note would just repeat the record.
    assert not any('straight for' in t for t in texts)
    assert 'The 60-point margin was the largest in 6 meetings between them.' in texts
    assert 'Scorigami: the first 140-80 final in QPFL history.' not in texts  # too little history


def test_evening_the_series_and_snapping_a_run():
    games = []
    for week in range(1, 4):
        games += _matchup(2026, week, 'GSA', 100, 'CGK', 90)
    games += _matchup(2026, 4, 'CGK', 100, 'GSA', 90)
    texts = _texts(recap.generate_recaps(_owned(games, OWNERS), [], 2026, 4), 'CGK', 'GSA')
    assert 'CGK snapped a 3-game losing run against GSA.' in texts
    assert 'GSA still leads the series 3-1 after 4 meetings.' in texts


def test_upset_and_league_rank_notes():
    games = []
    for week in range(1, 31):
        games += _matchup(2025, week % 15 + 1, 'SLS', 90 + week % 7, 'WJK', 80)
    final = _matchup(2026, 1, 'GSA', 160, 'CGK', 60)
    final = [
        dataclasses.replace(g, projected=p, opp_projected=o)
        for g, p, o in zip(final, (80.0, 95.0), (95.0, 80.0), strict=True)
    ]
    texts = _texts(recap.generate_recaps(games + final, [], 2026, 1), 'GSA', 'CGK')
    assert 'An upset: GSA won despite a projected 15-point deficit.' in texts
    assert any(t.startswith('A 100-point win, the largest margin in league history') for t in texts)
    assert 'GSA scored 160, the highest score in league history.' in texts
    assert 'CGK scored 60, the lowest score in league history.' in texts


def test_weekly_notes_win_over_recap_notes_that_say_the_same():
    weekly = [
        {'id': 'h2h_even', 'subjects': ['CWR', 'RPA'], 'template': 'evened', 'notability': 0.6},
        {'id': 'playoff_odds', 'subjects': ['CWR', 'S/T'], 'template': 'other', 'notability': 1},
        {
            'id': 'player_game',
            'subjects': ['CWR'],
            'template': 'Bijan Robinson 50',
            'notability': 1,
        },
    ]
    notes = [
        {'id': 'recap_series_record', 'subjects': ['CWR', 'RPA'], 'template': 'r', 'notability': 0.4},
        {'id': 'recap_series_blowout', 'subjects': ['CWR', 'RPA'], 'template': 'b', 'notability': 0.5},
        {'id': 'recap_top_player', 'subjects': ['CWR'], 'template': 't', 'notability': 0.3,
         'tags': ['Bijan Robinson']},
    ]  # fmt: skip
    merged = recap.merge_with_weekly([{'team1': 'CWR', 'team2': 'RPA', 'notes': notes}], weekly)
    assert [n['template'] for n in merged[0]['notes']] == ['Bijan Robinson 50', 'evened', 'b']
