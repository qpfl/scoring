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
        'commissioner-conditional-form',
        'commissioner-downloads',
        'commissioner-download-rosters',
        'commissioner-download-draft',
        'commissioner-download-status',
        'commissioner-score-form',
        'commissioner-audit-log',
    ):
        assert f'id="{element_id}"' in html

    for action in (
        'add',
        'release',
        'reverse_trade',
        'conditional_picks',
        'resolve_conditional_pick',
        'download_rosters',
        'download_draft_board',
        'score_adjustment',
        'audit_log',
    ):
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


def test_commissioner_workbook_downloads_decode_authenticated_export_responses():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function saveCommissionerWorkbook')
    end = app.index('function commissionerAuditDescription', start)
    download_code = app[start:end]

    assert 'atob(result.content_base64)' in download_code
    assert 'new Blob([bytes]' in download_code
    assert 'link.download = result.filename' in download_code
    assert 'commissionerRequest(adminAction, payload)' in download_code
    assert "adminAction === 'download_draft_board'" in download_code


def test_commissioner_conditional_tool_shows_context_and_submits_resolution_details():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    for element_id in (
        'commissioner-conditional-group',
        'commissioner-conditional-details',
        'commissioner-conditional-pick',
        'commissioner-conditional-owner',
        'commissioner-conditional-reason',
        'commissioner-conditional-status',
    ):
        assert f'id="{element_id}"' in html

    conditional_start = app.index('function commissionerConditionalGroups')
    conditional_end = app.index('function populateCommissionerControls', conditional_start)
    conditional_controls = app[conditional_start:conditional_end]
    assert 'pick.condition' in conditional_controls
    assert 'pick.conditional_claim' in conditional_controls
    assert 'commissionerConditionalPickLabel(pick)' in conditional_controls
    assert '<strong>Candidate picks:</strong>' in conditional_controls
    assert "commissionerRequest('conditional_picks')" in conditional_controls
    assert '(commissionerConditionalPicks || []).forEach' in conditional_controls

    form_start = app.index("document.getElementById('commissioner-conditional-form').onsubmit")
    form_end = app.index("document.getElementById('commissioner-score-form').onsubmit", form_start)
    form = app[form_start:form_end]
    assert 'condition: groupSelect.value' in form
    assert 'winning_pick_id: pickSelect.value' in form
    assert 'final_owner: ownerSelect.value' in form
    assert "'resolve_conditional_pick'" in form
    assert 'Other candidate picks keep their current owners.' in form


def test_commissioner_requests_reuse_authenticated_gsa_credentials():
    app = WEB_APP.read_text(encoding='utf-8')
    request_start = app.index('async function commissionerRequest')
    request_end = app.index('function commissionerAuditDescription', request_start)
    request = app[request_start:request_end]

    assert 'if (!isCommissioner())' in request
    assert 'team: manageState.team' in request
    assert 'password: manageState.password' in request
    assert "action: 'admin_adjust'" in request
