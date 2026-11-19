"""This week in history and Season Wrapped (web/charts-seasons.js), run in node."""

import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX

WEB = WEB_APP.parent
SCRIPTS = (
    'charts.js',
    'tok.js',
    'charts-standings.js',
    'charts-luck.js',
    'charts-managers.js',
    'charts-players.js',
    'charts-seasons.js',
)


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
    season: 2026, liveSeason: 2026, week: 11,
    names: { GSA: 'Griff', CGK: 'Kaminska', WJK: 'Bill' },
    weekHistory: {
        '11': [
            { season: 2026, label: 'Week 11', awards: [{ id: 'high_score', team: 'GSA', value: 999 }] },
            { season: 2025, label: 'Week 11', awards: [
                { id: 'high_score', team: 'CGK', value: 137, opp: 'WJK' },
                { id: 'blowout', team: 'CGK', value: 75, opp: 'WJK', score: [137, 62] },
                { id: 'mvp', team: 'CGK', value: 48, player: 'Josh Allen', position: 'QB' },
            ] },
            { season: 2023, label: 'Week 11', awards: [{ id: 'high_score', team: 'GSA', value: 120, opp: 'CGK' }] },
        ],
    },
    wrapped: {
        '2025': { complete: true, teams: { GSA: {
            record: [9, 6, 0], points_for: 1322, ppg: 88.1, ppg_rank: 4, playoffs: false, champion: false,
            best_week: { week: 8, label: 'Week 8', score: 137, opp: 'CWR', opp_score: 68 },
            worst_week: { week: 14, label: 'Week 14', score: 54, opp: 'CGK', opp_score: 101 },
            biggest_win: null, worst_loss: null, lineup_iq: 0.8, left_on_bench: 381, luck: 0.4,
            nemesis: { opp: 'CGK', record: [0, 2] },
            mvp: { name: 'Patrick Mahomes II', position: 'QB', points: 313, starts: 14 },
            workhorse: { name: "Ja'Marr Chase", position: 'WR', points: 168, starts: 15 },
        } } },
        '2026': { complete: false, teams: { GSA: {
            record: [4, 6, 0], points_for: 947, ppg: 94.7, ppg_rank: 3, playoffs: false, champion: false,
            best_week: null, worst_week: null, biggest_win: null, worst_loss: null, lineup_iq: null,
            left_on_bench: null, luck: -1.9, nemesis: null, mvp: null, workhorse: null,
        } } },
    },
    teamHof: { GSA: { seasons: [{ season: 2025, seasonFinishes: [{ type: 'position', label: '5th Place' }] }] } },
}"""


def test_week_in_history_shows_past_seasons_only():
    result = run_charts(f"""
        const input = {INPUT};
        const entries = weekInHistory(input.weekHistory, 11, 2026);
        return {{ seasons: entries.map(e => e.season), record: weekRecord(entries) }};
    """)
    assert result['seasons'] == [2025, 2023]
    assert result['record']['season'] == 2025 and result['record']['award']['value'] == 137


def test_wrapped_opens_on_the_newest_finished_season():
    result = run_charts(f"""
        const input = {INPUT};
        return {{
            seasons: wrappedSeasons(input.wrapped, 'GSA'),
            open: defaultWrappedSeason(input.wrapped, 'GSA'),
            place: wrappedFinish(input.teamHof, 'GSA', 2025, 10),
            places: [1, 2, 3, 4, 11, 22].map(placeText),
        }};
    """)
    assert result['seasons'] == [
        {'season': 2026, 'complete': False},
        {'season': 2025, 'complete': True},
    ]
    assert result['open'] == 2025 and result['place'] == 5
    assert result['places'] == [
        'Champion 🏆',
        '2nd place',
        '3rd place',
        '4th place',
        '11th place',
        '22nd place',
    ]


def test_both_charts_render_and_make_clips():
    result = run_charts(f"""
        const input = {INPUT};
        const ctx = {{ seasonsInput: input, team: 'GSA', upcomingWeek: 11 }};
        const wrapped = renderChartSection('season-wrapped', ctx);
        const soFar = renderChartSection('season-wrapped', {{ ...ctx, wrappedSeason: 2026 }});
        const history = renderChartSection('week-in-history', ctx, {{ highlight: 'CGK' }});
        const cards = collectTokCards({{ seasonsInput: input, upcomingWeek: 11 }}, 'GSA');
        const card = id => cards.find(c => c.id === id);
        return {{
            wrapped, soFar, history,
            wrappedCaption: card('season-wrapped')?.caption,
            wrappedRoute: tokFullChartRoute(card('season-wrapped')?.home),
            wrappedBody: card('season-wrapped')?.body().includes('wrapped-grid'),
            historyCaption: card('week-in-history')?.caption,
            historyTimely: card('week-in-history')?.timely,
        }};
    """)
    w = result['wrapped']
    assert 'id="chart-season-wrapped"' in w and '2025 Wrapped' in w
    assert '5th place' in w and 'Patrick Mahomes II' in w and 'Kaminska' in w
    assert 'data-wrapped-season="2026"' in w and 'data-wrapped-season="2025"' in w
    assert '2026 Wrapped (so far)' in result['soFar'] and 'In progress' in result['soFar']
    h = result['history']
    assert '2025' in h and '2023' in h and '999' not in h
    assert 'is-highlight' in h
    assert result['wrappedCaption'] == '🎁 2025: 9-6, carried by Patrick Mahomes II (313)'
    assert result['wrappedRoute'] == '#teams/history/GSA?section=chart-season-wrapped'
    assert result['wrappedBody'] is True
    assert result['historyCaption'] == "📜 Week 11's best ever: Kaminska's 137 in 2025"
    assert result['historyTimely'] is True


def test_season_charts_are_placed_on_the_page():
    index = WEB_INDEX.read_text(encoding='utf-8')
    assert index.index('src="charts-players.js"') < index.index('src="charts-seasons.js"')
    assert index.index('src="charts-seasons.js"') < index.index('src="app.js"')
    assert 'id="home-wrapped-banner"' in index
    assert index.index('id="home-wrapped-banner"') < index.index('id="home-season-content"')
    app = WEB_APP.read_text(encoding='utf-8')
    assert '${wrappedSectionHtml(currentTeam)}' in app
    assert '${weekHistorySectionHtml(week)}' in app
    assert 'renderHomeWrappedBanner()' in app
