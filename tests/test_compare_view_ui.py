"""Compare Teams: weekly/season scoring, PPG and rank, and trade building.

These run the real browser code against the real exports.
"""

import json
import shutil
import subprocess

import pytest

from tests.test_pick_trade_history_ui import HARNESS, PROJECT_ROOT, WEB_APP, WEB_STYLES

PROBE = r"""
data = {
    ...JSON.parse(fs.readFileSync('web/data.json', 'utf8')),
    draft_picks: JSON.parse(
        fs.readFileSync('web/data/seasons/2026/draft_picks.json', 'utf8')
    ),
};
LIVE_SEASON = data.season;

const weeks = compareScoredWeeks();
const lastWeek = weeks.at(-1);
const matchup = lastWeek.matchups[0];
const side = matchup.team1;
const starters = side.roster.filter(p => p.starter);

// Week scope: each starter's points come from that week, and the starters
// add back up to the team's score.
compareScope = lastWeek.week;
const weekStats = starters.map(p => compareStatsFor(p, side.abbrev));
const starterSum = weekStats.reduce((sum, s) => sum + s.value, 0);
const weekRanks = [...getWeekPlayerScores(lastWeek.week).values()];
const weekHeader = compareTeamSummaryHtml({ abbrev: side.abbrev, total: 0 });

// Season scope: rank and PPG match the Rosters table's metrics.
compareScope = 'season';
const rostered = data.rosters[side.abbrev].find(p => !p.taxi);
const metrics = getPlayerSeasonMetrics().get(
    `${rostered.position}|${rostered.name.toLowerCase()}`
);
const seasonStats = compareStatsFor({ ...rostered, totalPoints: 12 }, side.abbrev);
const seasonHeader = compareTeamSummaryHtml({ abbrev: side.abbrev, total: 231 });

// Season points are the player's whole year, not just his time on this team.
const built = buildCompareTeam(side.abbrev, { name: side.name });
const builtPlayers = Object.values(built.byPosition).flat();
const wholeYear = builtPlayers.every(p => {
    const m = getPlayerSeasonMetrics().get(`${p.position}|${p.name.toLowerCase()}`);
    return p.totalPoints === (m ? m.total_points : 0);
});
const taxiStats = built.taxiPlayers.map(p => compareStatsFor(p, side.abbrev).points);

// Trade building: only for a logged-in manager who is one of the two teams.
compareTeam1 = side.abbrev;
compareTeam2 = matchup.team2.abbrev;
const loggedOut = compareTradeContext();
manageState.team = side.abbrev;
manageState.password = 'x';
const mine = compareTradeContext();
compareTeam1 = data.teams.find(t => t.abbrev !== side.abbrev && t.abbrev !== compareTeam2).abbrev;
const notMine = compareTradeContext();

// Every tradeable pick chip on Compare carries the trade builder's pick id.
const picksHtml = renderComparePicks(getCompareTeamPicks(side.abbrev), side.abbrev, true);
const chipIds = [...picksHtml.matchAll(/data-kind="pick" data-id="([^"]+)"/g)].map(m => m[1]).sort();
const ownedIds = getOwnedPicks(side.abbrev).map(p => p.id).sort();
const readOnlyHtml = renderComparePicks(getCompareTeamPicks(side.abbrev), side.abbrev);

// The trade builder's rows carry the same rank/PPG, and follow its own scope.
tradeScope = 'season';
const tradeSeasonRow = tradePlayerRowHtml(rostered, false, side.abbrev);
tradeScope = lastWeek.week;
const tradeWeekRow = tradePlayerRowHtml(starters[0], false, side.abbrev);

console.log(JSON.stringify({
    week: lastWeek.week,
    teamScore: side.total_score,
    starterSum,
    startedFlags: weekStats.map(s => s.started),
    weekMeta: weekStats[0].meta,
    ranksValid: weekRanks.every(e => e.position_rank >= 1 && e.position_rank <= e.pool_size),
    weekHeader,
    seasonMeta: seasonStats.meta,
    expectedSeasonMeta: `${rostered.position}${metrics.position_rank} · ${metrics.ppg.toFixed(1)} PPG`,
    seasonHeader,
    wholeYear,
    taxiStats,
    loggedOut,
    mine,
    notMine,
    chipIds,
    ownedIds,
    tradeSeasonRow,
    tradeWeekRow,
    readOnlyToggles: (readOnlyHtml.match(/compare-trade-toggle/g) || []).length,
}));
"""


@pytest.fixture(scope='module')
def probe():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the compare view regression test')

    app = WEB_APP.read_text(encoding='utf-8')
    startup = 'loadData();\ncheckRefresh();'
    assert app.count(startup) == 1
    app = app.replace(startup, '')

    completed = subprocess.run(
        [node],
        cwd=PROJECT_ROOT,
        input=f'{HARNESS}\n{app}\n{PROBE}',
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_week_scope_starters_add_up_to_the_team_score(probe):
    assert all(probe['startedFlags'])
    assert probe['starterSum'] == pytest.approx(probe['teamScore'])
    assert probe['weekMeta'].endswith('· Started')
    assert probe['ranksValid']
    assert f"Week {probe['week']}" in probe['weekHeader']


def test_season_scope_shows_the_same_rank_and_ppg_as_rosters(probe):
    assert probe['seasonMeta'] == probe['expectedSeasonMeta']
    assert 'PPG' in probe['seasonHeader']
    assert '231 pts' in probe['seasonHeader']


def test_season_points_cover_the_whole_year(probe):
    assert probe['wholeYear']
    assert '-' not in probe['taxiStats']


def test_trade_building_needs_a_logged_in_manager_on_one_side(probe):
    assert probe['loggedOut'] is None
    assert probe['mine'] is not None
    assert probe['notMine'] is None


def test_compare_pick_chips_use_the_trade_builders_pick_ids(probe):
    assert probe['chipIds']
    assert probe['chipIds'] == probe['ownedIds']
    assert probe['readOnlyToggles'] == 0


def test_trade_builder_rows_show_rank_ppg_and_week_scores(probe):
    assert probe['expectedSeasonMeta'] in probe['tradeSeasonRow']
    assert probe['weekMeta'] in probe['tradeWeekRow']


def test_compare_trade_styles_exist():
    styles = WEB_STYLES.read_text(encoding='utf-8')
    for selector in ('.compare-trade-bar', '.compare-trade-toggle', '.compare-player-meta'):
        assert selector in styles
