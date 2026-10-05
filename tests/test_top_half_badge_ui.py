import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def _top_half(matchups, settled=False):
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function computeTopHalfRanks(')
    end = app.index('function pendingMatchupTeamData(', start)
    escape = app[
        app.index('function escapeHtml(') : app.index('\n}\n', app.index('function escapeHtml('))
        + 3
    ]
    ordinal = app[
        app.index('function ordinalPlace(') : app.index(
            '\n}\n', app.index('function ordinalPlace(')
        )
        + 3
    ]
    script = (
        f'{escape}\n{ordinal}\n{app[start:end]}\n'
        f'const ranks = computeTopHalfRanks({json.dumps(matchups)}, '
        f'{{ settled: {json.dumps(settled)} }});\n'
        'console.log(JSON.stringify({\n'
        '  ranks: Object.fromEntries(ranks),\n'
        '  badges: Object.fromEntries([...ranks.keys()].map(a => [a, renderTopHalfBadge(a, ranks).trim()])),\n'
        f'  lines: Object.fromEntries({json.dumps([t for m in matchups for t in (m["team1"], m["team2"])])}\n'
        f'    .map(t => [t.abbrev, renderScoreRankLine(t, ranks, {json.dumps(not settled)})])),\n'
        '}));'
    )
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _team(abbrev, score, remaining, ready=True):
    return {
        'abbrev': abbrev,
        'total_score': score,
        'starters_remaining': remaining,
        'projection_ready': ready,
    }


def _week(*pairs):
    return [{'team1': _team(*a), 'team2': _team(*b)} for a, b in pairs]


MONDAY = _week(
    (('A', 120, 0), ('B', 60, 2)),
    (('C', 55, 1), ('D', 50, 3)),
    (('E', 100, 0), ('F', 95, 0)),
    (('G', 90, 0), ('H', 40, 0)),
    (('I', 30, 0), ('J', 20, 0)),
)


def test_spot_is_secured_only_when_every_team_still_playing_cannot_push_it_out():
    out = _top_half(MONDAY)
    secured = {a: e['secured'] for a, e in out['ranks'].items() if e['topHalf']}

    # Three teams still playing: 1st and 2nd stay top five even if all three pass.
    assert secured == {'A': True, 'E': True, 'F': False, 'G': False, 'B': False}
    assert 'Top Half - 1' in out['badges']['A'] and 'Currently' not in out['badges']['A']
    assert 'Currently Top Half - 3' in out['badges']['F']
    # A team with starters left is never secured: its own score can still drop.
    assert 'Currently Top Half - 5' in out['badges']['B']
    assert out['badges']['C'] == ''  # 6th: no badge, but still ranked below


def test_every_team_shows_its_scoring_rank_and_starters_left():
    lines = _top_half(MONDAY)['lines']

    assert '1st of 10 in points · all starters done' in lines['A']
    assert '5th of 10 in points · 2 starters left' in lines['B']
    assert '6th of 10 in points · 1 starter left' in lines['C']
    assert '10th of 10 in points · all starters done' in lines['J']


def test_ties_share_a_rank_and_history_hides_starters_left():
    tied = _week(
        (('A', 90, 0), ('B', 90, 0)),
        (('C', 80, 0), ('D', 70, 0)),
    )
    live = _top_half(tied)['lines']
    assert 'T-1st of 4 in points' in live['A'] and 'T-1st of 4 in points' in live['B']
    assert '3rd of 4 in points' in live['C']

    history = _top_half(tied, settled=True)['lines']
    assert 'starters' not in history['A']


def test_finished_teams_with_finished_opponents_are_not_secured_early():
    # GSA's matchup is over, but three teams below can still pass it.
    out = _top_half(
        _week(
            (('SLS', 103, 1), ('GSA', 82, 0)),
            (('CGK', 88, 0), ('WJK', 73, 0)),
            (('S/T', 84, 2), ('CWR', 68, 2)),
            (('RPA', 68, 0), ('J/J', 59, 1)),
            (('AYP', 58, 1), ('AST', 41, 3)),
        )
    )

    assert out['ranks']['GSA'] == {
        'rank': 4,
        'tied': False,
        'total': 10,
        'topHalf': True,
        'secured': False,
    }
    assert 'Currently Top Half - 4' in out['badges']['GSA']


def test_unknown_remaining_counts_as_still_playing_and_history_is_settled():
    pending = _week(
        (('A', 120, 0), ('B', 60, 0, False)),
        (('C', 55, 0, False), ('D', 50, 0, False)),
        (('E', 100, 0), ('F', 95, 0)),
        (('G', 90, 0), ('H', 40, 0)),
        (('I', 30, 0), ('J', 20, 0)),
    )
    # Three teams without projections yet could all still pass F.
    ranks = _top_half(pending)['ranks']
    assert ranks['E']['secured'] is True
    assert ranks['F']['secured'] is False
    assert _top_half(MONDAY, settled=True)['ranks']['B']['secured'] is True
