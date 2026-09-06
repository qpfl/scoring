import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_JS = PROJECT_ROOT / 'web' / 'app.js'
API_CONFIG_JS = PROJECT_ROOT / 'web' / 'api-config.js'
INDEX_HTML = PROJECT_ROOT / 'web' / 'index.html'


def test_api_config_is_loaded_before_app_and_owns_all_endpoints():
    index = INDEX_HTML.read_text(encoding='utf-8')
    app = APP_JS.read_text(encoding='utf-8')
    config = API_CONFIG_JS.read_text(encoding='utf-8')

    assert index.index('src="api-config.js"') < index.index('src="app.js"')
    assert config.count('function originForLocation(') == 1
    assert "hostname === 'qpfl.github.io'" in config
    assert "hostname === 'localhost'" in config
    assert 'return String(location?.origin' in config
    for endpoint in (
        'lineup',
        'nfl-draft',
        'rule-changes',
        'team-avatar',
        'team-name',
        'transaction',
    ):
        assert f"QPFL_API.url('{endpoint}')" in app
    assert ".replace('/lineup'" not in app


def test_inline_javascript_handlers_are_removed():
    index = INDEX_HTML.read_text(encoding='utf-8').lower()
    app = APP_JS.read_text(encoding='utf-8').lower()

    for handler in ('onclick=', 'onerror=', 'onload=', 'onchange='):
        assert handler not in index
        assert handler not in app


def test_password_session_uses_versioned_key_and_legacy_storage_is_deleted():
    """The manage session persists across browser sessions by design.

    It was previously sessionStorage (tab-scoped); it now uses localStorage so
    a refresh or a new tab keeps the user logged in. That means the stored
    credential outlives the tab, so the only storage guarantees left to enforce
    are that it lives under the versioned key alone and that the legacy v1 key
    is always purged.
    """
    app = APP_JS.read_text(encoding='utf-8')

    assert 'localStorage.setItem(GLOBAL_SESSION_KEY' in app
    assert 'localStorage.getItem(GLOBAL_SESSION_KEY' in app
    assert 'localStorage.removeItem(GLOBAL_SESSION_KEY)' in app
    assert 'localStorage.removeItem(LEGACY_LOCAL_SESSION_KEY)' in app

    # The session must not be written anywhere other than the versioned key.
    assert app.count('localStorage.setItem') == 1


def test_pages_has_dedicated_committed_content_deploy():
    workflow = (PROJECT_ROOT / '.github' / 'workflows' / 'deploy-pages.yml').read_text(
        encoding='utf-8'
    )
    score = (PROJECT_ROOT / '.github' / 'workflows' / 'score.yml').read_text(encoding='utf-8')
    transition = (PROJECT_ROOT / '.github' / 'workflows' / 'season-transition.yml').read_text(
        encoding='utf-8'
    )

    assert "- 'web/**'" in workflow
    assert 'actions/checkout@v4' in workflow
    assert 'actions/deploy-pages@v4' in workflow
    assert 'actions/deploy-pages' not in score
    assert 'actions/deploy-pages' not in transition


def test_csp_and_security_headers_are_configured():
    index = INDEX_HTML.read_text(encoding='utf-8')
    vercel = json.loads((PROJECT_ROOT / 'vercel.json').read_text(encoding='utf-8'))
    headers = vercel['routes'][-1]['headers']

    assert 'http-equiv="Content-Security-Policy"' in index
    assert "script-src 'self'" in index
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert 'camera=()' in headers['Permissions-Policy']
