import json
from pathlib import Path

from qpfl import pregame as pg
from qpfl import weekly_facts as wf
from scripts import export_pregame as export
from scripts import export_weekly_facts as facts_export


def _matchup(season, week, a, sa, b, sb, bracket=wf.REGULAR):
    label = f'Week {week}'
    fa, fb = facts_export.franchises_for(a), facts_export.franchises_for(b)
    return [
        wf.TeamGame(season, week, label, bracket, a, fa, sa, b, fb, sb),
        wf.TeamGame(season, week, label, bracket, b, fb, sb, a, fa, sa),
    ]


def _upcoming(season, week, a, b, bracket=wf.REGULAR):
    return _matchup(season, week, a, 0, b, 0, bracket)


def _player(season, week, name, score, abbrev, opp, position='WR', starter=True):
    return wf.PlayerGame(
        season, week, f'Week {week}', wf.REGULAR, name.lower(), name, position, abbrev,
        facts_export.franchises_for(abbrev), score, starter, facts_export.franchises_for(opp),
    )  # fmt: skip


def _roster(name, position='WR', starter=True, projected=None):
    return pg.RosterPlayer(name.lower(), name, position, starter, projected)


def _texts(result, kind, names=None):
    return [wf.render(f['template'], names or {}) for m in result['matchups'] for f in m[kind]]


def _run(team_games, upcoming, player_games=(), rosters=None, **kwargs):
    season, week = upcoming[0].season, upcoming[0].week
    return pg.generate_pregame(
        list(team_games), list(player_games), season, week, upcoming, rosters or {}, **kwargs
    )


def test_last_meeting_and_series_streak():
    games = []
    for week, (gsa, cgk) in enumerate([(80, 90), (100, 90), (110, 90), (120, 90)], start=1):
        games += _matchup(2026, week, 'GSA', gsa, 'CGK', cgk)
    texts = _texts(_run(games, _upcoming(2026, 5, 'GSA', 'CGK')), 'storylines')

    assert 'GSA won the last meeting 120-90 (Week 4, 2026).' in texts
    assert 'GSA has won 3 straight against CGK.' in texts
    # Team-level streaks come from every opponent, not just this one.
    assert 'GSA has won 3 straight.' in texts
    assert 'CGK has lost 3 straight.' in texts
    # The card's head-to-head badge shows the all-time record; notes don't repeat it.
    assert not any('3-1' in t for t in texts)


def test_first_meeting_and_tied_last_meeting():
    games = _matchup(2026, 1, 'GSA', 100, 'CGK', 90) + _matchup(2026, 2, 'GSA', 90, 'CGK', 90)
    texts = _texts(
        _run(games, _upcoming(2026, 3, 'GSA', 'CGK') + _upcoming(2026, 3, 'SLS', 'WJK')),
        'storylines',
    )

    assert 'SLS and WJK meet for the first time.' in texts
    assert 'The last meeting ended in a 90-90 tie (Week 2, 2026).' in texts


def test_notes_only_use_games_before_the_week():
    games = _matchup(2026, 1, 'GSA', 100, 'CGK', 90) + _matchup(2026, 5, 'GSA', 50, 'CGK', 90)
    texts = _texts(_run(games, _upcoming(2026, 5, 'GSA', 'CGK')), 'storylines')

    assert 'GSA won the last meeting 100-90 (Week 1, 2026).' in texts
    assert not any('50' in t for t in texts)


def test_standings_storylines():
    upcoming = (
        _upcoming(2026, 9, 'GSA', 'CGK')
        + _upcoming(2026, 9, 'SLS', 'WJK')
        + _upcoming(2026, 9, 'RPA', 'AST')
    )
    ranks = {'GSA': 1, 'CGK': 2, 'SLS': 3, 'WJK': 4, 'RPA': 5, 'AST': 6}
    texts = _texts(_run([], upcoming, ranks=ranks), 'storylines')

    assert 'First place is on the line: GSA (1st) against CGK (2nd).' in texts
    assert 'A meeting of playoff-position teams: SLS (3rd) and WJK (4th).' in texts
    assert not any('RPA (5th)' in t for t in texts)

    line = _texts(
        _run([], _upcoming(2026, 9, 'RPA', 'AST'), ranks={'RPA': 4, 'AST': 5}), 'storylines'
    )
    assert 'RPA (4th) and AST (5th) meet on either side of the playoff line.' in line


def test_rivalry_week_record():
    games = _matchup(2024, wf.RIVALRY_WEEK, 'GSA', 100, 'CGK', 90)
    games += _matchup(2025, wf.RIVALRY_WEEK, 'GSA', 80, 'CGK', 90)
    games += _matchup(2025, 6, 'GSA', 120, 'CGK', 90)
    texts = _texts(
        _run(games, _upcoming(2026, wf.RIVALRY_WEEK, 'GSA', 'CGK'), is_rivalry=True), 'storylines'
    )

    assert "It's Rivalry Week: GSA is 1-1 against CGK in Rivalry Week games." in texts


def test_revenge_needs_enough_starts_or_a_trade():
    history = [_player(2025, w, 'Mike Evans', 10, 'CGK', 'SLS') for w in range(1, 9)]
    history += [_player(2025, w, 'Short Stint', 10, 'CGK', 'SLS') for w in range(1, 3)]
    history += [_player(2025, w, 'Old Defense', 10, 'CGK', 'SLS', 'D/ST') for w in range(1, 10)]
    # Evans has since played against CGK twice for GSA.
    history += [_player(2026, w, 'Mike Evans', w * 10, 'GSA', 'CGK') for w in (1, 2)]
    rosters = {
        'GSA': [
            _roster('Mike Evans'),
            _roster('Short Stint', starter=False),
            _roster('Old Defense', 'D/ST'),
        ]
    }
    texts = _texts(_run([], _upcoming(2026, 3, 'GSA', 'CGK'), history, rosters), 'revenge')

    assert texts == [
        'Mike Evans faces former team CGK (8 starts, 80 points there, 2025). '
        'Averages 15 in 2 starts against them.'
    ]


def test_revenge_from_a_recent_trade_and_bench_note():
    trade = wf.Trade(
        2026,
        4,
        'Week 4, 2026',
        (
            wf.TradeSide('CGK', ('george kittle',), ('George Kittle',)),
            wf.TradeSide('GSA', ('x',), ('X',)),
        ),
    )
    rosters = {
        'CGK': [_roster('George Kittle', 'TE', starter=False), _roster('Starter', 'QB')],
    }
    texts = _texts(
        _run([], _upcoming(2026, 6, 'CGK', 'GSA'), rosters=rosters, trades=[trade]), 'revenge'
    )

    assert texts == [
        'George Kittle faces former team GSA (traded away Week 4, 2026). On the bench for now.'
    ]

    # Before any lineup is set, nobody is "on the bench".
    unset = {'CGK': [_roster('George Kittle', 'TE', starter=False)]}
    texts = _texts(
        _run([], _upcoming(2026, 6, 'CGK', 'GSA'), rosters=unset, trades=[trade]), 'revenge'
    )
    assert texts == ['George Kittle faces former team GSA (traded away Week 4, 2026).']


def _group(group_id, entries):
    return {'id': group_id, 'entries': [{'rank': i + 1, **e} for i, e in enumerate(entries)]}


def test_player_record_within_reach_skips_own_entry():
    history = [_player(2026, w, 'Ja Marr', 25, 'GSA', 'CGK') for w in range(1, 5)]  # 100 points
    groups = [
        _group(
            'player-season-most-points',
            [
                {'value': 200, 'player': 'Far Away', 'profile_key': 'far', 'season': 2021},
                {'value': 110, 'player': 'Catchable', 'profile_key': 'c', 'season': 2022},
                # The record book already counts this season's 100 points.
                {'value': 100, 'player': 'Ja Marr', 'profile_key': 'ja marr', 'season': 2026},
            ],
        ),
        _group(
            'player-career-most-points',
            [{'value': 104, 'player': 'Career Guy', 'profile_key': 'cg', 'season': 2024}],
        ),
    ]
    rosters = {'GSA': [_roster('Ja Marr', projected=9.0)]}
    texts = _texts(
        _run([], _upcoming(2026, 5, 'GSA', 'CGK'), history, rosters, record_groups=groups),
        'records',
    )

    assert (
        'Ja Marr is 10 points behind Catchable (2022) for 2nd in single-season points, '
        'with 9 projected this week.'
    ) in texts
    # Career lists name the player without a season.
    assert (
        'Ja Marr is 4 points behind Career Guy for 1st in career points, with 9 projected this week.'
    ) in texts


def test_records_need_a_projected_starter():
    history = [_player(2026, w, 'Ja Marr', 25, 'GSA', 'CGK') for w in range(1, 5)]
    groups = [
        _group('player-season-most-points', [{'value': 105, 'player': 'X', 'profile_key': 'x'}])
    ]
    for roster in (
        [_roster('Ja Marr', starter=False, projected=9.0)],
        [_roster('Ja Marr', projected=None)],
    ):
        result = _run(
            [], _upcoming(2026, 5, 'GSA', 'CGK'), history, {'GSA': roster}, record_groups=groups
        )
        assert _texts(result, 'records') == []


def test_starts_and_points_milestones():
    history = [_player(2025, w, 'Vet', 10, 'GSA', 'CGK') for w in range(1, 50)]  # 490 points
    groups = [
        _group(
            'player-career-most-starts',
            [{'value': 49, 'player': 'Old Timer', 'profile_key': 'ot', 'season': 2023}],
        )
    ]
    rosters = {'GSA': [_roster('Vet', projected=12.0)]}
    result = _run([], _upcoming(2026, 1, 'GSA', 'CGK'), history, rosters, record_groups=groups)

    assert _texts(result, 'records') == [
        "Vet's next start would be career start 50, passing Old Timer for 1st all-time."
    ]
    milestones = _texts(result, 'milestones')
    assert 'Vet needs 10 points for 500 career points as a QPFL starter.' in milestones
    assert 'Vet is set for career start 50.' in milestones


def test_team_streak_record_and_owner_milestone():
    games = []
    for week in range(1, 4):
        games += _matchup(2026, week, 'GSA', 100, 'CGK', 90)
    groups = [
        _group(
            'team-longest-win-streak',
            [
                {'value': 6, 'team': 'SLS', 'team_name': 'Six', 'season': 2021, 'week': 9},
                {'value': 4, 'team': 'WJK', 'team_name': 'Four', 'season': 2022, 'week': 3},
                # The running streak is already in the book.
                {'value': 3, 'team': 'GSA', 'team_name': 'Mine', 'season': 2026, 'week': 3},
            ],
        )
    ]
    texts = _texts(_run(games, _upcoming(2026, 4, 'GSA', 'CGK'), record_groups=groups), 'records')
    assert texts == [
        'A win would make it 4 straight for GSA, enough to tie Four (2022) for 2nd on the '
        'longest win streak list.'
    ]

    owned = [
        wf.TeamGame(2026, w, f'Week {w}', wf.REGULAR, 'GSA', ('GSA',), 100, 'CGK', ('CGK',), 90,
                    owners=('GSA',), opp_owners=('CGK',))
        for w in range(1, wf.OWNER_WIN_MILESTONE)
    ]  # fmt: skip
    upcoming = [
        wf.TeamGame(2026, 30, 'Week 30', wf.REGULAR, 'GSA', ('GSA',), 0, 'CGK', ('CGK',), 0,
                    owners=('GSA',), opp_owners=('CGK',)),
        wf.TeamGame(2026, 30, 'Week 30', wf.REGULAR, 'CGK', ('CGK',), 0, 'GSA', ('GSA',), 0,
                    owners=('CGK',), opp_owners=('GSA',)),
    ]  # fmt: skip
    milestones = _texts(_run(owned, upcoming, owner_names={'GSA': 'Griff'}), 'milestones')
    assert f"A win would be Griff's {wf.OWNER_WIN_MILESTONE}th career win." in milestones


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_exporter_reads_week_file_or_falls_back_to_lineups(tmp_path, monkeypatch):
    seasons, data = tmp_path / 'seasons', tmp_path / 'data'
    monkeypatch.setattr(export, 'SEASONS_DIR', seasons)
    monkeypatch.setattr(export, 'DATA_DIR', data)
    _write(
        seasons / '2026' / 'weeks' / 'week_10.json',
        {
            'matchups': [
                {
                    'team1': {
                        'abbrev': 'GSA',
                        'roster': [
                            {'name': 'Josh Allen', 'position': 'QB', 'starter': True,
                             'projected_points': 21.5},
                            {'name': 'Bench Guy', 'position': 'WR', 'starter': False},
                        ],
                    },
                    'team2': {'abbrev': 'CGK', 'roster': []},
                }
            ]
        },
    )  # fmt: skip
    rosters = export.load_rosters(2026, 10)
    assert [(p.name, p.starter, p.projected) for p in rosters['GSA']] == [
        ('Josh Allen', True, 21.5),
        ('Bench Guy', False, None),
    ]

    _write(
        data / 'rosters.json',
        {
            'GSA': [
                {'name': 'Josh Allen', 'position': 'QB'},
                {'name': 'Bench Guy', 'position': 'WR'},
            ]
        },
    )
    _write(
        data / 'lineups' / '2026' / 'week_11.json',
        {'lineups': {'GSA': {'QB': ['Josh Allen'], 'submitted_at': 'x'}}},
    )
    rosters = export.load_rosters(2026, 11)
    assert [(p.name, p.starter) for p in rosters['GSA']] == [
        ('Josh Allen', True),
        ('Bench Guy', False),
    ]


def test_exporter_builds_upcoming_rows_from_the_schedule():
    meta = {
        'schedule': [
            {'week': 5, 'is_rivalry': True, 'matchups': [{'team1': 'GSA', 'team2': 'S/T'}]},
        ]
    }
    rows, is_rivalry = export.upcoming_rows(meta, 2026, 5)

    assert is_rivalry is True
    assert [(r.abbrev, r.opp_abbrev, r.bracket) for r in rows] == [
        ('GSA', 'S/T', wf.REGULAR),
        ('S/T', 'GSA', wf.REGULAR),
    ]
    assert export.upcoming_rows(meta, 2026, 6) == ([], False)


def test_score_workflow_writes_notes_after_the_web_export():
    root = Path(__file__).resolve().parent.parent
    workflow = (root / '.github' / 'workflows' / 'score.yml').read_text()
    export_step = workflow.index('scripts/export_current.py --season')
    pregame_step = workflow.index('scripts/export_pregame.py --season')
    commit_step = workflow.index('- name: Commit and push')
    assert export_step < pregame_step < commit_step
