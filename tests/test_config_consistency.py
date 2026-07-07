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
