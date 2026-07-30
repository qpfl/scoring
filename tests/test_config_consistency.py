"""Season/deadline constants must agree everywhere (docs/ROADMAP_2026.md P3.4).

Vercel doesn't bundle data/, so api/*.py bake CURRENT_SEASON/TRADE_DEADLINE_WEEK
in as constants rather than reading league_config.json. scripts/create_new_season.py
keeps most of these in sync at season transition, but nothing enforces it — a
missed step here silently mis-files lineups/scores/trade-deadline behavior all
season. This test turns "forgot to run the transition script" into a red CI run.
"""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _extract(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    assert match, f'Pattern not found: {pattern}'
    return match.group(1)


def test_current_season_consistent_across_files():
    config = json.loads((PROJECT_ROOT / 'data' / 'league_config.json').read_text())
    config_season = config['current_season']

    transaction_py = (PROJECT_ROOT / 'api' / 'transaction.py').read_text()
    lineup_py = (PROJECT_ROOT / 'api' / 'lineup.py').read_text()
    export_current_py = (PROJECT_ROOT / 'scripts' / 'export_current.py').read_text()
    score_yml = (PROJECT_ROOT / '.github' / 'workflows' / 'score.yml').read_text()

    transaction_season = int(_extract(r'CURRENT_SEASON\s*=\s*(\d{4})', transaction_py))
    lineup_season = int(_extract(r'CURRENT_SEASON\s*=\s*(\d{4})', lineup_py))
    export_default_season = int(_extract(r'season:\s*int\s*=\s*(\d{4})', export_current_py))
    workflow_season = int(_extract(r"CURRENT_SEASON:\s*'(\d{4})'", score_yml))

    assert transaction_season == config_season, (
        f'api/transaction.py CURRENT_SEASON ({transaction_season}) != '
        f'league_config.json current_season ({config_season})'
    )
    assert lineup_season == config_season, (
        f'api/lineup.py CURRENT_SEASON ({lineup_season}) != '
        f'league_config.json current_season ({config_season})'
    )
    assert export_default_season == config_season, (
        f'scripts/export_current.py default season ({export_default_season}) != '
        f'league_config.json current_season ({config_season})'
    )
    assert workflow_season == config_season, (
        f'.github/workflows/score.yml CURRENT_SEASON ({workflow_season}) != '
        f'league_config.json current_season ({config_season})'
    )


def test_trade_deadline_week_consistent_across_files():
    config = json.loads((PROJECT_ROOT / 'data' / 'league_config.json').read_text())
    config_deadline = config['trade_deadline_week']

    transaction_py = (PROJECT_ROOT / 'api' / 'transaction.py').read_text()
    transaction_deadline = int(_extract(r'TRADE_DEADLINE_WEEK\s*=\s*(\d+)', transaction_py))

    assert transaction_deadline == config_deadline, (
        f'api/transaction.py TRADE_DEADLINE_WEEK ({transaction_deadline}) != '
        f'league_config.json trade_deadline_week ({config_deadline})'
    )


def _extract_dict(pattern: str, text: str) -> dict:
    """Extract a `{'QB': 3, 'RB': 4, ...}`-shaped literal and eval it."""
    raw = _extract(pattern, text)
    return eval(raw, {'__builtins__': {}})  # noqa: S307 - trusted repo source, not user input


def test_roster_slots_consistent_across_files():
    """P1.8 was caused by exactly this kind of drift (constants.py's WR:3 vs
    the API/site's WR:2, silently enforced differently). Guard against a
    repeat: qpfl/constants.py, api/transaction.py, and league_config.json
    must all agree on the roster (non-starter) slot limits per position."""
    config = json.loads((PROJECT_ROOT / 'data' / 'league_config.json').read_text())
    config_slots = config['roster_slots']

    constants_py = (PROJECT_ROOT / 'qpfl' / 'constants.py').read_text()
    transaction_py = (PROJECT_ROOT / 'api' / 'transaction.py').read_text()

    constants_slots = _extract_dict(r'ROSTER_SLOTS\s*=\s*(\{[^}]*\})', constants_py)
    transaction_slots = _extract_dict(r'ROSTER_SLOTS\s*=\s*(\{[^}]*\})', transaction_py)

    assert constants_slots == config_slots, (
        f'qpfl/constants.py ROSTER_SLOTS ({constants_slots}) != '
        f'league_config.json roster_slots ({config_slots})'
    )
    assert transaction_slots == config_slots, (
        f'api/transaction.py ROSTER_SLOTS ({transaction_slots}) != '
        f'league_config.json roster_slots ({config_slots})'
    )


def test_starter_slots_consistent_across_files():
    """Same drift class as above, for starter limits: qpfl/constants.py,
    api/lineup.py, league_config.json, and web/app.js must all agree."""
    config = json.loads((PROJECT_ROOT / 'data' / 'league_config.json').read_text())
    config_slots = config['starter_slots']

    constants_py = (PROJECT_ROOT / 'qpfl' / 'constants.py').read_text()
    lineup_py = (PROJECT_ROOT / 'api' / 'lineup.py').read_text()
    app_js = (PROJECT_ROOT / 'web' / 'app.js').read_text()

    constants_slots = _extract_dict(r'STARTER_SLOTS\s*=\s*(\{[^}]*\})', constants_py)
    lineup_slots = _extract_dict(r'MAX_STARTERS\s*=\s*(\{[^}]*\})', lineup_py)

    match = re.search(r'const LINEUP_CONFIG = \{.*?positions:\s*\{(.*?)\n    \}', app_js, re.DOTALL)
    assert match, 'LINEUP_CONFIG.positions block not found in web/app.js'
    app_js_positions = match.group(1)
    app_js_slots = {
        pos: int(max_)
        for pos, max_ in re.findall(r"'([\w/]+)':\s*\{\s*max:\s*(\d+)", app_js_positions)
    }

    assert constants_slots == config_slots, (
        f'qpfl/constants.py STARTER_SLOTS ({constants_slots}) != '
        f'league_config.json starter_slots ({config_slots})'
    )
    assert lineup_slots == config_slots, (
        f'api/lineup.py MAX_STARTERS ({lineup_slots}) != '
        f'league_config.json starter_slots ({config_slots})'
    )
    assert app_js_slots == config_slots, (
        f'web/app.js LINEUP_CONFIG.positions ({app_js_slots}) != '
        f'league_config.json starter_slots ({config_slots})'
    )


def test_taxi_slots_consistent_across_files():
    config = json.loads((PROJECT_ROOT / 'data' / 'league_config.json').read_text())
    config_taxi = config['taxi_slots']

    constants_py = (PROJECT_ROOT / 'qpfl' / 'constants.py').read_text()
    transaction_py = (PROJECT_ROOT / 'api' / 'transaction.py').read_text()

    constants_taxi = int(_extract(r'TAXI_SLOTS\s*=\s*(\d+)', constants_py))
    transaction_taxi = int(_extract(r'TAXI_SLOTS\s*=\s*(\d+)', transaction_py))

    assert constants_taxi == config_taxi, (
        f'qpfl/constants.py TAXI_SLOTS ({constants_taxi}) != '
        f'league_config.json taxi_slots ({config_taxi})'
    )
    assert transaction_taxi == config_taxi, (
        f'api/transaction.py TAXI_SLOTS ({transaction_taxi}) != '
        f'league_config.json taxi_slots ({config_taxi})'
    )


def test_password_checks_use_constant_time_comparison():
    """P2.6: password comparisons must use hmac.compare_digest, not == / !=,
    to avoid a timing side-channel. Guards against a future regression."""
    api_dir = PROJECT_ROOT / 'api'
    offenders = []
    for path in api_dir.glob('*.py'):
        text = path.read_text()
        if re.search(r'password\s*(?:!=|==)\s*expected', text):
            offenders.append(path.name)
    assert offenders == [], f'Found non-constant-time password comparisons in: {offenders}'
