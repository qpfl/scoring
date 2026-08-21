from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = (PROJECT_ROOT / 'web' / 'app.js').read_text()
STYLES_CSS = (PROJECT_ROOT / 'web' / 'styles.css').read_text()


def test_mobile_all_rosters_uses_expandable_team_cards():
    assert 'class="all-rosters-desktop"' in APP_JS
    assert 'class="all-rosters-mobile"' in APP_JS
    assert 'class="mobile-roster-card"' in APP_JS
    assert 'class="mobile-roster-position"' in APP_JS
    assert '.all-rosters-desktop' in STYLES_CSS
    assert '.all-rosters-mobile' in STYLES_CSS
    assert '.mobile-roster-card summary' in STYLES_CSS


def test_mobile_roster_search_filters_teams_positions_and_players():
    assert "document.querySelectorAll('.mobile-roster-card')" in APP_JS
    assert 'positionGroup.hidden = Boolean(query) && !positionHasMatch;' in APP_JS
    assert 'card.hidden = Boolean(query) && !hasMatch;' in APP_JS
    assert 'if (query && hasMatch) card.open = true;' in APP_JS


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
