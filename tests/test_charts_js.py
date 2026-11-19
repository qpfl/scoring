"""web/charts.js: the chart primitives and registry, loaded whole in node."""

import json
import re
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX, WEB_STYLES

WEB_CHARTS = WEB_APP.parent / 'charts.js'


def run_charts(body: str):
    script = f"""
{WEB_CHARTS.read_text(encoding='utf-8')}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


SERIES = """[
    { id: 'GSA', label: 'Griff', values: [1500, 1520, null, 1560] },
    { id: 'CGK', label: 'Kaminska', values: [1500, 1480, 1470, 1450] },
]"""


def test_every_primitive_returns_nothing_for_empty_input():
    result = run_charts("""
        return [
            lineChart({ series: [], x: [] }),
            lineChart({ series: [{ id: 'A', label: 'A', values: [null] }], x: ['W1'] }),
            bumpChart({ series: [], x: ['W1'] }),
            barList({ rows: [] }),
            divergingBars({ rows: [{ label: 'A', value: NaN }] }),
            heatGrid({ cells: [], xDomain: ['A'], yDomain: ['B'] }),
            ringStat({ pct: null }),
            stripPlot({ rows: [{ label: 'A', values: [] }] }),
        ];
    """)
    assert result == [''] * 8


def test_line_chart_is_labelled_and_highlights_one_series():
    html = run_charts(f"""
        return lineChart({{ series: {SERIES}, x: ['W1', 'W2', 'W3', 'W4'], highlight: 'GSA',
                           title: 'Elo ratings', refLine: 1500 }});
    """)
    assert 'role="img"' in html and 'aria-label="Elo ratings"' in html
    assert '<title>Elo ratings</title>' in html
    assert html.count('is-highlight') == 1 and html.count('is-muted') == 1
    # The highlighted series draws last, on top of the others.
    assert html.index('data-series="CGK"') < html.index('data-series="GSA"')
    # A null splits the line into two runs rather than bridging the gap.
    gsa = re.search(r'data-series="GSA">\s*<path class="chart-hit" d="([^"]+)"', html).group(1)
    assert gsa.count('M') == 2
    assert 'class="chart-refline"' in html
    assert '<details class="chart-table">' in html and '<th scope="row">Griff</th>' in html


def test_no_highlight_mutes_nothing():
    html = run_charts(f"return lineChart({{ series: {SERIES}, x: ['1', '2', '3', '4'] }});")
    assert 'is-muted' not in html and 'is-highlight' not in html


def test_bump_chart_puts_first_place_on_top():
    result = run_charts("""
        const html = bumpChart({ x: ['W1', 'W2'], series: [
            { id: 'A', label: 'A', ranks: [1, 2] },
            { id: 'B', label: 'B', ranks: [2, 1] },
        ] });
        const a = html.match(/data-series="A">\\s*<path class="chart-hit" d="M[\\d.]+,([\\d.]+)/)[1];
        const b = html.match(/data-series="B">\\s*<path class="chart-hit" d="M[\\d.]+,([\\d.]+)/)[1];
        return { aY: Number(a), bY: Number(b), table: html.includes('<th scope="col">W2</th>') };
    """)
    assert result['aY'] < result['bY']
    assert result['table']


def test_bar_list_scales_to_the_largest_value_and_escapes_labels():
    html = run_charts("""
        return barList({ highlight: 'B', rows: [
            { id: 'A', label: '<A>', value: 50 },
            { id: 'B', label: 'B', value: 100, sub: 'Team B' },
        ] });
    """)
    assert '&lt;A&gt;' in html and '<A>' not in html
    assert 'width:50%' in html and 'width:100%' in html
    assert html.count('is-highlight') == 1
    assert '<span class="chart-bar-sub">Team B</span>' in html


def test_diverging_bars_grow_from_the_center_by_sign():
    html = run_charts("""
        return divergingBars({ rows: [
            { id: 'A', label: 'A', value: 2 },
            { id: 'B', label: 'B', value: -1 },
        ] });
    """)
    assert 'class="chart-div-fill pos" style="left:50%;width:50%"' in html
    assert 'class="chart-div-fill neg" style="right:50%;width:25%"' in html
    assert '+2' in html and '-1' in html


def test_heat_grid_places_categorical_cells_and_skips_unknown_ones():
    html = run_charts("""
        return heatGrid({ label: 'Head to head', xDomain: ['A', 'B'], yDomain: ['A', 'B'],
            cells: [
                { x: 'B', y: 'A', cls: 'lvl-4', text: '3-0', tip: 'A vs B' },
                { x: 'Z', y: 'A', text: 'nope' },
            ] });
    """)
    assert html.count('<rect class="hg-cell') == 1
    assert 'class="hg-cell lvl-4"' in html and 'data-tip="A vs B"' in html
    assert '>3-0</text>' in html and 'nope' not in html
    assert 'aria-label="Head to head"' in html


def test_ring_clamps_and_labels():
    html = run_charts("return ringStat({ pct: 1.4, label: 'Griff', sub: '10 from 5,000' });")
    assert '>100%</text>' in html
    assert 'aria-label="Griff: 100%, 10 from 5,000"' in html


def test_strip_plot_marks_each_median():
    html = run_charts("""
        return stripPlot({ title: 'Scores', rows: [
            { id: 'A', label: 'A', values: [100, 110, 130] },
            { id: 'B', label: 'B', values: [90, 95] },
        ] });
    """)
    assert html.count('class="chart-strip-dot"') == 5
    assert html.count('class="chart-strip-median"') == 2
    assert 'A median 110' in html and 'B median 92.5' in html


def test_registry_rejects_duplicates_and_drops_charts_with_nothing_to_say():
    result = run_charts("""
        registerChart({ id: 'demo', family: 'standings', title: 'Demo',
            compute: ctx => (ctx.rows?.length ? ctx.rows : null),
            render: rows => barList({ rows }) });
        registerChart({ id: 'broken', family: 'luck', title: 'Broken',
            compute: () => { throw new Error('bad data'); }, render: () => 'x' });
        let duplicate = false;
        try { registerChart({ id: 'demo', family: 'standings' }); } catch (e) { duplicate = true; }
        let badFamily = false;
        try { registerChart({ id: 'other', family: 'nope' }); } catch (e) { badFamily = true; }
        const warn = console.warn;
        console.warn = () => {};
        const broken = renderChartSection('broken', {});
        console.warn = warn;
        return {
            duplicate, badFamily, broken,
            empty: renderChartSection('demo', { rows: [] }),
            missing: renderChartSection('nope', {}),
            full: renderChartSection('demo', { rows: [{ id: 'A', label: 'A', value: 1 }] }),
        };
    """)
    assert result['duplicate'] and result['badFamily']
    assert result['empty'] == result['missing'] == result['broken'] == ''
    assert 'id="chart-demo"' in result['full'] and 'data-chart="demo"' in result['full']
    assert '<h3 class="chart-title">Demo</h3>' in result['full']


def test_charts_js_loads_before_app_js_with_styles():
    index = WEB_INDEX.read_text(encoding='utf-8')
    assert index.index('src="charts.js"') < index.index('src="app.js"')
    styles = WEB_STYLES.read_text(encoding='utf-8')
    for selector in ('.chart-section', '.chart-barlist', '.chart-tip', '.hg-cell.lvl-4'):
        assert selector in styles


def test_charts_js_names_do_not_clash_with_app_js_globals():
    """Classic scripts share one global scope: a clash would be a SyntaxError
    (const) or silently replace a function (function)."""
    charts = WEB_CHARTS.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    names = re.findall(r'^(?:function|const|let) ([A-Za-z_]+)', charts, re.M)
    clashes = [
        n for n in names if re.search(rf'^(?:async )?(?:function|const|let|var) {n}\b', app, re.M)
    ]
    assert names and clashes == []
