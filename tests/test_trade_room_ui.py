"""The trade "Make Room" preview (web/app.js) mirrors the server's roster
rules in api/transaction.py _apply_trade_assets. See
docs/PLAN_trade_roster_moves.md."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def _run(expression: str):
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the trade room UI test')
    app = WEB_APP.read_text(encoding='utf-8')
    constants = re.search(r'const ROSTER_SLOTS = .*?\nconst TAXI_SLOTS = \d+;', app, re.DOTALL)
    start = app.index('function projectTradeRoster')
    end = app.index('function tradeIncomingPlayers', start)
    script = f"""
{constants.group(0)}
{app[start:end]}
process.stdout.write(JSON.stringify({expression}));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _player(name, position, taxi=False):
    return {'name': name, 'position': position, 'taxi': taxi}


CGK = [
    _player('CGK QB', 'QB'),
    *(_player(f'CGK RB{i}', 'RB') for i in range(1, 5)),
    _player('CGK Taxi RB', 'RB', taxi=True),
]
INCOMING = [_player('GSA QB', 'QB'), _player('GSA Taxi RB', 'RB', taxi=True)]


def _project(moves, offseason=False):
    args = ', '.join(json.dumps(value) for value in (CGK, ['CGK QB'], INCOMING, moves, offseason))
    return _run(f'projectTradeRoster({args}).violations')


def test_preview_flags_the_taxi_collision_and_clears_once_room_is_made():
    assert _project({}) == ['2 taxi RB players (max 1 per position)']
    assert _project({'activate': ['GSA Taxi RB']}) == ['5 RB players (max 4)']
    assert _project({'release': ['CGK RB4'], 'activate': ['GSA Taxi RB']}) == []
    assert _project({'release': ['CGK Taxi RB']}) == []


def test_preview_skips_position_limits_in_the_offseason():
    assert _project({'activate': ['GSA Taxi RB']}, offseason=True) == []


def test_candidates_and_pruning():
    args = ', '.join(json.dumps(v) for v in (CGK, ['CGK QB'], INCOMING))
    candidates = _run(f'tradeRoomCandidates({args})')
    assert 'CGK QB' not in {p['name'] for p in candidates['release']}
    assert {p['name'] for p in candidates['activate']} == {'CGK Taxi RB', 'GSA Taxi RB'}

    pruned = _run(
        'pruneTradeRoomMoves('
        + json.dumps({'release': ['CGK QB', 'CGK RB1'], 'activate': ['CGK RB2']})
        + f', tradeRoomCandidates({args}))'
    )
    assert pruned == {'release': ['CGK RB1'], 'activate': []}
