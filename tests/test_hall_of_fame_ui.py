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


def test_hall_of_fame_shows_this_weeks_facts_from_the_generated_file():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '<div id="hof-weekly-facts"></div>' in app
    assert 'renderWeeklyFactsCard().catch(() => {});' in app
    # The latest completed week from the Hall of Fame marker; a missing file is quiet.
    assert 'data?.hall_of_fame?.completed_through?.[String(season)]' in app
    assert (
        'fetchJsonResource(`data/seasons/${season}/facts/week_${week}.json`, { optional: true })'
        in app
    )
    assert 'if (!headline.length || !slot.isConnected) return;' in app
    # Team tokens show the newsletter's owner names, with the team name on hover.
    assert '.split(/(\\{(?:team|has|is):[^}]+\\})/)' in app
    assert 'const ownerNames = facts.names || {};' in app
    assert 'ownerNames[abbrev] || normalizeCoOwnerLabel(teams[abbrev]?.owner) || abbrev' in app
    # Verbs agree with co-owned names: "Spencer/Tim have".
    assert "const pluralVerbs = { has: 'have', is: 'are' };" in app
    assert "if (kind !== 'team') return isPluralName(owner) ? pluralVerbs[kind] : kind;" in app
    assert '`<span title="${escapeHtml(teamName)}">${escapeHtml(owner)}</span>`' in app
    for selector in ('.hof-weekly-facts-week', '.hof-weekly-facts-list', '.hof-weekly-facts-more'):
        assert selector in styles
