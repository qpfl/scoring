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
    assert app.count('<div class="team-score-block">') >= 4

    live_matchups = app[app.index('const matchupsHtml = regularMatchups.map') :]
    t1_score = live_matchups.index('${t1Score.toFixed(0)}</span>')
    t1_projection = live_matchups.index('${renderTeamProjection(t1, t1Projected, finalTie)}')
    divider = live_matchups.index('<span class="score-divider">—</span>')
    assert t1_score < t1_projection < divider


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
    assert '.team-score-block {' in styles
    assert '.team-score-block .team-projection {' in styles
    assert '.player-points {' in styles
    assert 'align-items: flex-end;' in styles
    assert '.player-projection {' in styles
    assert 'white-space: nowrap;' in styles


def test_scheduled_matchups_use_the_live_scoreboard_with_submitted_starters():
    app = WEB_APP.read_text(encoding='utf-8')

    matchups_loader = app[
        app.index("} else if (view === 'matchups')") : app.index("} else if (view === 'standings')")
    ]
    assert 'ensureCurrentSeasonFiles({ rosters: true })' in matchups_loader
    assert 'function pendingMatchupTeamData(abbrev, week)' in app
    assert 'Number(week) === activeLineupWeek ? data.lineups?.[abbrev] : null' in app
    assert 'starter: starters.some(name => name.trim().toLowerCase() === normalizedName)' in app
    assert "function renderScheduledMatchupCard(matchup, index, bracket = '')" in app
    assert 'total_score: actualTotal' in app
    assert 'projected_total: projectedTotal' in app
    assert 'projection_ready: starters.length > 0' in app
    assert 'data-matchup="scheduled-${index}"' in app
    assert 'id="roster-scheduled-${index}"' in app
    assert '${renderRoster(t1.roster, currentWeek)}' in app
    assert '${renderRoster(t2.roster, currentWeek)}' in app
    assert '${renderTeamProjection(t1, t1.projected_total)}' in app
    assert '${t1Score.toFixed(0)}' in app
    scheduled = app[
        app.index('function renderScheduledMatchupCard(') : app.index(
            'function renderProjectionMethodology()'
        )
    ]
    t1_score = scheduled.index('${t1Score.toFixed(0)}</span>')
    t1_projection = scheduled.index('${renderTeamProjection(t1, t1.projected_total)}')
    divider = scheduled.index('<span class="score-divider">—</span>')
    assert t1_score < t1_projection < divider
    assert 'matchup preview' not in app.lower()
    assert 'Live scores will replace this preview' not in app


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


def test_schedule_toggle_supports_full_league_and_individual_team_schedules():
    html = (PROJECT_ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'id="matchups-schedule-tab"' in html
    assert 'id="schedule-team-filter"' in html
    assert 'function renderSchedule()' in app
    assert 'matchups: () => { renderWeekSelector(); renderMatchups(); renderSchedule(); }' in app
    assert "const requestedTeam = (route.params.get('team') || 'ALL').toUpperCase();" in app
    assert "viewFresh.delete('matchups');" in app
    assert 'matchup.team1 === currentScheduleTeam || matchup.team2 === currentScheduleTeam' in app
    assert 'replaceRouteParams({ team:' in app
    assert '.schedule-team-focus {' in styles
