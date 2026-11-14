import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX, app_slice


def run_js(body: str, league: dict | None = None):
    grades = app_slice(
        '// ====== GRADES (trade report cards, draft value, costliest drops) ======',
        'function renderTradeBlowouts()',
    )
    script = f"""
let data = {json.dumps(league or {})};
const currentSeason = 2026;
function escapeHtml(value) {{ return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }}
function myTeamClass() {{ return ''; }}
function seasonTeamLabel(abbrev) {{ return abbrev; }}
function teamProfileButton(abbrev, name) {{ return name; }}
function playerProfileButton(name) {{ return name; }}
function getTransactionDate(tx) {{ return {{ dateStr: tx.date || '', cleanMessage: '' }}; }}
function transactionAnchorId(tx) {{ return 'tx-' + tx.id; }}
function txSeason(tx) {{ return tx.season; }}
function franchiseSuccessionCodes(team) {{ return [team]; }}
function franchiseCodesForStintTeam(team) {{ return [team]; }}
// Trades: each test transaction carries its own verdict.
function tradeVerdict(tx) {{ return tx.verdict; }}
// Drafts: picks name their team and the player's weekly points directly.
function draftPerformanceMoment(draft) {{ return draft.from; }}
function draftTeamCode(team) {{ return team; }}
function draftYear(draft) {{ return draft.year; }}
function getPlayerCareerProfile(name) {{ return {{ name, profile_key: name }}; }}
function draftPickFranchisePerformance(profile, draft, team) {{
    const pick = draft.rounds.flatMap(r => r.picks).find(p => p.player === profile.name);
    return {{ stint: {{ weekly_points: pick.weekly }} }};
}}
{grades}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def _trade(tx_id, season, a, b):
    winner = None if a[1] == b[1] else ('A' if a[1] > b[1] else 'B')
    sides = [{'team': a[0], 'total': a[1]}, {'team': b[0], 'total': b[1]}]
    return {
        'id': tx_id,
        'season': season,
        'verdict': {
            'sides': sides,
            'margin': abs(a[1] - b[1]),
            'winner': winner,
            'unparsed': False,
            'untracked': False,
        },
    }


def test_grades_are_symmetric_and_an_even_trade_is_a_c_plus():
    result = run_js("""
        const rank = percentileRanker([-300, -10, 0, 0, 10, 300]);
        return {
            top: letterGrade(rank(300)),
            bottom: letterGrade(rank(-300)),
            even: letterGrade(rank(0)),
            gpa: [gpaLetter(4.0), gpaLetter(2.41), gpaLetter(0.1)],
        };
    """)
    assert result['top'] == 'A' and result['bottom'] == 'D-'
    assert result['even'] == 'C+'
    assert result['gpa'] == ['A', 'C+', 'F']


def test_trade_report_grades_each_side_and_ranks_teams():
    league = {
        'transactions': [
            _trade(1, 2025, ('GSA', 500), ('CGK', 100)),
            _trade(2, 2025, ('GSA', 200), ('RPA', 190)),
            _trade(3, 2026, ('CGK', 50), ('RPA', 50)),
            # Unfollowable assets: never graded.
            {
                **_trade(4, 2026, ('GSA', 900), ('CGK', 0)),
                'verdict': {
                    **_trade(4, 2026, ('GSA', 900), ('CGK', 0))['verdict'],
                    'untracked': True,
                },
            },
        ]
    }
    result = run_js(
        """
        const { graded } = tradeGrades();
        const highlights = tradeHighlights(graded);
        return {
            count: graded.length,
            grades: graded.map(e => e.sides.map(s => s.team + ':' + s.grade)),
            teams: tradeReportByTeam(graded).map(r => [r.team, r.trades, r.qualified]),
            fleecing: highlights.fleecing.tx.id,
            mostEven: highlights.mostEven.tx.id,
            bestForBoth: highlights.bestForBoth?.tx.id ?? null,
            gpa: teamTradeGpaHtml('GSA'),
        };
        """,
        league,
    )
    assert result['count'] == 3
    # Six graded sides: the best of them ranks A (A+ needs a bigger pool).
    assert result['grades'][0] == ['GSA:A', 'CGK:D-']
    assert result['grades'][2] == ['CGK:C+', 'RPA:C+']
    assert result['fleecing'] == 1
    # Trade 3 is dead even but produced little; trade 2 is close and big.
    assert result['mostEven'] == 2
    # Never the same trade as another headline.
    assert result['bestForBoth'] not in (result['fleecing'], result['mostEven'])
    assert 'over 2 graded trades' in result['gpa']


def test_draft_value_over_slot_compares_like_slots_over_the_same_window():
    def draft(name, year, from_moment, picks):
        return {
            'name': name,
            'year': year,
            'from': from_moment,
            'rounds': [
                {
                    'round': '1',
                    'picks': [
                        {'pick': str(i + 1), 'team': team, 'player': player, 'weekly': weekly}
                        for i, (team, player, weekly) in enumerate(picks)
                    ],
                }
            ],
        }

    old = draft(
        '2024 Offseason Draft',
        2024,
        202401,
        [('GSA', 'Old1', [[2024, 1, 20]]), ('CGK', 'Old2', [[2024, 1, 10]])],
    )
    new = draft(
        '2025 Offseason Draft',
        2025,
        202501,
        [
            ('GSA', 'New1', [[2025, 1, 5], [2025, 7, 50]]),
            ('CGK', 'New2', [[2025, 1, 25], [2025, 7, 0]]),
        ],
    )
    result = run_js(
        """
        const { byPick, byDraft } = draftGrades();
        const picks = data.drafts[1].rounds[0].picks.map(p => byPick.get(p));
        return {
            window: byDraft.get(data.drafts[1]).window,
            vos: picks.map(p => [p.points, p.expected, p.vos]),
            classes: byDraft.get(data.drafts[1]).classes.map(c => c.team + ':' + c.grade),
        };
        """,
        {'drafts': [old, new]},
    )
    # The newer draft runs through week 7: seven weeks.
    assert result['window'] == 7
    # Slots 1 and 2 both average the old draft's slots 1-2 (15 points).
    assert result['vos'] == [[55, 15, 40], [25, 15, 10]]
    assert result['classes'][0].startswith('GSA:')


def test_points_after_a_drop_count_other_teams_for_a_year():
    result = run_js("""
        const profile = { franchise_stints: [
            { teams: ['GSA'], weekly_points: [[2024, 3, 30]] },
            { teams: ['CGK'], weekly_points: [[2024, 5, 12], [2025, 4, 8]] },
            { teams: ['RPA'], weekly_points: [[2025, 2, 6]] },
        ] };
        const { total, byTeam } = pointsAfterDrop(profile, 'GSA', 202404);
        return { total, byTeam: Object.fromEntries(byTeam) };
    """)
    # GSA's own week doesn't count, nor CGK's week 4 a year on.
    assert result == {'total': 18, 'byTeam': {'CGK': 12, 'RPA': 6}}


def test_grades_are_wired_into_the_views():
    app = WEB_APP.read_text(encoding='utf-8')
    html = WEB_INDEX.read_text(encoding='utf-8')
    assert '<div id="transactions-reports"></div>' in html
    assert '    renderTradeBlowouts();\n    renderTransactionReports();' in app
    assert '${draftGradesSummaryHtml(draft)}' in app
    assert '${draftPickValueHtml(pick)}' in app
    assert '${teamTradeGpaHtml(currentTeam)}' in app
    assert 'const grade = tradeGradeFor(tx, side.team);' in app
