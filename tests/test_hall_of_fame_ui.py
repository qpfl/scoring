from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_league_hall_is_the_single_history_archive():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'data-subview="records">League Hall' in html
    assert 'id="history-lore-tab"' not in html
    assert 'id="history-lore-subview"' not in html
    assert "path: 'data/shared/lore.json'" not in app
    assert 'function renderLeagueLore(' not in app
    assert "route.path.startsWith('history/lore')" in app


def test_league_hall_surfaces_record_sections_without_overview_summary():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'class="league-hof-summary"' not in app
    assert 'class="hof-index"' in app
    for section in (
        'hof-seasons',
        'hof-owners',
        'hof-team-records',
        'hof-player-records',
        'hof-rivalries',
    ):
        assert f'id="{section}"' in app
    assert '.league-hof-summary' not in styles
    assert '.hof-index' in styles


def test_lore_only_backend_and_generated_data_are_removed():
    retired_paths = (
        'api/lore.py',
        'data/league_lore.json',
        'qpfl/lore.py',
        'scripts/export_lore.py',
        'web/data/shared/lore.json',
    )

    for relative_path in retired_paths:
        assert not (PROJECT_ROOT / relative_path).exists()


def test_week_recap_and_champion_links_use_surviving_destinations():
    app = WEB_APP.read_text(encoding='utf-8')

    assert '`#matchups/week/${week.week}`' in app
    assert '`#teams/history/${championAbbrev}`' in app
    assert '`#history/lore/week/${data.season}/${week.week}`' not in app
