from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_league_hall_is_the_single_history_archive():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'data-subview="records">Hall of Fame' in html
    assert 'data-view="history">League</a>' in html
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
    assert 'data-page-section=' in app
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

    assert '`#matchups/week/${previousWeekNumber}`' in app
    assert '`#teams/history/${championAbbrev}`' in app
    assert '`#history/lore/week/${data.season}/${week.week}`' not in app


def test_head_to_head_badges_show_ties_as_the_third_record_number():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function renderH2HBadge(')
    end = app.index('function buildRostersFromWeeks()', start)
    renderer = app[start:end]

    assert 'allTime.ties ? `–${allTime.ties}`' in renderer
    assert 'season.ties ? `–${season.ties}`' in renderer
    assert '${allTime.ties}T' not in renderer
    assert '${season.ties}T' not in renderer


def test_weekly_facts_load_from_the_generated_file_for_any_week():
    app = WEB_APP.read_text(encoding='utf-8')
    loader = app[
        app.index('async function loadWeeklyFacts(season, week)') : app.index(
            'async function renderMatchupWeeklyFacts('
        )
    ]

    # One file per week; a missing file is quiet.
    assert (
        'fetchJsonResource(`data/seasons/${season}/facts/week_${week}.json`, { optional: true })'
        in loader
    )
    assert 'if (!headline.length) return null;' in loader
    # Team tokens show the newsletter's owner names, with the team name on hover.
    assert '.split(/(\\{(?:team|has|is):[^}]+\\})/)' in loader
    assert 'const ownerNames = facts.names || {};' in loader
    assert 'ownerNames[abbrev] || normalizeCoOwnerLabel(teams[abbrev]?.owner) || abbrev' in loader
    # Verbs agree with co-owned names: "Spencer/Tim have".
    assert "const pluralVerbs = { has: 'have', is: 'are' };" in loader
    assert "if (kind !== 'team') return isPluralName(owner) ? pluralVerbs[kind] : kind;" in loader
    assert '`<span title="${escapeHtml(teamName)}">${escapeHtml(owner)}</span>`' in loader


def test_matchups_page_shows_the_viewed_weeks_facts():
    """The notes stay with their week instead of being replaced every week."""
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    live_matchups = app[app.index('const matchupsHtml = regularMatchups.map') :]
    slot = live_matchups.index('<div id="matchup-weekly-facts" class="matchup-weekly-facts-slot"></div>')
    scoreboard = live_matchups.index('renderProjectionScoreboard(currentWeek)')
    assert slot < scoreboard
    assert 'renderMatchupWeeklyFacts(currentSeason, currentWeek).catch(() => {});' in live_matchups

    renderer = app[
        app.index('async function renderMatchupWeeklyFacts(') : app.index(
            'async function renderWeeklyFactsCard()'
        )
    ]
    assert 'const notes = await loadWeeklyFacts(season, week);' in renderer
    # Switching weeks replaces the slot; a stale response must not land.
    assert 'if (!notes || !slot.isConnected) return;' in renderer
    assert '<details class="weekly-facts-more">' in renderer
    for selector in (
        '.weekly-facts-week',
        '.weekly-facts-list',
        '.weekly-facts-more',
        '.matchup-weekly-facts-slot:empty',
    ):
        assert selector in styles


def test_hall_of_fame_teases_the_latest_weeks_facts():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '<div id="hof-weekly-facts"></div>' in app
    assert 'renderWeeklyFactsCard().catch(() => {});' in app
    teaser = app[
        app.index('async function renderWeeklyFactsCard()') : app.index(
            '// null until the view first renders'
        )
    ]
    # The latest completed week from the Hall of Fame marker.
    assert 'data?.hall_of_fame?.completed_through?.[String(season)]' in teaser
    assert 'list(headline.slice(0, HOF_WEEKLY_FACTS_TEASER))' in teaser
    assert 'matchupLink(season, week,' in teaser
    assert '<details' not in teaser
    assert '.weekly-facts-link' in styles
