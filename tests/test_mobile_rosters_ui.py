from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = (PROJECT_ROOT / 'web' / 'app.js').read_text()
STYLES_CSS = (PROJECT_ROOT / 'web' / 'styles.css').read_text()


def test_mobile_all_rosters_keeps_spreadsheet_layout_with_column_controls():
    assert 'class="all-rosters-spreadsheet"' in APP_JS
    assert 'class="all-rosters-player-row"' in APP_JS
    assert 'class="roster-column-hide"' in APP_JS
    assert 'class="roster-columns-reset"' in APP_JS
    assert 'data-roster-column=' in APP_JS
    assert '.all-rosters-spreadsheet' in STYLES_CSS
    assert 'position: sticky;' in STYLES_CSS
    assert 'class="roster-row-hide"' not in APP_JS


def test_roster_columns_can_be_hidden_by_team_and_restored():
    assert 'const allRostersHiddenColumns = new Set();' in APP_JS
    assert 'allRostersHiddenColumns.add(button.dataset.team);' in APP_JS
    assert 'element.hidden = allRostersHiddenColumns.has(element.dataset.rosterColumn);' in APP_JS
    assert 'allRostersHiddenColumns.clear();' in APP_JS
    assert 'updateAllRostersColumnVisibility(container);' in APP_JS


def test_team_roster_week_history_uses_contained_horizontal_scroll():
    assert 'class="team-roster-scroll"' in APP_JS
    assert 'Swipe to see weekly scores' in APP_JS
    assert '.team-roster-scroll:not(.taxi-roster-scroll)' in STYLES_CSS
    assert '-webkit-overflow-scrolling: touch' in STYLES_CSS


def test_mobile_shell_limits_page_overflow_and_preserves_touch_targets():
    assert 'overflow-x: clip' in STYLES_CSS
    assert 'min-height: 44px' in STYLES_CSS
    assert '.stats-position-selector' in STYLES_CSS
    assert '.transactions-season-selector' in STYLES_CSS
    assert '.drafts-tabs' in STYLES_CSS


def test_mobile_history_uses_small_banners_and_a_pinned_owner_column():
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in STYLES_CSS
    assert '.owner-stats-table th:first-child' in STYLES_CSS
    assert '.owner-stats-table td:first-child' in STYLES_CSS
    assert 'min-width: 7.5rem;' in STYLES_CSS
