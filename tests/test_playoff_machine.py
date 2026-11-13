import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'

TEAMS = ['AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF', 'GGG', 'HHH', 'S/T', 'J/J']


def app_slice(start_marker: str, end_marker: str) -> str:
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index(start_marker)
    end = app.index(end_marker, start)
    return app[start:end]


def _league(completed: int = 3):
    """Ten teams, a rotating 15-week schedule, and `completed` scored weeks.

    AAA scores the most every week and J/J the least, so standings and team
    strength agree.
    """
    schedule = []
    for week in range(1, 16):
        rotated = TEAMS[:1] + TEAMS[1:][week % 9 :] + TEAMS[1:][: week % 9]
        pairs = [(rotated[i], rotated[-1 - i]) for i in range(5)]
        schedule.append(
            {
                'week': week,
                'is_playoffs': False,
                'matchups': [{'team1': a, 'team2': b} for a, b in pairs],
            }
        )
    strength = {abbrev: 140 - 6 * index for index, abbrev in enumerate(TEAMS)}
    weeks = []
    record = {abbrev: {'wins': 0, 'rp': 0.0, 'pf': 0.0} for abbrev in TEAMS}
    for week in schedule[:completed]:
        matchups = []
        for game in week['matchups']:
            a, b = game['team1'], game['team2']
            matchups.append(
                {
                    'team1': {'abbrev': a, 'total_score': strength[a]},
                    'team2': {'abbrev': b, 'total_score': strength[b]},
                }
            )
            winner = a if strength[a] > strength[b] else b
            record[winner]['wins'] += 1
            record[winner]['rp'] += 1
        for abbrev in sorted(TEAMS, key=lambda t: -strength[t])[:5]:
            record[abbrev]['rp'] += 0.5
        for abbrev in TEAMS:
            record[abbrev]['pf'] += strength[abbrev]
        weeks.append({'week': week['week'], 'has_scores': True, 'matchups': matchups})
    standings = sorted(
        (
            {
                'abbrev': abbrev,
                'name': f'Team {abbrev}',
                'wins': record[abbrev]['wins'],
                'losses': completed - record[abbrev]['wins'],
                'rank_points': record[abbrev]['rp'],
                'points_for': record[abbrev]['pf'],
            }
            for abbrev in TEAMS
        ),
        key=lambda team: (-team['rank_points'], -team['wins'], -team['points_for']),
    )
    return {
        'season': 2026,
        'current_week': completed + 1,
        'completed_through': completed,
        'completed_standings': standings,
        'is_offseason': False,
        'is_historical': False,
        'teams': standings,
        'standings': standings,
        'weeks': weeks,
        'schedule': schedule,
    }


def run_machine(body: str, league=None):
    sim = app_slice('const PLAYOFF_TRIALS', 'function renderPlayoffOdds')
    machine = app_slice('const PLAYOFF_MACHINE_TRIALS', 'function seedStripHtml')
    guide = app_slice('function computeRootingGuide', 'function rootingGuideHtml')
    script = f"""
const data = {json.dumps(league or _league())};
const currentSeason = 2026;
const BRACKET_LABELS = {{ mid_bowl: 'Mid Bowl', sewer_series: 'Sewer Series', toilet_bowl: 'Toilet Bowl' }};
function sumStarterScores() {{ return 0; }}
function buildCompletedStandingsSnapshot() {{ return data.completed_standings; }}
{sim}
{machine}
{guide}
const ctx = preparePlayoffSim();
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    # Piped over stdin: the script can outgrow Linux's 128 KB limit on one
    # command-line argument (`node -e`), which macOS doesn't enforce.
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def test_no_picks_matches_the_standings_playoff_odds():
    result = run_machine("""
        const plain = simulatePlayoffOdds();
        const machine = summarizePlayoffSim(ctx, playoffMachineSummary(ctx, new Map()) && runPlayoffSim(ctx, { fixed: new Map(), trials: PLAYOFF_MACHINE_TRIALS }));
        return [plain.byTeam, machine.byTeam];
    """)
    plain, machine = result
    assert {k: v['odds'] for k, v in plain.items()} == {k: v['odds'] for k, v in machine.items()}
    for team in machine.values():
        assert abs(sum(team['seedOdds']) - 1) < 1e-9


def test_picked_winner_wins_every_trial_and_only_moves_odds_its_way():
    result = run_machine("""
        const baseline = runPlayoffSim(ctx, { trials: 1500 });
        const fixed = new Map();
        for (const m of ctx.remaining) {
            if (m.team1Abbrev === 'J/J' || m.team2Abbrev === 'J/J') {
                fixed.set(playoffPickKey(m.week, m.team1Abbrev, m.team2Abbrev), 'J/J');
            }
        }
        const picked = runPlayoffSim(ctx, { fixed, trials: 1500 });
        const records = fixedPickRecords(ctx, fixed);
        return {
            before: baseline.playoffCount['J/J'] / baseline.trials,
            after: picked.playoffCount['J/J'] / picked.trials,
            jjRecord: records['J/J'],
            remainingForJJ: ctx.remaining.filter(m => m.team1Abbrev === 'J/J' || m.team2Abbrev === 'J/J').length,
        };
    """)
    assert result['after'] > result['before']
    assert result['jjRecord'] == {
        'wins': result['remainingForJJ'],
        'losses': 0,
        'tops': 0,
        'bottoms': 0,
    }


def test_picking_every_game_makes_clinch_and_elimination_certain():
    result = run_machine("""
        const fixed = new Map();
        for (const m of ctx.remaining) {
            const favorite = ctx.teamMean[m.team1Abbrev] >= ctx.teamMean[m.team2Abbrev]
                ? m.team1Abbrev : m.team2Abbrev;
            fixed.set(playoffPickKey(m.week, m.team1Abbrev, m.team2Abbrev), favorite);
        }
        const summary = summarizePlayoffSim(ctx, runPlayoffSim(ctx, { fixed, trials: 500 }), fixed);
        return Object.fromEntries(Object.entries(summary.byTeam)
            .map(([abbrev, team]) => [abbrev, [team.odds, team.clinched, team.eliminated]]));
    """)
    assert result['AAA'] == [1, True, False]
    assert result['J/J'] == [0, False, True]
    for odds, clinched, eliminated in result.values():
        if clinched:
            assert odds == 1
        if eliminated:
            assert odds == 0


def test_rooting_guide_roots_against_rivals_for_the_bubble_team():
    result = run_machine("""
        const guide = computeRootingGuide(ctx, new Map(), 'EEE');
        return {
            week: guide.week,
            own: guide.own && guide.own.win.odds > guide.own.lose.odds,
            games: guide.games.length,
            sorted: guide.games.every((game, i, all) => i === 0 || all[i - 1].swing >= game.swing),
            ownGameExcluded: guide.games.every(game => game.rootFor !== 'EEE' && game.against !== 'EEE'),
        };
    """)
    assert result == {
        'week': 4,
        'own': True,
        'games': 4,
        'sorted': True,
        'ownGameExcluded': True,
    }


def test_picks_round_trip_through_the_url_including_slashed_abbreviations():
    result = run_machine("""
        const picks = new Map();
        const games = ctx.remaining.filter(m => [m.team1Abbrev, m.team2Abbrev].includes('S/T')).slice(0, 2);
        for (const m of games) picks.set(playoffPickKey(m.week, m.team1Abbrev, m.team2Abbrev), 'S/T');
        const extra = ctx.remaining.find(m => m.week === 6 && ![m.team1Abbrev, m.team2Abbrev].includes('S/T'));
        picks.set(playoffPickKey(extra.week, extra.team1Abbrev, extra.team2Abbrev), extra.team2Abbrev);
        const encoded = encodePlayoffPicks(ctx, picks);
        const decoded = decodePlayoffPicks(ctx, encoded + ',junk,99-AAA');
        return { same: JSON.stringify([...decoded].sort()) === JSON.stringify([...picks].sort()), encoded };
    """)
    assert result['same'] is True
    assert '-S/T' in result['encoded']


def test_playoff_machine_is_a_standings_subview():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')
    assert 'data-parent="standings" data-subview="machine"' in html
    assert 'id="standings-table-subview"' in html
    assert 'id="playoff-machine"' in html
    assert 'data-route="#standings/machine"' in html
    assert "standings: 'table'," in app
    assert "activateGenericSubview('standings', sub);" in app
    assert "if (subview === 'machine') renderPlayoffMachine();" in app
    # Arriving by link (not the tab button) must still render the Machine.
    assert "(view === 'standings' && sub === 'machine')" in app
    assert '.pm-layout {' in styles


def test_rooting_guide_never_shows_100_percent_unless_clinched():
    result = run_machine("""
        // AAA is far ahead: a sampled share can round to 100% without a clinch.
        const guide = computeRootingGuide(ctx, new Map(), 'AAA');
        const entries = [guide.own.win, guide.own.lose, ...guide.games.flatMap(g => [g.best, g.worst])];
        return entries.map(e => [displayPlayoffPct(e), e.clinched, e.eliminated]);
    """)
    for pct, clinched, eliminated in result:
        if not clinched:
            assert pct <= 99
        if not eliminated:
            assert pct >= 1


def test_half_plan_follows_picked_winners_and_refuses_the_impossible():
    result = run_machine("""
        const week = ctx.remainingWeekNums[0];
        const [g0, g1] = ctx.weeksRemaining[week];
        const key = m => playoffPickKey(week, m.team1Abbrev, m.team2Abbrev);
        const half = (team, value) => [playoffHalfKey(week, team), value];
        // The loser finishes top half, so the picked winner does too; a
        // bottom-half winner takes the loser down with it.
        const fixed = new Map([[key(g0), g0.team1Abbrev], [key(g1), g1.team1Abbrev]]);
        const plan = playoffHalfPlan(ctx, fixed, new Map([
            half(g0.team2Abbrev, 'top'),
            half(g1.team1Abbrev, 'bottom'),
        ]))[week];
        const contradiction = playoffHalfError(playoffHalfPlan(ctx, fixed, new Map([
            half(g0.team2Abbrev, 'top'),
            half(g0.team1Abbrev, 'bottom'),
        ])));
        const everyone = new Map(ctx.weeksRemaining[week].flatMap(m => [
            half(m.team1Abbrev, 'top'),
        ]));
        everyone.set(playoffHalfKey(week, g0.team2Abbrev), 'top');
        return {
            top: [...plan.top].sort(),
            bottom: [...plan.bottom].sort(),
            winner: g0.team1Abbrev,
            loser: g0.team2Abbrev,
            winner1: g1.team1Abbrev,
            loser1: g1.team2Abbrev,
            contradiction,
            tooMany: playoffHalfError(playoffHalfPlan(ctx, null, everyone)),
            week,
        };
    """)
    assert result['top'] == sorted([result['winner'], result['loser']])
    assert result['bottom'] == sorted([result['winner1'], result['loser1']])
    assert result['contradiction'] == (
        f'{result["winner"]} beats {result["loser"]} in Week {result["week"]}, '
        "so it can't finish below them."
    )
    assert result['tooMany'] == f'Only 5 teams finish in the top half in Week {result["week"]}.'


def test_pinned_halves_are_worth_exactly_their_half_point():
    result = run_machine("""
        // Every game and every top half decided, so rank points follow from
        // the picks alone: team2 wins every game, the winners of the first
        // four games and the loser of the first finish top half (5 of 10).
        const fixed = new Map();
        const halves = new Map();
        const expected = Object.fromEntries(ctx.standings.map(t => [t.abbrev, t.rank_points || 0]));
        for (const week of ctx.remainingWeekNums) {
            ctx.weeksRemaining[week].forEach((m, i) => {
                fixed.set(playoffPickKey(week, m.team1Abbrev, m.team2Abbrev), m.team2Abbrev);
                expected[m.team2Abbrev] += 1;
                const tops = new Set(i === 0 ? [m.team1Abbrev, m.team2Abbrev] : i < 4 ? [m.team2Abbrev] : []);
                for (const team of [m.team1Abbrev, m.team2Abbrev]) {
                    halves.set(playoffHalfKey(week, team), tops.has(team) ? 'top' : 'bottom');
                    if (tops.has(team)) expected[team] += 0.5;
                }
            });
        }
        const error = playoffHalfError(playoffHalfPlan(ctx, fixed, halves));
        const run = runPlayoffSim(ctx, { fixed, halves, trials: 50 });
        const order = Object.keys(expected).sort((a, b) => expected[b] - expected[a]);
        return {
            error,
            points: order.slice(0, 6).map(team => expected[team]),
            settled: order.slice(0, 5).map((team, seed) => run.seedCounts[team][seed]),
        };
    """)
    assert result['error'] is None
    # Rank points 15, 14.5, 14, 13, 12 apart: nothing is left to chance, so the
    # top five land in that order in every trial.
    assert result['points'][:5] == sorted(set(result['points'][:5]), reverse=True)
    assert result['settled'] == [50] * 5


def test_top_half_picks_round_trip_through_the_url():
    result = run_machine("""
        const week = ctx.remainingWeekNums[0];
        const halves = new Map([
            [playoffHalfKey(week, 'J/J'), 'top'],
            [playoffHalfKey(week, 'AAA'), 'bottom'],
            [playoffHalfKey(99, 'AAA'), 'top'],
        ]);
        const encoded = encodePlayoffHalves(ctx, halves);
        return { encoded, decoded: [...decodePlayoffHalves(ctx, encoded + ',junk,99tAAA').entries()].sort(), week };
    """)
    week = result['week']
    assert set(result['encoded'].split(',')) == {f'{week}tJ/J', f'{week}bAAA'}
    assert result['decoded'] == sorted([[f'{week}|AAA', 'bottom'], [f'{week}|J/J', 'top']])


def test_clinch_bounds_count_top_half_picks():
    result = run_machine("""
        const week = ctx.remainingWeekNums[0];
        const m = ctx.weeksRemaining[week][0];
        const records = fixedPickRecords(ctx, null, new Map([
            [playoffHalfKey(week, m.team1Abbrev), 'top'],
            [playoffHalfKey(week, m.team2Abbrev), 'bottom'],
        ]));
        return [records[m.team1Abbrev], records[m.team2Abbrev]];
    """)
    assert result == [
        {'wins': 0, 'losses': 0, 'tops': 1, 'bottoms': 0},
        {'wins': 0, 'losses': 0, 'tops': 0, 'bottoms': 1},
    ]


def test_both_sides_of_a_game_can_finish_top_half():
    result = run_machine("""
        const week = ctx.remainingWeekNums[0];
        const m = ctx.weeksRemaining[week][0];
        const [a, b] = [m.team1Abbrev, m.team2Abbrev];
        const key = playoffPickKey(week, a, b);
        const both = new Map([[playoffHalfKey(week, a), 'top'], [playoffHalfKey(week, b), 'top']]);
        const errors = [new Map(), new Map([[key, a]]), new Map([[key, b]])]
            .map(fixed => playoffHalfError(playoffHalfPlan(ctx, fixed, both)));
        // The clinch bounds credit both with the half point.
        const fixed = new Map([[key, a]]);
        const records = fixedPickRecords(ctx, fixed, both);
        return { errors, a: records[a], b: records[b] };
    """)
    assert result['errors'] == [None, None, None]
    assert result['a'] == {'wins': 1, 'losses': 0, 'tops': 1, 'bottoms': 0}
    assert result['b'] == {'wins': 0, 'losses': 1, 'tops': 1, 'bottoms': 0}
