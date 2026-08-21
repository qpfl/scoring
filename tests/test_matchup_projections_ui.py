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


def test_matchup_roster_keeps_projection_beside_actual_score():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'Number.isFinite(p.projected_points)' in app
    assert 'Proj ${p.projected_points.toFixed(1)}' in app
    assert '<div class="player-points">${scoreDisplay}${projectionDisplay}</div>' in app
    assert 'p.game_final === true' in app
    assert 'player.on_bye === true' in app


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
