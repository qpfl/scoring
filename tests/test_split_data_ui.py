import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
TRADE_BLOCK_WORKFLOW = PROJECT_ROOT / '.github' / 'workflows' / 'trade_blocks.yml'
VERCEL_CONFIG = PROJECT_ROOT / 'vercel.json'
VERCEL_IGNORE = PROJECT_ROOT / '.vercelignore'

REQUIRED_BOOTSTRAP_FILES = (
    PROJECT_ROOT / 'web' / 'data' / 'index.json',
    PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2026' / 'meta.json',
    PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2026' / 'standings.json',
    PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2026' / 'live.json',
)


def test_frontend_bootstraps_from_split_season_index_without_legacy_probes():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "fetchJsonResource('data/index.json'" in app
    assert '`data/seasons/${season}/meta.json`' not in app
    assert '`${base}/meta.json`' in app
    assert '`${base}/standings.json`' in app
    assert "fetch('data.json'" not in app
    assert 'data_${currentSeason}.json' not in app
    assert "method: 'HEAD'" not in app
    assert 'detectAvailableSeasons' not in app


def test_large_feature_data_is_loaded_by_view():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "path: 'data/shared/hall_of_fame.json'" in app
    assert "path: 'data/shared/transactions.json'" in app
    assert "path: 'data/shared/drafts.json'" in app
    assert "view === 'transactions'" in app
    assert "ensureSharedResource('transactions')" in app
    assert "view === 'history'" in app
    assert "ensureSharedResource('hall_of_fame')" in app
    assert "view === 'matchups'" in app


def test_matchups_and_standings_load_their_history_dependencies():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index("} else if (view === 'matchups' || view === 'standings') {")
    end = app.index("} else if (view === 'teams') {", start)
    loader = app[start:end]

    assert 'ensureAllSeasonWeeks()' in loader
    assert "ensureSharedResource('hall_of_fame')" in loader


def test_previous_season_home_uses_split_week_files():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('async function ensurePreviousSeasonLoaded()')
    end = app.index('function renderHomeSeason()', start)
    loader = app[start:end]

    assert 'loadSeasonBase(prev)' in loader
    assert 'ensureAllSeasonWeeks(previous)' in loader
    assert 'data_${prev}.json' not in loader


def test_split_runtime_files_have_freshness_and_workflow_coverage():
    workflow = TRADE_BLOCK_WORKFLOW.read_text(encoding='utf-8')
    vercel = VERCEL_CONFIG.read_text(encoding='utf-8')

    assert 'web/data/seasons/*/live.json' in workflow
    assert r'data/seasons/\\d+/(?:meta|standings|live|rosters|draft_picks)' in vercel
    assert 'data/shared/(?:transactions|drafts)' in vercel


def test_vercel_deploy_includes_split_data_tree():
    patterns = {
        line.strip()
        for line in VERCEL_IGNORE.read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    }

    assert '/data/' in patterns
    assert 'data/' not in patterns
    for path in REQUIRED_BOOTSTRAP_FILES:
        assert path.is_file()


def test_vercel_handlers_do_not_import_ignored_project_paths():
    ignored_roots = {'qpfl', 'scripts', 'docs', 'data'}
    api_dir = PROJECT_ROOT / 'api'

    for path in api_dir.glob('*.py'):
        source = path.read_text(encoding='utf-8')
        imports = set(re.findall(r'^from ([A-Za-z0-9_]+)', source, re.M))
        imports.update(re.findall(r'^import ([A-Za-z0-9_]+)', source, re.M))
        assert imports.isdisjoint(ignored_roots), f'{path.name} imports an ignored path'
