"""Standings & outlook charts (web/charts-standings.js), run in node."""

import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX

WEB = WEB_APP.parent
SCRIPTS = ('charts.js', 'tok.js', 'charts-standings.js')


def run_charts(body: str):
    sources = '\n'.join((WEB / name).read_text(encoding='utf-8') for name in SCRIPTS)
    script = f"""
{sources}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


# A wins every week with the most points; D loses every week with the fewest.
WEEKS = """[
    { week: 1, games: [{ a: 'A', b: 'B', sa: 130, sb: 100 }, { a: 'C', b: 'D', sa: 110, sb: 80 }] },
    { week: 2, games: [{ a: 'A', b: 'C', sa: 125, sb: 105 }, { a: 'B', b: 'D', sa: 120, sb: 70 }] },
    { week: 3, games: [{ a: 'A', b: 'D', sa: 140, sb: 60 }, { a: 'B', b: 'C', sa: 90, sb: 135 }] },
]"""


def input_js(extra: str = '') -> str:
    return f"""{{
        season: 2026, live: true, completedThrough: 3, slots: 2,
        teams: ['A', 'B', 'C', 'D'], label: t => `Team ${{t}}`,
        weeks: {WEEKS},
        standings: [
            {{ abbrev: 'A', rank_points: 4.5, wins: 3, losses: 0 }},
            {{ abbrev: 'C', rank_points: 3, wins: 2, losses: 1 }},
            {{ abbrev: 'B', rank_points: 1.5, wins: 1, losses: 2 }},
            {{ abbrev: 'D', rank_points: 0, wins: 0, losses: 3 }},
        ],
        remaining: [{{ week: 4, a: 'A', b: 'B' }}, {{ week: 4, a: 'C', b: 'D' }}],
        weeksLeft: 1,
        model: {{ teamMean: {{ A: 130, B: 103, C: 117, D: 70 }}, meanUncertaintySD: {{}}, leagueStd: 20, leagueMean: 105 }},
        leaguePpg: 105,
        history: [
            {{ week: 1, rankings: {{ A: 1, C: 2, B: 3, D: 4 }} }},
            {{ week: 2, rankings: {{ A: 1, B: 2, C: 3, D: 4 }} }},
            {{ week: 3, rankings: {{ A: 1, C: 2, B: 3, D: 4 }} }},
        ],
        status: {{ A: {{ clinched: true }}, D: {{ eliminated: true }} }},
        sos: {{ A: 110, B: 100, C: 90, D: 120 }},
        oddsSeries: () => [
            {{ week: 0, odds: {{ A: 0.5, B: 0.5, C: 0.5, D: 0.5 }} }},
            {{ week: 1, odds: {{ A: 0.7, B: 0.4, C: 0.6, D: 0.3 }} }},
            {{ week: 2, odds: {{ A: 0.9, B: 0.5, C: 0.5, D: 0.1 }} }},
        ],
        {extra}
    }}"""


def test_power_rankings_reward_all_play_record_and_recent_scoring():
    history = run_charts(f"return computePowerRankings({WEEKS}, ['A', 'B', 'C', 'D']);")
    assert [h['week'] for h in history] == [1, 2, 3]
    assert history[-1]['ranks'] == {'A': 1, 'C': 2, 'B': 3, 'D': 4}
    # After week 1, C (110, a win) is ahead of B (100, a loss).
    assert history[0]['ranks']['C'] < history[0]['ranks']['B']


def test_biggest_move_finds_the_largest_jump():
    assert run_charts("""
        return biggestMove([
            { week: 1, ranks: { A: 1, B: 2, C: 3 } },
            { week: 2, ranks: { C: 1, A: 2, B: 3 } },
        ]);
    """) == {'team': 'C', 'move': 2, 'rank': 1}


def test_win_probability_favors_the_better_team_and_is_symmetric():
    result = run_charts("""
        const model = { teamMean: { A: 130, B: 100 }, meanUncertaintySD: {}, leagueStd: 20, leagueMean: 110 };
        const remaining = [{ a: 'A', b: 'B' }, { a: 'B', b: 'A' }];
        return {
            p: gameWinProbability(model, 'A', 'B'),
            q: gameWinProbability(model, 'B', 'A'),
            even: gameWinProbability(model, 'A', 'A'),
            wins: expectedRemainingWins(remaining, model),
            cdf: [chartNormalCdf(0), chartNormalCdf(1.96)],
        };
    """)
    assert 0.8 < result['p'] < 0.9
    assert abs(result['p'] + result['q'] - 1) < 1e-9
    assert abs(result['even'] - 0.5) < 1e-6
    assert abs(result['wins']['A'] + result['wins']['B'] - 2) < 1e-9
    assert abs(result['cdf'][0] - 0.5) < 1e-6 and abs(result['cdf'][1] - 0.975) < 1e-3


def test_clinch_rows_label_each_team_against_the_line():
    rows = run_charts("""
        const standings = [
            { abbrev: 'A', rank_points: 10 }, { abbrev: 'B', rank_points: 8 },
            { abbrev: 'C', rank_points: 8 }, { abbrev: 'D', rank_points: 5 },
        ];
        return clinchRows(standings, { A: { clinched: true }, D: { eliminated: true } }, 2, 2);
    """)
    # B holds the last spot: its chaser C can reach 11, so B needs 3.5 (a tie
    # isn't a clinch). C is out once B's 8 is out of reach: 11 - 8 + 0.5.
    assert [r['label'] for r in rows] == ['Clinched', 'Magic # 3.5', 'Elim # 3.5', 'Out']
    assert rows[1]['chaser'] == 'C' and rows[2]['holder'] == 'B'
    assert rows[0]['max'] == 13


def test_magic_numbers_on_real_standings():
    numbers = run_charts("""
        const st = [['CGK', 12.5], ['S/T', 10.5], ['CWR', 9.5], ['SLS', 7.5], ['RPA', 7.5],
                    ['AST', 7], ['GSA', 7], ['J/J', 5], ['WJK', 4.5], ['AYP', 4]]
            .map(([abbrev, rank_points]) => ({ abbrev, rank_points }));
        return magicNumbers(st, 5, 4);
    """)
    # Five weeks left: anyone can reach rank points + 7.5. The fourth-highest
    # other ceiling for CGK is 15 (SLS or RPA), so 15 - 12.5 + 0.5.
    assert numbers['CGK']['magic'] == 3
    assert numbers['SLS']['magic'] == 8 and numbers['RPA']['elimination'] == 8
    assert numbers['AYP']['elimination'] == 4.5


def test_a_zero_magic_number_reads_as_clinched():
    rows = run_charts("""
        return clinchRows([{ abbrev: 'A', rank_points: 20 }, { abbrev: 'B', rank_points: 2 },
                           { abbrev: 'C', rank_points: 1 }], {}, 1, 1);
    """)
    assert [r['label'] for r in rows] == ['Clinched', 'Out', 'Out']


def test_finish_history_reads_places_titles_and_toilet_bowls():
    result = run_charts("""
        const hof = {
            GSA: { seasons: [
                { season: 2024, seasonFinishes: [{ type: 'champion', label: 'Champion' }] },
                { season: 2025, seasonFinishes: [{ type: 'position', label: '5th Place' }] },
                { season: 2026, seasonFinishes: [] },
            ] },
            AYP: { seasons: [
                { season: 2024, seasonFinishes: [{ type: 'toilet-bowl', label: 'Toilet Bowl' }] },
                { season: 2025, seasonFinishes: [{ type: 'playoff', label: '2nd Place' }] },
            ] },
        };
        return finishHistory(hof, code => code, 10);
    """)
    assert result['seasons'] == [2024, 2025]
    assert [r['id'] for r in result['rows']] == ['GSA', 'AYP']
    assert result['rows'][0]['places'] == {'2024': 1, '2025': 5}
    assert result['rows'][1]['places'] == {'2024': 10, '2025': 2}


def test_every_standings_chart_renders_and_makes_a_tok_card():
    result = run_charts(f"""
        const input = {input_js()};
        const hof = {{
            GSA: {{ seasons: [{{ season: 2024, seasonFinishes: [{{ type: 'champion', label: 'Champion' }}] }},
                              {{ season: 2025, seasonFinishes: [{{ type: 'position', label: '4th Place' }}] }}] }},
        }};
        const ctx = {{ standingsInput: input, finishInput: {{ teamHof: hof, label: c => c, leagueSize: 10 }} }};
        const out = {{}};
        for (const chart of STANDINGS_CHARTS) {{
            const html = renderChartSection(chart.id, ctx, {{ highlight: 'A' }});
            const card = collectTokCards(ctx, 'A').find(c => c.id === chart.id);
            out[chart.id] = {{ html: html.length > 0, anchor: html.includes(`id="chart-${{chart.id}}"`),
                              caption: card?.caption, body: card ? card.body().length > 0 : false }};
        }}
        return out;
    """)
    assert set(result) == {
        'playoff-odds-trend',
        'power-rankings',
        'projected-wins',
        'schedule-ahead',
        'clinch-tracker',
        'finish-history',
    }
    for chart_id, chart in result.items():
        assert chart['html'] and chart['anchor'] and chart['body'], chart_id
    # B and C swapped places in week 3; C's climb is the story.
    assert result['power-rankings']['caption'] == '🚀 Team C jumped 1 spot to No. 2'
    assert result['schedule-ahead']['caption'] == '😰 Team D has the toughest road left'
    assert result['clinch-tracker']['caption'] == (
        "🔢 Team C's magic number is 0.5 · 1 clinched, 1 out"
    )
    assert result['playoff-odds-trend']['caption'].startswith('📈 Team A gained 20 points')
    assert result['finish-history']['caption'] == '🏆 GSA has 1 title'


def test_outlook_charts_stay_out_of_finished_and_historical_seasons():
    result = run_charts(f"""
        const input = {input_js('live: false, sos: null, model: null')};
        const ctx = {{ standingsInput: input }};
        return ['playoff-odds-trend', 'projected-wins', 'schedule-ahead', 'clinch-tracker', 'power-rankings']
            .map(id => [id, renderChartSection(id, ctx) !== '']);
    """)
    assert dict(result) == {
        'playoff-odds-trend': False,
        'projected-wins': False,
        'schedule-ahead': False,
        'clinch-tracker': False,
        'power-rankings': True,
    }


def test_harder_schedules_read_red():
    html = run_charts(f"""
        return renderChartSection('schedule-ahead', {{ standingsInput: {input_js()} }});
    """)
    # D's opponents score 15 more than average: a tough road, shown in red.
    assert 'chart-div-fill neg" style="left:50%' in html


def test_standings_charts_are_placed_on_the_page():
    index = WEB_INDEX.read_text(encoding='utf-8')
    assert (
        index.index('src="tok.js"')
        < index.index('src="charts-standings.js"')
        < index.index('src="app.js"')
    )
    assert 'id="standings-charts"' in index and 'id="machine-charts"' in index
    app = WEB_APP.read_text(encoding='utf-8')
    assert 'renderStandingsCharts();' in app and 'renderMachineCharts();' in app
    assert "renderChartSection('finish-history'" in app
    assert "'chart-finish-history': 'franchises'," in app
