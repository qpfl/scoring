import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def evaluate_lineup_lock(data: dict, week: int, player: dict) -> bool:
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function lineupKickoffForPlayer')
    end = app.index('function getLockedPlayers', start)
    lock_functions = app[start:end]
    script = f"""
let LIVE_SEASON = 2026;
let data = {json.dumps(data)};
let lineupState = {{ week: {week} }};
{lock_functions}
process.stdout.write(JSON.stringify(isPlayerLocked({json.dumps(player)})));
"""
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_live_lineup_lock_ignores_stale_prior_season_game_times():
    site = {
        'season': 2026,
        'is_historical': False,
        'current_week': 0,
        'lineup_week': 1,
        'kickoffs': {'KC': '2999-09-10T00:20:00+00:00'},
        'game_times': {'1': {'KC': '2025-09-04T20:20:00-05:00'}},
    }

    assert evaluate_lineup_lock(site, 1, {'nfl_team': 'KC'}) is False


def test_lineup_lock_uses_live_kickoffs_and_historical_fallback():
    live_site = {
        'season': 2026,
        'is_historical': False,
        'lineup_week': 1,
        'kickoffs': {'LA': '2000-09-10T00:20:00+00:00'},
        'game_times': {'1': {'LAR': '2999-09-10T00:20:00+00:00'}},
    }
    historical_site = {
        'season': 2025,
        'is_historical': True,
        'kickoffs': {'LA': '2999-09-10T00:20:00+00:00'},
        'game_times': {'1': {'LAR': '2000-09-10T00:20:00+00:00'}},
    }

    assert evaluate_lineup_lock(live_site, 1, {'nfl_team': 'LAR'}) is True
    assert evaluate_lineup_lock(live_site, 2, {'nfl_team': 'LAR'}) is False
    assert evaluate_lineup_lock(historical_site, 1, {'nfl_team': 'LAR'}) is True
