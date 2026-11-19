"""Players, moves & awards charts: web/charts-players.js in node, plus the
weekly awards and costliest drops in qpfl/charts.py."""

import json
import subprocess

from qpfl import charts
from qpfl.weekly_facts import REGULAR, PlayerGame
from tests.test_charts_export import game
from tests.test_playoff_machine import WEB_APP, WEB_INDEX

WEB = WEB_APP.parent
SCRIPTS = (
    'charts.js',
    'tok.js',
    'charts-standings.js',
    'charts-luck.js',
    'charts-managers.js',
    'charts-players.js',
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


def player(name, team, score, starter=True, week=1, season=2026, opp='B', position='QB'):
    return PlayerGame(
        season=season,
        week=week,
        week_label=f'Week {week}',
        bracket=REGULAR,
        player_key=name.lower(),
        name=name,
        position=position,
        abbrev=team,
        franchises=(team,),
        score=score,
        starter=starter,
        opp_franchises=(opp,),
    )


# ---- Python: weekly awards and costliest drops ----


def test_weekly_awards_pick_each_winner():
    history = [
        *game(2026, 3, 'A', 130, 'B', 60, optimal=140),
        *game(2026, 3, 'C', 101, 'D', 100, optimal=101),
        *game(2026, 2, 'A', 200, 'B', 0),
    ]
    # C was projected to lose; it won anyway.
    history = [
        g.__class__(**{**g.__dict__, 'projected': 90.0, 'opp_projected': 110.0})
        if g.abbrev == 'C'
        else g
        for g in history
    ]
    players = [
        player('Josh Allen', 'A', 40, week=3),
        player('Benchwarmer', 'C', 25, starter=False, week=3),
        player('Old Week', 'A', 60, week=2),
    ]
    awards = {a['id']: a for a in charts.weekly_awards(history, players, 2026, 3)}
    assert awards['mvp'] == {
        'id': 'mvp',
        'label': 'MVP',
        'emoji': '⭐',
        'team': 'A',
        'value': 40,
        'player': 'Josh Allen',
        'position': 'QB',
    }
    assert awards['high_score']['team'] == 'A' and awards['low_score']['team'] == 'B'
    assert awards['blowout']['value'] == 70 and awards['nail_biter']['team'] == 'C'
    assert awards['upset']['team'] == 'C' and awards['upset']['value'] == -20
    assert awards['bench_mvp']['player'] == 'Benchwarmer'
    assert awards['left_on_bench'] == {
        'id': 'left_on_bench',
        'label': 'Most left on the bench',
        'emoji': '🤦',
        'team': 'A',
        'value': 10,
        'score': 130,
        'optimal': 140,
    }
    assert charts.weekly_awards(history, players, 2026, 9) == []


def test_costliest_drops_follow_players_to_new_teams_in_season_only():
    timeline = {
        (2026, 1): {'josh allen': 'A', 'kept': 'A'},
        (2026, 2): {'kept': 'A'},
        (2026, 3): {'josh allen': 'B', 'kept': 'A'},
        (2026, 15): {'traded': 'A'},
        (2026, 16): {},
    }
    players = [
        player('Josh Allen', 'B', 30, week=3, opp='A'),
        player('Josh Allen', 'B', 20, week=3, starter=False, opp='A'),
        player('Traded', 'B', 50, week=16, opp='A'),
    ]
    drops = charts.costliest_drops(timeline, players, lambda code: (code,), {})
    # Week 15 → 16 is the playoffs, where missing teams say nothing.
    assert drops == [
        {
            'player': 'Josh Allen',
            'team': 'A',
            'season': 2026,
            'week': 1,
            'points': 30,
            'starts': 1,
            'to': ['B'],
        }
    ]


# ---- Browser: charts-players.js ----


def test_boom_bust_ranks_spread_among_regular_starters():
    result = run_charts("""
        const starts = [];
        const add = (name, scores) => scores.forEach(s => starts.push({ key: name, name, position: 'WR', team: 'A', score: s }));
        add('Boom', [2, 40, 3, 38, 5]);
        add('Steady', [15, 16, 14, 15, 15]);
        add('Few', [50, 0]);
        add('Low', [1, 2, 1, 2, 1]);
        return boomBust(starts);
    """)
    assert [r['id'] for r in result['boom']] == ['Boom', 'Steady']
    assert result['steady'][0]['id'] == 'Steady'


def test_one_man_armies_share_of_team_points():
    rows = run_charts("""
        return oneManArmies([
            { key: 'a', name: 'Ace', position: 'QB', team: 'A', score: 60 },
            { key: 'b', name: 'Bee', position: 'RB', team: 'A', score: 40 },
            { key: 'c', name: 'Cee', position: 'WR', team: 'B', score: 30 },
            { key: 'd', name: 'Dee', position: 'TE', team: 'B', score: 70 },
        ]);
    """)
    assert [(r['team'], r['player'], r['share']) for r in rows] == [
        ('B', 'Dee', 0.7),
        ('A', 'Ace', 0.6),
    ]


def test_trade_grades_curve_and_gpa():
    result = run_charts("""
        const trades = [
            { id: 't1', sides: [{ team: 'A', total: 500 }, { team: 'B', total: 100 }] },
            { id: 't2', sides: [{ team: 'A', total: 200 }, { team: 'C', total: 190 }] },
            { id: 't3', sides: [{ team: 'B', total: 50 }, { team: 'C', total: 250 }] },
        ];
        return { graded: tradeGrades(trades), grades: [1, 0.9, 0.7, 0.5, 0.3, 0.1].map(p => tradeGrade(p)[0]) };
    """)
    assert result['grades'] == ['A+', 'A+', 'A', 'C', 'D', 'F']
    teams = {t['team']: t for t in result['graded']['teams']}
    assert teams['A']['trades'] == 2 and teams['A']['gpa'] > teams['B']['gpa']
    assert teams['B']['grades'] == ['F', 'F']
    assert result['graded']['fleecing']['team'] == 'A'
    assert result['graded']['fleecing']['margin'] == 400


def test_draft_value_compares_each_draft_against_itself():
    result = run_charts("""
        const picks = [];
        // Two graded drafts where pick 1 returns twice the draft's average,
        // and one too recent to grade.
        for (const [season, scale] of [[2022, 2], [2023, 1]]) {
            picks.push({ season, draft: `${season}`, overall: 1, team: 'A', player: `A${season}`, points: 300 * scale });
            picks.push({ season, draft: `${season}`, overall: 2, team: 'B', player: `B${season}`, points: 100 * scale });
            picks.push({ season, draft: `${season}`, overall: 3, team: 'C', player: `C${season}`, points: 200 * scale });
        }
        picks.push({ season: 2026, draft: '2026', overall: 1, team: 'C', player: 'New', points: 5 });
        return draftValueOverSlot(picks, 2024);
    """)
    assert result['seasons'] == [2022, 2023]
    assert 'New' not in {p['player'] for p in result['steals'] + result['busts']}
    assert {c['team'] for c in result['classes']} == {'A', 'B', 'C'}
    # The same relative performance scores the same in both drafts, in each
    # draft's own points: 2022's numbers are double 2023's.
    by_player = {p['player']: p['over'] for p in result['steals'] + result['busts']}
    assert abs(by_player['C2022'] - 2 * by_player['C2023']) < 1e-9


def test_every_player_chart_renders_and_makes_a_tok_card():
    result = run_charts("""
        const names = { A: 'Ay', B: 'Bee', C: 'Cee' };
        const starts = [];
        ['A', 'B', 'C'].forEach((team, t) => [5, 30, 8, 35, 6, 28].forEach((s, i) =>
            starts.push({ key: team, name: `${team} Player`, position: 'RB', team, score: s + t })));
        const ctx = {
            awardsInput: { season: 2026, week: 10, names, awards: [
                { id: 'mvp', label: 'MVP', emoji: '⭐', team: 'A', value: 44, player: 'Patrick Mahomes II', position: 'QB' },
                { id: 'blowout', label: 'Biggest blowout', emoji: '⚔️', team: 'B', value: 73, opp: 'C', score: [112, 39] },
            ] },
            playerInput: { season: 2026, week: 10, names, starts },
            tradeInput: { names, trades: [
                { id: 't1', sides: [{ team: 'A', total: 500 }, { team: 'B', total: 100 }] },
                { id: 't2', sides: [{ team: 'A', total: 200 }, { team: 'C', total: 190 }] },
                { id: 't3', sides: [{ team: 'B', total: 50 }, { team: 'C', total: 250 }] },
            ] },
            dropsInput: { names, version: '2026-10', drops: [
                { player: 'David Montgomery', team: 'B', season: 2020, week: 6, points: 114, starts: 8, to: ['A'] },
            ] },
            draftInput: { names, gradedThrough: 2024, picks: [
                { season: 2023, draft: '2023', overall: 1, team: 'A', player: 'Bijan', points: 800 },
                { season: 2023, draft: '2023', overall: 2, team: 'B', player: 'Gibbs', points: 900 },
            ] },
        };
        const out = {};
        for (const chart of PLAYER_CHARTS) {
            const html = renderChartSection(chart.id, ctx, { highlight: 'A' });
            const card = collectTokCards(ctx, 'A').find(c => c.id === chart.id);
            out[chart.id] = { html: html.includes(`id="chart-${chart.id}"`), caption: card?.caption,
                              pill: card?.pill, body: card ? card.body().length > 0 : false };
        }
        return out;
    """)
    assert set(result) == {
        'weekly-awards',
        'boom-bust',
        'one-man-armies',
        'trade-grades',
        'costliest-drops',
        'draft-value',
    }
    for chart_id, chart in result.items():
        assert chart['html'] and chart['body'], chart_id
    assert result['weekly-awards']['caption'] == '⭐ 44 · Patrick Mahomes II: MVP'
    assert result['weekly-awards']['pill'] == 'AWARDS NIGHT'
    assert result['trade-grades']['caption'] == (
        '🦊 Biggest fleecing: Ay won a trade with Bee by 400 points'
    )
    assert result['costliest-drops']['caption'] == (
        '🗑️ Bee dropped David Montgomery, who scored 114 for someone else'
    )


def test_player_charts_are_placed_on_the_page():
    index = WEB_INDEX.read_text(encoding='utf-8')
    assert index.index('src="charts-managers.js"') < index.index('src="charts-players.js"')
    assert index.index('src="charts-players.js"') < index.index('src="app.js"')
    for slot in (
        'stats-leaders-charts',
        'team-stats-player-charts',
        'transactions-charts',
        'drafts-charts',
    ):
        assert f'id="{slot}"' in index
    app = WEB_APP.read_text(encoding='utf-8')
    assert "renderChartSection('weekly-awards'" in app
    assert 'renderTransactionCharts();' in app and 'renderDraftCharts();' in app
    assert 'renderPlayerStatsCharts();' in app
