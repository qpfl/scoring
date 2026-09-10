from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_matchup_header_renders_team_projection_and_win_probability():
    app = WEB_APP.read_text(encoding='utf-8')

    assert (
        'function renderTeamProjection(team, projectedTotal, finalTie = false, '
        'pregameTotal = undefined)' in app
    )
    assert 'Awaiting lineups' in app
    assert 'team.win_probability * 100' in app
    assert '${liveLabel} ${projectedTotal.toFixed(1)}' in app
    assert 'Final tie' in app
    assert '${renderTeamProjection(t1, t1Projected, finalTie, t1Pregame)}' in app
    assert '${renderTeamProjection(t2, t2Projected, finalTie, t2Pregame)}' in app
    assert app.count('<div class="team-score-block">') >= 4

    live_matchups = app[app.index('const matchupsHtml = regularMatchups.map') :]
    t1_score = live_matchups.index('${t1Score.toFixed(0)}</span>')
    t1_projection = live_matchups.index(
        '${renderTeamProjection(t1, t1Projected, finalTie, t1Pregame)}'
    )
    divider = live_matchups.index('<span class="score-divider">—</span>')
    assert t1_score < t1_projection < divider


def test_live_projection_sits_above_the_pregame_one():
    """Two lines: the live projection the win probability is built on, and the
    untouched pregame projection beneath it. A week scored before pregame_total
    existed passes undefined and must keep rendering the original single line."""
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    render = app[app.index('function renderTeamProjection(') : app.index('function pendingMatchup')]
    assert 'const hasPregame = Number.isFinite(pregameTotal);' in render
    assert "const liveLabel = hasPregame ? 'Live' : 'Proj';" in render
    live = render.index('${liveLabel} ${projectedTotal.toFixed(1)}')
    pregame = render.index('Proj ${pregameTotal.toFixed(1)}')
    assert live < pregame
    assert 'team-projection pregame' in render
    assert '.team-projection.pregame {' in styles

    # The mid-bowl two-week total has to carry over on both lines or they
    # silently disagree about which week they describe.
    assert 'if (Number.isFinite(t1Pregame)) t1Pregame += t1Week16;' in app
    assert 'if (Number.isFinite(t2Pregame)) t2Pregame += t2Week16;' in app


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
    assert 'blended with a prior-season baseline' in app
    assert "stabilized toward the player's position average" in app
    assert 'the highest and lowest results trimmed' in app
    assert 'Opponent adjustments are capped at ±20%' in app
    # The two lines and the model's two loudest position-specific rules.
    assert '<strong>Live</strong> counts real points' in app
    assert 'projected straight from the pregame betting spread' in app
    assert 'D/ST and OL are projected at their position average' in app
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


def test_unavailable_players_explain_their_zero_projection():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'const UNAVAILABLE_BADGES = {' in app
    assert "not_head_coach: { label: 'NOT HC'" in app
    assert 'function playerUnavailableBadge(playerOrName)' in app
    # The Sleeper badge wins when both apply, so nobody gets two badges.
    assert 'if (!injury?.abbreviation) return playerUnavailableBadge(playerOrName);' in app
    assert 'UNAVAILABLE_BADGES[player.unavailable_reason]?.detail' in app
    assert 'details.projection, details.unavailable' in app
    assert '.injury-badge.unavailable-badge {' in styles


def test_methodology_mentions_the_availability_gate():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'Players on bye project zero' in app
    assert "no longer their team's listed head coach" in app
