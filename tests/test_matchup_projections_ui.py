from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_matchup_header_renders_team_projection_and_win_probability():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'function renderTeamProjection(team, projectedTotal, finalTie = false)' in app
    assert 'Awaiting lineups' in app
    assert 'team.win_probability * 100' in app
    assert 'Proj ${projectedTotal.toFixed(1)}' in app
    assert 'Final tie' in app
    assert '${renderTeamProjection(t1, t1Projected, finalTie)}' in app
    assert '${renderTeamProjection(t2, t2Projected, finalTie)}' in app


def test_matchup_roster_stacks_actual_above_projection_and_moves_game_time():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'Number.isFinite(p.projected_points)' in app
    assert 'Proj ${p.projected_points.toFixed(1)}' in app
    assert 'const score = Number.isFinite(p.score) ? p.score : 0;' in app
    assert '<div class="player-points">${scoreDisplay}${projectionDisplay}</div>' in app
    assert 'p.game_final === true' in app
    assert 'player.on_bye === true' in app
    assert 'player.nfl_is_home === false' in app
    assert 'class="player-game-context"' in app
    assert 'class="player-game-time ${escapeHtml(gameDetails.colorClass)}"' in app


def test_modern_kickoff_context_preserves_historical_fallback():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'player.kickoff || currentKickoffs[playerTeam]' in app
    assert 'data.game_times && data.game_times[weekKey]' in app
    assert 'hasProjectionContext' in app
    assert (
        "if (!hasProjectionContext && !gameTimes) return { status: 'unknown', label: '' };" in app
    )


def test_projection_styles_are_compact_and_responsive():
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '.team-projection {' in styles
    assert 'flex-wrap: wrap;' in styles
    assert '.team-win-probability {' in styles
    assert '.player-points {' in styles
    assert 'align-items: flex-end;' in styles
    assert '.player-projection {' in styles
    assert 'white-space: nowrap;' in styles


def test_pending_regular_matchups_show_live_rosters_and_submitted_starters():
    app = WEB_APP.read_text(encoding='utf-8')

    matchups_loader = app[
        app.index("} else if (view === 'matchups')") : app.index("} else if (view === 'standings')")
    ]
    assert 'ensureCurrentSeasonFiles({ rosters: true })' in matchups_loader
    assert 'function pendingMatchupTeamData(abbrev, week)' in app
    assert 'Number(week) === activeLineupWeek ? data.lineups?.[abbrev] : null' in app
    assert 'starter: starters.some(name => name.trim().toLowerCase() === normalizedName)' in app
    assert 'data-matchup="pending-regular-${idx}"' in app
    assert 'id="roster-pending-regular-${idx}"' in app
    assert '${renderRoster(t1.roster, currentWeek)}' in app
    assert '${renderRoster(t2.roster, currentWeek)}' in app
    assert 'Week ${currentWeek} matchup preview' in app
    assert 'Submitted starters are highlighted below.' in app


def test_set_lineup_uses_live_game_context_and_projections():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'function renderPlayerGameSummary(player, weekNum)' in app
    assert 'week === activeLineupWeek && data.rosters?.[teamAbbrev]' in app
    assert '.map(p => ({ ...p, score: 0, starter: false }))' in app
    assert '${renderPlayerGameSummary(p, lineupState.week)}' in app
    assert '.player-game-summary {' in styles


def test_matchups_explain_projection_methodology_in_all_week_states():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'function renderProjectionMethodology()' in app
    assert 'two-game-weighted prior-season baseline' in app
    assert "stabilized toward the player's position average" in app
    assert 'the highest and lowest 10% are trimmed' in app
    assert 'Opponent adjustments are capped at ±20%' in app
    assert 'Projections never affect official scoring.' in app
    assert app.count('renderProjectionMethodology()') >= 5
    assert '.projection-methodology {' in styles


def test_matchups_have_one_week_view_and_keep_old_schedule_links_compatible():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'function renderSchedule()' not in app
    assert "matchups: () => { renderWeekSelector(); renderMatchups(); }" in app
    assert "'schedule': 'matchups/week'" in app
    assert "'matchups/schedule': 'matchups/week'" in app
