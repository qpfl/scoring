import re
from pathlib import Path


WEB_APP = Path(__file__).resolve().parent.parent / 'web' / 'app.js'


def function_source(app: str, name: str) -> str:
    match = re.search(rf'^(?:async )?function {name}\(', app, re.MULTILINE)
    assert match, f'{name} not found in web/app.js'
    next_match = re.search(r'^(?:async )?function \w+\(', app[match.end():], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(app)
    return app[match.start():end]


def test_load_data_can_bypass_the_shared_and_browser_caches():
    app = WEB_APP.read_text(encoding='utf-8')
    load_data = function_source(app, 'loadData')

    assert 'if (!sharedData || forceRefresh)' in load_data
    assert "cache: forceRefresh ? 'no-store' : 'default'" in load_data


def test_game_window_refresh_requests_fresh_data():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "loadData(null, { forceRefresh: true });" in function_source(app, 'checkRefresh')


def test_roster_and_trade_actions_request_fresh_data():
    app = WEB_APP.read_text(encoding='utf-8')
    refresh_call = "loadData(null, { forceRefresh: true })"

    for function_name in (
        'executeTaxiActivation',
        'executeFaActivation',
        'executeRelease',
        'executeTradeProposal',
        'executeTradeResponse',
        'cancelTrade',
        'saveTradeBlock',
    ):
        assert refresh_call in function_source(app, function_name), function_name
