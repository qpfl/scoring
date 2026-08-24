from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'
VERCEL_CONFIG = PROJECT_ROOT / 'vercel.json'


def test_league_lore_has_an_accessible_history_tab_and_lazy_resource():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'id="history-lore-tab" role="tab"' in html
    assert 'aria-controls="history-lore-subview"' in html
    assert 'id="history-lore-subview" role="tabpanel"' in html
    assert "path: 'data/shared/lore.json'" in app
    assert "subview === 'lore'" in app
    assert "ensureSharedResource('lore')" in app


def test_lore_supports_week_rivalry_and_yearbook_deep_links():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "kind === 'week'" in app
    assert "kind === 'rivalry'" in app
    assert "kind === 'season'" in app
    assert 'function renderLoreChronicle(' in app
    assert 'function renderLoreRivalry(' in app
    assert 'function renderLoreYearbook(' in app
    assert '#history/lore/week/${data.season}/${week.week}' in app


def test_lore_calls_completed_matchup_pages_weeks():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'Latest Chronicle' not in app
    assert 'Read the Chronicle' not in app
    assert 'Share Chronicle' not in app
    assert 'Chronicle navigation' not in app
    assert '<h2 id="lore-latest-heading">Weeks</h2>' in app
    assert '>Share Week</button>' in app


def test_lore_sharing_prefers_native_share_and_has_clipboard_fallback():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'data-lore-share' in app
    assert 'navigator.share({ title, text, url })' in app
    assert 'async function copyLoreText(' in app
    assert "'Recap and link copied'" in app


def test_lore_layout_has_mobile_specific_rules():
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '.lore-rivalry-grid' in styles
    assert '.lore-matchup-story' in styles
    assert '.lore-yearbook-grid-detail' in styles
    assert '@media (max-width: 700px)' in styles
    assert '.lore-versus,' in styles


def test_superlative_ballot_uses_team_auth_and_lore_api():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')
    vercel = VERCEL_CONFIG.read_text(encoding='utf-8')

    assert 'function renderLoreSuperlativeBallot(' in app
    assert 'data-superlative-vote' in app
    assert 'async function submitSuperlativeVote(' in app
    assert "action: 'vote_superlative'" in app
    assert '.lore-ballot-option.selected' in styles
    assert '"src": "/api/lore"' in vercel
