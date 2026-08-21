import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def test_commissioner_is_a_hidden_my_team_subpage_until_gsa_login():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'data-view="commissioner"' not in html
    commissioner_tab = re.search(r'<button[^>]+id="commissioner-tab"[^>]*>', html)
    assert commissioner_tab
    assert 'data-tab="commissioner"' in commissioner_tab.group()
    assert ' hidden' in commissioner_tab.group()
    assert html.index('id="tx-commissioner"') > html.index('id="manage-panel"')
    assert 'id="commissioner-view"' not in html
    assert "const COMMISSIONER_TEAM = 'GSA';" in app
    assert 'commissionerTab.hidden = !hasCommissionerAccess;' in app
    assert "tabName === 'commissioner' && !isCommissioner()" in app
    assert "'commissioner': 'manage/commissioner'" in app


def test_commissioner_screen_exposes_requested_operations():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    for element_id in (
        'commissioner-add-form',
        'commissioner-release-form',
        'commissioner-reverse-form',
        'commissioner-score-form',
        'commissioner-audit-log',
    ):
        assert f'id="{element_id}"' in html

    for action in ('add', 'release', 'reverse_trade', 'score_adjustment', 'audit_log'):
        assert f"'{action}'" in app

    assert "trade.status === 'accepted'" in app
    assert (
        "trade.status === 'pending'"
        not in app[
            app.index('function populateCommissionerTrades') : app.index(
                'function populateCommissionerControls'
            )
        ]
    )
    assert 'window.confirm(confirmation)' in app


def test_commissioner_requests_reuse_authenticated_gsa_credentials():
    app = WEB_APP.read_text(encoding='utf-8')
    request_start = app.index('async function commissionerRequest')
    request_end = app.index('function commissionerAuditDescription', request_start)
    request = app[request_start:request_end]

    assert 'if (!isCommissioner())' in request
    assert 'team: manageState.team' in request
    assert 'password: manageState.password' in request
    assert "action: 'admin_adjust'" in request
