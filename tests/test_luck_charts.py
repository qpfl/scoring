"""Luck & what-if charts (web/charts-luck.js), run in node."""

import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX

WEB = WEB_APP.parent
SCRIPTS = ('charts.js', 'tok.js', 'charts-standings.js', 'charts-luck.js')


def run_charts(body: str):
    sources = '\n'.join((WEB / name).read_text(encoding='utf-8') for name in SCRIPTS)
    script = f"""
{sources}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


# Four teams, two weeks. B scores second-most both weeks but plays A, the
# top scorer, both times: unlucky. D scores least both weeks but beats C in
# week 1: lucky.
GAMES = """[
    { week: 1, a: 'A', b: 'B', sa: 130, sb: 120, pa: 130, pb: 140, proja: 100, projb: 110 },
    { week: 1, a: 'C', b: 'D', sa: 80, sb: 85, pa: 95, pb: 85, proja: 90, projb: 80 },
    { week: 2, a: 'A', b: 'B', sa: 125, sb: 118, pa: 125, pb: 118, proja: 120, projb: 100 },
    { week: 2, a: 'C', b: 'D', sa: 100, sb: 70, pa: 110, pb: 90, proja: 95, projb: 90 },
]"""


def test_all_play_luck_finds_the_robbed_and_the_lucky():
    rows = run_charts(f'return allPlayLuck({GAMES});')
    by = {r['id']: r for r in rows}
    # B beat 2 of 3 both weeks (1.33 expected) but won nothing.
    assert round(by['B']['expected'], 2) == 1.33 and by['B']['wins'] == 0
    # D beat 1 of 3 in week 1 and nobody in week 2 (0.33) but won once.
    assert round(by['D']['luck'], 2) == 0.67
    assert rows[-1]['id'] == 'B'


def test_pythagorean_wins_use_the_fitted_exponent():
    result = run_charts(f"""
        const rows = pythagWins({GAMES});
        return {{ k: PYTHAG_EXPONENT, a: rows.find(r => r.id === 'A') }};
    """)
    assert result['k'] == 4.1
    pf, pa = 255, 238
    expected = 2 * pf**4.1 / (pf**4.1 + pa**4.1)
    assert abs(result['a']['expected'] - expected) < 1e-9


def test_wrong_opponent_counts_losses_that_beat_most_of_the_field():
    rows = run_charts(f'return wrongOpponentLosses({GAMES});')
    assert [r['id'] for r in rows] == ['B']
    assert len(rows[0]['losses']) == 2
    assert rows[0]['losses'][0] == {
        'week': 1,
        'score': 120,
        'oppScore': 130,
        'opp': 'A',
        'beaten': 2,
        'field': 2,
    }


def test_perfect_lineup_rate_and_bench_points():
    rows = run_charts(f'return perfectLineupRates({GAMES});')
    by = {r['id']: r for r in rows}
    assert by['A']['rate'] == 1 and by['A']['left'] == 0
    assert by['B']['perfect'] == 1 and by['B']['left'] == 20
    assert by['D']['left'] == 20 and rows[0]['id'] == 'A'


def test_projection_luck_is_measured_against_the_league_average():
    result = run_charts(f'return projectionLuck({GAMES});')
    assert result['weeks'] == [1, 2]
    by = {r['id']: r for r in result['rows']}
    # Week 1 beats: A +30, B +10, C -10, D +5 (average +8.75).
    assert by['A']['cumulative'][0] == 21.3
    assert abs(sum(r['total'] for r in result['rows'])) < 1e-9
    assert by['A']['raw'] == 35


def test_schedule_swap_cells_mark_reality_and_the_best_swap():
    result = run_charts("""
        const grid = {
            A: { A: { wins: 2, losses: 0, ties: 0, rp: 3 }, B: { wins: 1, losses: 1, ties: 0, rp: 2 } },
            B: { A: { wins: 2, losses: 0, ties: 0, rp: 2.5 }, B: { wins: 0, losses: 2, ties: 0, rp: 0.5 } },
        };
        return scheduleSwapCells(['A', 'B'], grid, t => `Team ${t}`);
    """)
    classes = {(c['y'], c['x']): c['cls'] for c in result['cells']}
    assert classes[('A', 'A')] == 'is-actual'
    assert classes[('A', 'B')] == 'lvl-1'
    assert classes[('B', 'A')] == 'lvl-4'
    assert result['best'] == {'team': 'B', 'owner': 'A', 'diff': 2}


def test_every_luck_chart_renders_and_makes_a_tok_card_with_short_names():
    result = run_charts(f"""
        const input = {{
            season: 2026, completedThrough: 2, teams: ['A', 'B', 'C', 'D'], label: t => `Team ${{t}}`,
            games: {GAMES},
            scheduleSwap: () => ({{ teams: ['A', 'B'], grid: {{
                A: {{ A: {{ wins: 2, losses: 0, ties: 0, rp: 3 }}, B: {{ wins: 1, losses: 1, ties: 0, rp: 2 }} }},
                B: {{ A: {{ wins: 2, losses: 0, ties: 0, rp: 2.5 }}, B: {{ wins: 0, losses: 2, ties: 0, rp: 0.5 }} }},
            }} }}),
        }};
        const ctx = {{ luckInput: input, names: {{ B: 'Bee' }} }};
        const out = {{}};
        for (const chart of LUCK_CHARTS) {{
            const html = renderChartSection(chart.id, ctx, {{ highlight: 'A' }});
            const card = collectTokCards(ctx, 'A').find(c => c.id === chart.id);
            out[chart.id] = {{ html: html.includes(`id="chart-${{chart.id}}"`), caption: card?.caption,
                              body: card ? card.body().length > 0 : false }};
        }}
        return {{ out, views: ['allplay', 'perfect', 'schedule', 'points'].map(luckChartsFor) }};
    """)
    out = result['out']
    assert set(out) == {
        'all-play-luck',
        'pythag-wins',
        'wrong-opponent',
        'perfect-rate',
        'schedule-swap',
        'projection-luck',
    }
    for chart_id, chart in out.items():
        assert chart['html'] and chart['body'], chart_id
    assert out['all-play-luck']['caption'] == '😭 Bee has been robbed of 1.3 wins'
    assert out['wrong-opponent']['caption'] == (
        '🤬 Bee lost 2 games that would have beaten most of the league'
    )
    assert out['schedule-swap']['caption'] == "🗓️ Bee would have 2 more RP with Team A's schedule"
    assert result['views'] == [
        ['all-play-luck', 'pythag-wins', 'wrong-opponent'],
        ['perfect-rate'],
        ['schedule-swap'],
        [],
    ]


def test_luck_charts_are_placed_on_the_page():
    index = WEB_INDEX.read_text(encoding='utf-8')
    assert index.index('src="charts-standings.js"') < index.index('src="charts-luck.js"')
    assert index.index('src="charts-luck.js"') < index.index('src="app.js"')
    assert 'id="team-stats-charts"' in index
    app = WEB_APP.read_text(encoding='utf-8')
    assert '${whatIfChartsHtml(view)}' in app
    assert 'renderTeamStatsCharts();' in app
    assert 'whatIfViewForSection(section)' in app
