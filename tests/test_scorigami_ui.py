import json
import subprocess

from tests.test_playoff_machine import WEB_APP, app_slice


def _game(season, week, winner, loser):
    return {
        'season': season,
        'week': week,
        'week_label': f'Week {week}',
        'winner': winner,
        'loser': loser,
    }


BLOCK = {
    'games': 4,
    'unique': 3,
    'max_score': 120,
    'cells': [
        {'w': 120, 'l': 70, 'count': 1, 'first': _game(2025, 1, 'CGK', 'WJK')},
        {
            'w': 100,
            'l': 90,
            'count': 2,
            'first': _game(2024, 1, 'GSA', 'CGK'),
            'latest': _game(2024, 2, 'WJK', 'SLS'),
        },
        {'w': 85, 'l': 85, 'count': 1, 'first': _game(2024, 3, 'GSA', 'SLS')},
    ],
    'recent': [{'w': 120, 'l': 70, 'nth': 3, **_game(2025, 1, 'CGK', 'WJK')}],
    'ties': [{'score': 85, **_game(2024, 3, 'GSA', 'SLS')}],
}


def run_scorigami(body: str):
    section = app_slice('// ====== SCORIGAMI ======', 'function hofPerfectLineupsCard')
    script = f"""
function escapeHtml(value) {{ return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }}
const block = {json.dumps(BLOCK)};
{section}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def test_section_shows_stats_grid_and_lists():
    html = run_scorigami('return scorigamiSectionHtml(block);')
    assert 'id="records-scorigami"' in html
    assert '<span class="sg-tile-value">75%</span>' in html
    assert html.count('class="sg-cell') == 3
    assert 'sg-count-2' in html
    # The newest first-time final is ringed.
    assert 'sg-newest' in html and 'class="sg-ring"' in html
    assert 'Most common final: 100-90 (2 times).' in html
    assert '<h3 class="sg-list-title">Finals seen more than once (1)</h3>' in html
    # Unique finals plus repeats account for every game: 3 + 1 = 4.
    assert (
        '<span class="sg-tile-value">3</span><span class="sg-tile-label">unique finals</span>'
        in html
    )
    assert (
        '<span class="sg-tile-value">1</span><span class="sg-tile-label">repeated an old final</span>'
        in html
    )
    assert '<h3 class="sg-list-title">Ties</h3>' in html
    assert 'role="img"' in html and 'aria-label="Scorigami grid: 3 unique final scores' in html


def test_cell_text_names_first_and_latest_games():
    result = run_scorigami('return block.cells.map(scorigamiCellText);')
    assert result[1] == (
        '100-90: happened twice. First: Week 1, 2024 (GSA over CGK). '
        'Latest: Week 2, 2024 (WJK over SLS).'
    )
    assert 'Latest' not in result[0]


def test_empty_block_renders_nothing():
    assert run_scorigami('return scorigamiSectionHtml({ games: 0 });') == ''


def test_records_page_offers_the_scorigami_filter():
    app = WEB_APP.read_text(encoding='utf-8')
    assert "book.scorigami?.games ? [{ id: 'scorigami', title: 'Scorigami' }]" in app
    assert "if (c.id === 'scorigami')" in app
    assert "if (tab === 'records') bindScorigamiGrid(container);" in app


def test_popover_lists_every_game_for_the_score():
    result = run_scorigami("""
        const thrice = {
            w: 109, l: 58, count: 3,
            first: { season: 2021, week: 1, week_label: 'Week 1', winner: 'CGK', loser: 'OPC' },
            latest: { season: 2026, week: 2, week_label: 'Week 2', winner: 'CGK', loser: 'SLS' },
            games: [
                { season: 2021, week: 1, week_label: 'Week 1', winner: 'CGK', loser: 'OPC' },
                { season: 2022, week: 15, week_label: 'Week 15', winner: 'GSA', loser: 'MAG' },
                { season: 2026, week: 2, week_label: 'Week 2', winner: 'CGK', loser: 'SLS' },
            ],
        };
        return {
            once: scorigamiPopoverHtml(block.cells[0]),
            twice: scorigamiCellGames(block.cells[1]).map(g => g.week),
            thrice: scorigamiPopoverHtml(thrice),
            title: scorigamiCellText(thrice),
        };
    """)
    assert '<div class="sg-pop-score">120-70</div>' in result['once']
    assert 'Happened once' in result['once']
    assert '<li>Week 1, 2025 (CGK over WJK)</li>' in result['once']
    assert result['twice'] == [1, 2]
    assert 'Happened 3 times' in result['thrice']
    assert result['thrice'].count('<li>') == 3
    assert 'Week 15, 2022 (GSA over MAG)' in result['title']
