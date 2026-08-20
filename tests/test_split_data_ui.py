from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
TRADE_BLOCK_WORKFLOW = PROJECT_ROOT / '.github' / 'workflows' / 'trade_blocks.yml'
VERCEL_CONFIG = PROJECT_ROOT / 'vercel.json'


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
    assert 'await ensureSeasonWeek(currentWeek)' in app


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
