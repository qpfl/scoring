import json
import re
import subprocess
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


def run_node(script: str):
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


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
    start = app.index("} else if (view === 'matchups') {")
    end = app.index("} else if (view === 'teams') {", start)
    loader = app[start:end]

    assert loader.count('ensureAllSeasonWeeks()') == 2
    assert loader.count("ensureSharedResource('hall_of_fame')") == 2
    assert 'ensureCurrentSeasonFiles({ rosters: true })' in loader


def test_previous_season_home_uses_split_week_files():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('async function ensurePreviousSeasonLoaded()')
    end = app.index('function renderHomeSeason()', start)
    loader = app[start:end]

    assert 'loadSeasonBase(prev)' in loader
    assert 'ensureAllSeasonWeeks(previous)' in loader
    assert 'data_${prev}.json' not in loader


def test_concurrent_week_requests_only_append_the_week_once():
    app = WEB_APP.read_text(encoding='utf-8')
    loader = app[
        app.index('async function ensureSeasonWeek(') : app.index('function seasonWeekNumbers(')
    ]
    script = f"""
const data = null;
const _statsLeadersCache = {{ dataRef: null }};
const weekData = {{ week: 4, has_scores: true, matchups: [] }};
async function fetchJsonResource() {{
    await new Promise(resolve => setImmediate(resolve));
    return weekData;
}}
{loader}
(async () => {{
    const target = {{ season: 2025, weeks: [] }};
    const loaded = await Promise.all([
        ensureSeasonWeek(4, target),
        ensureSeasonWeek(4, target),
    ]);
    process.stdout.write(JSON.stringify({{
        weekCount: target.weeks.length,
        sameResult: loaded[0] === loaded[1],
    }}));
}})();
"""

    assert run_node(script) == {'weekCount': 1, 'sameResult': True}


def test_historical_team_stats_dedupe_weeks_and_exclude_playoffs():
    app = WEB_APP.read_text(encoding='utf-8')
    calculator = app[
        app.index('function calculateTeamStatsFromWeeks(') : app.index(
            'async function ensureAllSeasonWeeks('
        )
    ]
    script = f"""
const REGULAR_SEASON_LAST_WEEK = 15;
{calculator}
const regularWeeks = Array.from({{ length: 15 }}, (_, index) => {{
    const week = index + 1;
    const won = ![1, 2, 3, 10].includes(week);
    return {{
        week,
        has_scores: true,
        matchups: [{{
            team1: {{ abbrev: 'CGK', total_score: won ? 100 : 80 }},
            team2: {{ abbrev: 'S/T', total_score: won ? 80 : 100 }},
        }}],
    }};
}});
const playoffWeeks = [16, 17].map(week => ({{
    week,
    has_scores: true,
    matchups: [{{
        team1: {{ abbrev: 'CGK', total_score: 200 }},
        team2: {{ abbrev: 'S/T', total_score: 50 }},
    }}],
}}));
const stats = calculateTeamStatsFromWeeks({{
    season: 2025,
    standings: [{{
        abbrev: 'CGK',
        wins: 11,
        losses: 4,
        ties: 0,
        points_for: 1493,
        points_against: 1236,
    }}],
    weeks: [...regularWeeks, ...regularWeeks, ...playoffWeeks],
}}).CGK;
process.stdout.write(JSON.stringify({{
    ppg: Number(stats.ppg.toFixed(1)),
    streak: stats.streak,
    bestWeek: stats.best_week,
}}));
"""

    assert run_node(script) == {
        'ppg': 99.5,
        'streak': {'type': 'W', 'count': 5},
        'bestWeek': 100,
    }


def test_season_head_to_head_counts_each_week_once():
    app = WEB_APP.read_text(encoding='utf-8')
    calculator = app[app.index('function getSeasonH2H(') : app.index('function renderH2HBadge(')]
    script = f"""
function sumStarterScores() {{ return 0; }}
const matchup = {{
    team1: {{ abbrev: 'CGK', total_score: 100 }},
    team2: {{ abbrev: 'S/T', total_score: 90 }},
}};
const weeks = [4, 15, 17].flatMap(week => [
    {{ week, has_scores: true, matchups: [matchup] }},
    {{ week, has_scores: true, matchups: [matchup] }},
]);
const data = {{ all_weeks_loaded: true, weeks }};
{calculator}
process.stdout.write(JSON.stringify(getSeasonH2H('CGK', 'S/T')));
"""

    assert run_node(script) == {'wins1': 3, 'wins2': 0, 'ties': 0}


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
