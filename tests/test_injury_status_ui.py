from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_current_injury_lookup_is_live_season_only_and_accessible():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "function getCurrentPlayerInjury(playerOrName, position = '')" in app
    assert 'data.is_historical || Number(data.season) !== Number(LIVE_SEASON)' in app
    assert 'data.injuries?.players ? data.injuries : sharedData?.injuries' in app
    assert "function playerInjuryBadge(playerOrName, position = '')" in app
    assert "Injury status: ${details.join(' · ')}" in app
    assert 'aria-label="${escapeHtml(label)}"' in app
    assert 'details.push(`Source: ${report.source}`)' in app


def test_injury_badges_render_on_matchups_lineups_rosters_and_player_profiles():
    app = WEB_APP.read_text(encoding='utf-8')

    assert '${playerInjuryBadge(p)}' in app
    assert '${playerInjuryBadge(player)}' in app
    assert '${playerInjuryBadge(playerData)}' in app
    assert '${playerInjuryBadge(candidate)}' in app
    assert 'playerInjuryBadge(displayName, playerPos || requestedPosition)' in app
    assert app.count('playerInjuryBadge(') >= 13
    assert "'kickoffs', 'injuries', 'lineups'" in app


def test_injury_badge_uses_compact_red_styling():
    styles = WEB_STYLES.read_text(encoding='utf-8')

    start = styles.index('.injury-badge {')
    rule = styles[start : styles.index('}', start)]
    assert 'color: var(--loss);' in rule
    assert 'font-weight: 800;' in rule
    assert 'min-width: 1.25rem;' in rule
