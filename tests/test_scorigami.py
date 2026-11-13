import dataclasses

from qpfl import scorigami
from qpfl import weekly_facts as wf
from tests.test_weekly_facts import _matchup


def _filler(weeks):
    """Distinct finals to clear the weekly note's history minimum."""
    games = []
    for i in range(weeks):
        season, week = 2020 + i // 14, i % 14 + 1
        games += _matchup(season, week, 'SLS', 60 + i, 'WJK', 30)
    return games


def test_finals_count_each_matchup_once_with_two_week_totals():
    games = _matchup(2025, 1, 'GSA', 100, 'CGK', 90)
    games += _matchup(2025, 2, 'GSA', 80, 'CGK', 0)  # forfeit: not a final
    # Two-week legs: only the final leg counts, at the combined totals.
    first, second = _matchup(2025, 16, 'GSA', 70, 'CGK', 60, two_week=True)
    final_leg = [
        dataclasses.replace(g, week=17, score=s, opp_score=o, result_score=rs, result_opp_score=ro)
        for g, s, o, rs, ro in (
            (first, 50, 80, 120, 140),
            (second, 80, 50, 140, 120),
        )
    ]
    games += [first, second, *final_leg]

    finals = scorigami.finals(games)

    assert [(f.week, f.winner, f.loser, f.score) for f in finals] == [
        (1, 'GSA', 'CGK', (100, 90)),
        (17, 'CGK', 'GSA', (140, 120)),
    ]


def test_build_scorigami_cells_firsts_and_ties():
    games = _matchup(2024, 1, 'GSA', 100, 'CGK', 90)
    games += _matchup(2024, 2, 'SLS', 90, 'WJK', 100)  # same final, other order
    games += _matchup(2024, 3, 'GSA', 85, 'SLS', 85)
    games += _matchup(2025, 1, 'CGK', 120, 'WJK', 70)
    names = {(2024, 2, 'WJK'): 'Wojo'}

    block = scorigami.build_scorigami(games, names)

    assert block['games'] == 4
    assert block['unique'] == 3
    assert block['max_score'] == 120
    top = next(c for c in block['cells'] if (c['w'], c['l']) == (100, 90))
    assert top['count'] == 2
    assert top['first']['week'] == 1 and top['first']['winner'] == 'GSA'
    assert top['latest']['winner'] == 'WJK' and top['latest']['winner_name'] == 'Wojo'
    once = next(c for c in block['cells'] if (c['w'], c['l']) == (120, 70))
    assert 'latest' not in once
    # Newest first-time final first, numbered by when it was new.
    assert [(r['w'], r['l'], r['nth']) for r in block['recent']] == [
        (120, 70, 3),
        (85, 85, 2),
        (100, 90, 1),
    ]
    assert [(t['score'], t['week']) for t in block['ties']] == [(85, 3)]


def test_weekly_note_calls_out_repeats_above_new_finals():
    history = _filler(60)
    history += _matchup(2023, 5, 'GSA', 109, 'CGK', 58)
    week = _matchup(2026, 3, 'CGK', 109, 'GSA', 58)
    week += _matchup(2026, 3, 'RPA', 131, 'AST', 129)

    facts = wf._scorigami_facts(wf.WeekContext(history + week, [], 2026, 3))
    by_id = {f.id: f for f in facts}

    repeat = wf.render(by_id['scorigami_repeat'].template, {})
    assert repeat == (
        'CGK beat GSA 109-58, a final the league had seen only once before '
        '(most recently Week 5, 2023).'
    )
    new = wf.render(by_id['scorigami_new'].template, {})
    assert new == (
        'Scorigami: RPA beat AST 131-129, the first 131-129 final in QPFL history '
        "and the league's 62nd unique final score."
    )
    assert by_id['scorigami_repeat'].notability > by_id['scorigami_new'].notability


def test_weekly_note_folds_several_new_finals_into_one():
    history = _filler(60)
    week = _matchup(2026, 3, 'RPA', 131, 'AST', 129)
    week += _matchup(2026, 3, 'GSA', 140, 'CGK', 20)
    week += _matchup(2026, 3, 'SLS', 60, 'WJK', 30)  # seen in the filler

    facts = wf._scorigami_facts(wf.WeekContext(history + week, [], 2026, 3))
    texts = [wf.render(f.template, {}) for f in facts if f.id == 'scorigami_week']

    assert texts == [
        '2 of 3 games were scorigamis (131-129 and 140-20), first-time finals that take '
        'the league to 62 unique final scores.'
    ]
    assert not any(f.id == 'scorigami_new' for f in facts)


def test_weekly_note_waits_for_enough_history():
    games = _filler(10) + _matchup(2026, 3, 'RPA', 131, 'AST', 129)
    assert wf._scorigami_facts(wf.WeekContext(games, [], 2026, 3)) == []
