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
    assert 'table-layout: fixed;' in styles
    assert '.standings-table th:nth-child(2)' in styles
    assert 'position: static;' in styles
    assert 'text-overflow: ellipsis;' in styles


def test_mobile_matchups_fill_the_viewport_and_use_a_contained_week_scroller():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in styles
    assert '.week-selector-row .week-selector {' in styles
    assert 'overscroll-behavior-inline: contain;' in styles
    assert 'container.scrollTo({ left: Math.max(0, centeredLeft)' in app
    assert 'matchup-bar' not in app
    assert '.matchup-bar' not in styles


def test_historical_seasons_hide_redundant_matchup_tab_and_update_age():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "document.querySelector('#matchups-view > .subnav')" in app
    assert 'matchupsSubviewNav.hidden = isHistorical;' in app
    assert 'element.hidden = isHistorical;' in app
    assert '.subnav[hidden]' in WEB_STYLES.read_text(encoding='utf-8')


def test_rosters_destination_explains_its_purpose():
    html = WEB_INDEX.read_text(encoding='utf-8')

    assert '<button class="nav-btn" data-view="teams">Rosters</button>' in html
    assert '<div class="page-title">League Rosters</div>' in html
    assert 'Find players, browse every team, review trade blocks, and compare rosters.' in html


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


def test_player_profiles_have_shareable_routes_and_copy_action():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'id="player-modal-copy-link"' in html
    assert '`#player/${encodeURIComponent(profile.profile_key)}`' in app
    assert "route.view === 'player'" in app
    assert 'function copyPlayerProfileLink()' in app


def test_filter_and_selection_state_is_preserved_in_the_hash():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'function parseHashRoute(' in app
    assert 'function replaceRouteParams(' in app
    assert "route.params.get('position')" in app
    assert "activeRouteParams.get('draft')" in app
    assert "route.params.get('team1')" in app
    assert "route.params.get('teams')" in app


def test_filtered_views_report_result_counts():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert "${allMatches.length} ${allMatches.length === 1 ? 'player' : 'players'} found" in app
    assert "${matched.length} ${matched.length === 1 ? 'transaction' : 'transactions'} found" in app
    assert 'class="results-summary"' in app
    assert '.results-summary {' in styles


def test_mobile_subnavigation_is_sticky_and_navigation_moves_focus():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'function focusMainContentOnMobile()' in app
    assert "window.matchMedia('(max-width: 768px)')" in app
    assert '.view-container.active > .subnav,' in styles
    assert 'position: sticky;' in styles


def test_my_team_warns_before_discarding_edits_and_shows_data_freshness():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'function hasUnsavedManageChanges()' in app
    assert "window.addEventListener('beforeunload'" in app
    assert 'You have unsaved My Team changes.' in app
    assert 'function formatRelativeTime(' in app
    assert 'Data may be stale' in app
    assert '.updated.stale {' in styles
