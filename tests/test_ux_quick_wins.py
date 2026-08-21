from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_current_homepage_cards_link_to_full_views():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'id="home-matchups-footer"' in html
    assert 'id="home-current-standings-footer"' in html
    assert 'id="home-current-transactions-footer"' in html
    assert "setHomeCardLink('home-matchups-footer'" in app
    assert 'data-route="#transactions" role="link" tabindex="0"' in app
    assert 'data-route="#matchups/week/${currentWeek}"' in app


def test_standings_are_touch_scrollable_and_have_a_visible_glossary():
    html = WEB_INDEX.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'class="standings-scroll" role="region"' in html
    assert 'aria-describedby="standings-help"' in html
    assert '<summary>How to read the standings</summary>' in html
    assert '<dt>xW-xL</dt>' in html
    assert '.standings-scroll {' in styles
    assert 'min-width: 760px;' in styles
    assert '.standings-table th:nth-child(2)' in styles
    assert 'position: sticky;' in styles


def test_all_rosters_has_player_and_owner_search():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'id="all-rosters-search"' in html
    assert 'id="all-rosters-search-results"' in html
    assert 'function updateAllRostersSearch()' in app
    assert 'data-player-search=' in app
    assert 'teamProfileButton(entry.abbrev, entry.teamName)' in app


def test_player_profiles_are_shared_across_public_and_my_team_surfaces():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'function playerProfileButton(' in app
    assert "e.target.closest('.player-profile-trigger')" in app
    assert "target.closest('#manage-view')" not in app
    assert "playerProfileButton(p.name, '', null, p.position)" in app
    assert "playerProfileButton(player.name, '', null, player.position)" in app
    assert "playerProfileButton(candidate.name, '', null, candidate.position)" in app
    assert (
        "playerProfileButton(player.name, 'trade-block-player-name', null, player.position)" in app
    )
    assert 'renderLineupEditor()' in app
    assert 'renderDepthChartTab()' in app


def test_team_names_link_to_roster_pages():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'function teamProfileButton(' in app
    assert "e.target.closest('.team-profile-trigger')" in app
    assert '`#teams/roster/${encodeURIComponent(abbrev)}`' in app
    assert "teamProfileButton(t1.abbrev, t1.name, 'team-name')" in app


def test_browser_metadata_tracks_the_active_view():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert '<meta name="description"' in html
    assert '<meta name="theme-color" content="#15171f">' in html
    assert '<meta property="og:title"' in html
    assert '<meta property="og:image"' in html
    assert 'function updatePageMetadata(' in app
    assert '`Week ${detail || currentWeek} Matchups · QPFL`' in app


def test_empty_states_offer_recovery_actions():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'function emptyStateHtml(' in app
    assert "{ label: 'Clear filters', action: 'clear-transaction-filters' }" in app
    assert "{ label: 'Return to current season', action: 'current-season' }" in app
    assert "{ label: 'View schedule', route: '#matchups/schedule' }" in app
    assert "e.target.closest('[data-empty-action]')" in app
    assert '.empty-state-action {' in styles


def test_player_profiles_distinguish_offensive_lines_from_defenses():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'data-player-position=' in app
    assert 'function playerProfileIdentityKey(' in app
    assert "normalizedPosition === 'D/ST' || normalizedPosition === 'OL'" in app
    assert "selection.expansion ? 'Expansion acquisition' : 'Drafted'" in app
