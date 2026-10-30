"""Excel workbook downloads live only in the commissioner tools.

The All Rosters, Pick Tracker and midseason draft pages used to carry export
buttons for any logged-in manager; those are gone.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_public_pages_have_no_export_buttons():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    for marker in ('data-export=', 'id="export-rosters-btn"', 'id="export-draft-board-btn"'):
        assert marker not in html
        assert marker not in app
    assert "action: 'export_workbook'" not in app
    assert '.workbook-export' not in WEB_STYLES.read_text(encoding='utf-8')


def test_commissioner_tools_keep_every_workbook_download():
    app = WEB_APP.read_text(encoding='utf-8')

    for action in ('download_rosters', 'download_draft_board', 'download_midseason_draft_board'):
        assert f"downloadCommissionerWorkbook('{action}'" in app or f"'{action}'," in app
