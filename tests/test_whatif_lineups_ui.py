import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX, app_slice


def run_js(body: str, league: dict | None = None):
    whatif = app_slice(
        '// ====== ALTERNATE STANDINGS ======', '// ====== PLAYOFF PROBABILITY SIMULATOR ======'
    )
    lineups = app_slice(
        '// ====== LINEUPS (Stats → Lineups) ======', '// ====== ALTERNATE STANDINGS ======'
    )
    optimal = app_slice('function sumStarterScores(roster)', 'function calculateOwnerSuccessByTeam')
    script = f"""
const data = {json.dumps(league or {})};
function seasonFormat() {{ return {{ lastWeek: 15 }}; }}
function escapeHtml(value) {{ return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }}
function myTeamClass() {{ return ''; }}
function teamProfileButton(abbrev, name) {{ return name; }}
function playerProfileButton(name) {{ return name; }}
function hofNumber(value) {{ return String(value); }}
function hofEntryIsMine() {{ return false; }}
{optimal}
{whatif}
{lineups}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def _team(abbrev, score, roster=None):
    return {'abbrev': abbrev, 'total_score': score, 'roster': roster or []}


def _week(number, *games):
    return {
        'week': number,
        'has_scores': True,
        'matchups': [{'team1': _team(*a), 'team2': _team(*b)} for a, b in games],
    }


LEAGUE = {
    'weeks': [
        # AAA beats BBB and CCC beats DDD; AAA (100) and BBB (90) top half.
        _week(1, (('AAA', 100), ('BBB', 90)), (('CCC', 80), ('DDD', 70))),
        # BBB beats AAA and CCC beats DDD; CCC tops the week, and BBB and DDD
        # tie at 95 for the last top-half place, so each gets half of it.
        _week(2, (('AAA', 60), ('BBB', 95)), (('CCC', 110), ('DDD', 95))),
    ],
}


def test_standings_from_scores_follow_the_rank_point_rules():
    result = run_js(
        """
        const rows = standingsFromScores(whatIfActualScores(whatIfWeeks(2)));
        return Object.fromEntries([...rows].map(([ab, r]) => [ab, [r.rp, r.wins, r.topHalf]]));
        """,
        LEAGUE,
    )
    assert result == {
        'AAA': [1.5, 1, 1],
        'BBB': [1.75, 1, 1.5],
        'CCC': [2.5, 2, 1],
        'DDD': [0.25, 0, 0.5],
    }


def test_all_play_and_points_views():
    result = run_js(
        """
        const weeks = whatIfWeeks(2);
        const allplay = computeWhatIf('allplay', weeks).rows.map(r => [r.abbrev, r.apW, r.apL, r.apT]);
        const points = computeWhatIf('points', weeks).rows.map(r => r.abbrev);
        return { allplay, points };
        """,
        LEAGUE,
    )
    # BBB beat 2 of 3 then 1 of 3 with a tie; CCC beat 1 then all 3.
    assert result['allplay'][0] == ['BBB', 3, 2, 1]
    assert ['CCC', 4, 2, 0] in result['allplay']
    assert result['points'] == ['CCC', 'BBB', 'DDD', 'AAA']


def test_schedule_swap_plays_the_owner_instead_of_yourself():
    result = run_js(
        """
        const { grid } = computeWhatIf('schedule', whatIfWeeks(2));
        return {
            own: grid.AAA.AAA,
            // AAA on BBB's schedule: BBB played AAA in both weeks, so AAA plays BBB.
            asBBB: grid.AAA.BBB,
            // DDD on CCC's schedule: CCC's opponent each week is DDD, so DDD plays CCC.
            dddAsCCC: grid.DDD.CCC,
        };
        """,
        LEAGUE,
    )
    assert result['own'] == {'wins': 1, 'losses': 1, 'ties': 0, 'rp': 1.5}
    assert result['asBBB'] == result['own']
    assert result['dddAsCCC']['wins'] == 0


def test_perfect_lineups_replay_with_the_best_lineup():
    league = {
        'weeks': [
            _week(
                1,
                (
                    (
                        'AAA',
                        70,
                        [
                            {'name': 'S', 'position': 'QB', 'score': 70, 'starter': True},
                            {'name': 'B', 'position': 'QB', 'score': 95, 'starter': False},
                        ],
                    ),
                    ('BBB', 90, [{'name': 'T', 'position': 'QB', 'score': 90, 'starter': True}]),
                ),
            ),
        ],
    }
    result = run_js(
        """
        const rows = computeWhatIf('perfect', whatIfWeeks(1)).rows;
        return rows.map(r => [r.abbrev, r.wins, r.bench, r.soloGain]);
        """,
        league,
    )
    # A perfect AAA (95) beats BBB and takes the top half: +1.5 RP alone.
    assert result[0] == ['AAA', 1, 25, 1.5]


def test_lineups_render_each_card_and_skip_empty_ones():
    block = {
        'seasons': [2026],
        'by_season': {
            '2026': {
                'bench_blunders': [
                    {
                        'season': 2026,
                        'week': 3,
                        'week_label': 'Week 3',
                        'team': 'GSA',
                        'owner': 'Griff',
                        'opponent': 'CGK',
                        'score': 90,
                        'opponent_score': 100,
                        'benched': {'player': 'Bench QB', 'position': 'QB'},
                        'benched_score': 30,
                        'started': {'player': 'Starter QB', 'position': 'QB'},
                        'started_score': 5,
                        'margin': 25,
                        'flipped': True,
                    }
                ],
                'ghost_starters': [],
            }
        },
        'all_time': {},
    }
    html = run_js(f'return lineupsHtml({json.dumps(block)}, "2026");')
    assert 'Benching Hall of Shame' in html
    assert 'Benched Bench QB (30) for Starter QB (5)' in html
    assert '<span class="lineup-flag">Cost the game</span>' in html
    assert 'Week 3, 2026 · 90-100 vs CGK' in html
    assert 'Ghost Starters' not in html


def test_lineups_tab_and_alternate_standings_are_wired():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    assert 'data-parent="stats" data-subview="lineups"' in html
    assert 'id="lineups-container"' in html
    assert 'id="standings-whatif"' in html
    assert "if (subview === 'lineups') renderLineupsTab();" in app
    # Its own small file, not the Hall of Fame's 1 MB record book.
    assert (
        "if (subview === 'lineups') requests.push(ensureSharedResource('lineup_superlatives'));"
        in app
    )
    assert "path: 'data/shared/lineup_superlatives.json'" in app
    assert 'renderWhatIfStandings(postseasonContext.completedThrough, displayedStandings);' in app
