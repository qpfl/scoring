"""Managers & rivalries charts (web/charts-managers.js), run in node."""

import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX

WEB = WEB_APP.parent
SCRIPTS = ('charts.js', 'tok.js', 'charts-standings.js', 'charts-luck.js', 'charts-managers.js')


def run_charts(body: str):
    sources = '\n'.join((WEB / name).read_text(encoding='utf-8') for name in SCRIPTS)
    script = f"""
{sources}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


INPUT = """{
    version: '2026-10', season: 2026, franchises: ['GSA', 'CGK', 'AYP'],
    names: { GSA: 'Griff', CGK: 'Kaminska', AYP: 'Arnav' },
    ownerStats: [
        { Owner: 'Griff', Code: 'GSA', Seasons: '7', Record: '64-33-1', 'Win%': '65.3%', Rings: '3' },
        { Owner: 'Kaminska', Code: 'CGK', Seasons: '7', Record: '65-30-3', 'Win%': '66.3%', Rings: '1' },
        { Owner: 'One Year', Code: 'OYR', Seasons: '1', Record: '7-3', 'Win%': '70.0%', Rings: '0' },
    ],
    charts: {
        elo: { labels: ['2025 W1', '2025 W2', '2026 W1'],
               series: { GSA: [1510, 1520, 1505], CGK: [1490, 1500, 1600], AYP: [null, 1480, 1450] },
               current: { GSA: 1505, CGK: 1600, AYP: 1450 } },
        head_to_head: {
            GSA: { CGK: [6, 8, 1, 1410, 1380], AYP: [12, 1, 0, 1338, 1018] },
            CGK: { GSA: [8, 6, 1, 1380, 1410], AYP: [3, 0, 0, 300, 250] },
            AYP: { GSA: [1, 12, 0, 1018, 1338], CGK: [0, 3, 0, 250, 300] },
        },
        player_nemeses: { GSA: [['Josh Allen', 'QB', 401, 14]] },
        streaks: {
            wins: [{ franchise: 'CGK', kind: 'W', length: 12, start: [2025, 11], end: [2026, 7], active: false }],
            losses: [{ franchise: 'AYP', kind: 'L', length: 6, start: [2026, 1], end: [2026, 6], active: true }],
            current: { GSA: ['W', 4], AYP: ['L', 6] },
        },
        scores: { GSA: [100, 110, 120], CGK: [90, 95, 130], AYP: [70, 80, 90] },
        season_arcs: { GSA: { '2025': [1, 1, 2, 3, 4, 5], '2026': [1, 2, 2, 2] }, CGK: { '2026': [1, 2, 3, 4] } },
        fingerprints: {
            traits: [{ id: 'scoring', label: 'Scoring', about: 'ppg' }, { id: 'playoffs', label: 'Playoffs', about: 'win %' }],
            owners: [
                { code: 'GSA', name: 'Griff', games: 98, values: { scoring: 95, playoffs: 0.78 }, pct: { scoring: 1, playoffs: 1 } },
                { code: 'CGK', name: 'Kaminska', games: 98, values: { scoring: 93, playoffs: 0.55 }, pct: { scoring: 0.5, playoffs: 0.5 } },
                { code: 'AYP', name: 'Arnav', games: 98, values: { scoring: 79, playoffs: null }, pct: { scoring: 0, playoffs: null } },
            ],
        },
    },
}"""


def test_rivals_pick_a_nemesis_and_victim_with_enough_games():
    result = run_charts(f"""
        const input = {INPUT};
        const r = franchiseRivals(input.charts.head_to_head, 'CGK');
        return {{ nemesis: r.nemesis?.opp, victim: r.victim?.opp, order: r.rows.map(x => x.opp) }};
    """)
    # CGK's 3-0 against AYP is too few games to make AYP a favorite victim.
    assert result == {'nemesis': 'GSA', 'victim': 'GSA', 'order': ['AYP', 'GSA']}


def test_closest_arc_compares_wins_through_the_same_week():
    assert run_charts("""
        return closestArc({ '2024': [1, 2, 3, 4, 4], '2025': [0, 1, 2, 2, 3], '2026': [1, 1, 2, 2] }, '2026', 4);
    """) == {'season': '2025', 'diff': 0, 'then': 2, 'final': 3, 'now': 2}


def test_every_manager_chart_renders_and_makes_a_tok_card():
    result = run_charts(f"""
        const input = {INPUT};
        const ctx = {{ managerInput: input, team: 'GSA', names: {{}} }};
        const out = {{}};
        for (const chart of MANAGER_CHARTS) {{
            const html = renderChartSection(chart.id, ctx, {{ highlight: 'GSA' }});
            const card = collectTokCards(ctx, 'GSA').find(c => c.id === chart.id);
            out[chart.id] = {{ html: html.includes(`id="chart-${{chart.id}}"`), caption: card?.caption,
                              body: card ? card.body().length > 0 : false, route: card && tokFullChartRoute(card.home) }};
        }}
        return out;
    """)
    assert set(result) == {
        'elo',
        'head-to-head',
        'score-distribution',
        'fingerprints',
        'win-rings',
        'streaks',
        'nemeses',
        'season-arcs',
    }
    for chart_id, chart in result.items():
        assert chart['html'] and chart['body'], chart_id
    assert result['elo']['caption'] == '📊 Griff is rated 1505, 2nd in the league'
    assert result['head-to-head']['caption'] == '😤 Griff is 12-1 against Arnav'
    assert result['nemeses']['caption'] == "😈 Griff's nemesis: Kaminska (6-8-1)"
    assert result['nemeses']['route'] == '#teams/history/GSA?section=chart-nemeses'
    assert result['season-arcs']['caption'] == '📈 Griff has 2 wins, like 2025 (5 by the end)'
    assert result['streaks']['caption'] == '🔥 Griff has won 4 straight'
    assert result['fingerprints']['caption'] == '🧬 Griff: best at Scoring and Playoffs'
    assert result['win-rings']['caption'] == '💍 Kaminska wins 66% of games'
    assert result['score-distribution']['caption'] == ('📦 Griff has the highest median score, 110')


def test_one_season_owners_stay_off_the_rings_and_old_files_draw_nothing():
    result = run_charts(f"""
        const input = {INPUT};
        const rings = renderChartSection('win-rings', {{ managerInput: input }});
        const old = {{ names: {{}}, ownerStats: [], franchises: [], version: '0' }};
        return {{
            oneYear: rings.includes('One Year'),
            old: ['elo', 'head-to-head', 'streaks', 'nemeses'].map(id => renderChartSection(id, {{ managerInput: old, team: 'GSA' }})),
        }};
    """)
    assert result['oneYear'] is False
    assert result['old'] == ['', '', '', '']


def test_elo_follows_the_leader_when_no_team_is_set():
    html = run_charts(f"""
        const input = {INPUT};
        return renderChartSection('elo', {{ managerInput: input }});
    """)
    assert 'class="chart-series is-highlight" data-series="CGK"' in html


def test_manager_charts_are_placed_on_the_page():
    index = WEB_INDEX.read_text(encoding='utf-8')
    assert index.index('src="charts-luck.js"') < index.index('src="charts-managers.js"')
    assert index.index('src="charts-managers.js"') < index.index('src="app.js"')
    app = WEB_APP.read_text(encoding='utf-8')
    assert "managerSections(['elo', 'head-to-head', 'score-distribution'])" in app
    assert "managerSections(['fingerprints', 'win-rings'])" in app
    assert "managerSections(['streaks'])" in app
    assert "managerSections(['nemeses', 'season-arcs'], { team: currentTeam })" in app
    assert "'chart-fingerprints': 'owners'," in app
    assert 'function scrollToSection(id' in app
