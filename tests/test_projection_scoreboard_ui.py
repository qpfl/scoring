"""Matchups projection scoreboard: how often the pregame projection picked the winner.

These run the real browser code.
"""

import json
import shutil
import subprocess

import pytest

from tests.test_pick_trade_history_ui import HARNESS, PROJECT_ROOT, WEB_APP

PROBE = r"""
const side = (abbrev, pregame, score, remaining = 0) => ({
    abbrev, projection_ready: true, pregame_total: pregame, projected_total: pregame,
    total_score: score, starters_remaining: remaining, roster: [],
});
LIVE_SEASON = 2026;
data = {
    season: 2026,
    is_historical: false,
    weeks: [
        { week: 1, matchups: [
            { team1: side('GSA', 90, 110), team2: side('RPA', 80, 70) },   // correct
            { team1: side('CGK', 85, 60), team2: side('CWR', 75, 90) },    // upset
            { team1: side('AYP', 80, 70), team2: side('WJK', 80, 60) },    // projected tie
            { team1: side('S/T', 90, 88), team2: side('SLS', 70, 88) },    // actual tie
        ] },
        { week: 2, matchups: [
            { team1: side('GSA', 90, 40, 3), team2: side('CWR', 80, 30, 2) },  // in progress
            { team1: side('RPA', 70, 95), team2: side('CGK', 90, 60) },        // upset
        ] },
    ],
};

const week1 = projectionWeekRecord(data.weeks[0], false);
const week2 = projectionWeekRecord(data.weeks[1], false);
const html = renderProjectionScoreboard(2);

const pastSeason = { ...data, season: 2025, is_historical: true, weeks: [
    { week: 1, matchups: [{ team1: { abbrev: 'GSA', total_score: 90, roster: [] },
                            team2: { abbrev: 'RPA', total_score: 80, roster: [] } }] },
] };
data = pastSeason;
const pastHtml = renderProjectionScoreboard(1);

console.log(JSON.stringify({ week1, week2, html, pastHtml }));
"""


@pytest.fixture(scope='module')
def probe():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the projection scoreboard test')

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


def test_ties_are_not_graded_and_upsets_count_against_the_projection(probe):
    assert probe['week1'] == {'week': 1, 'correct': 1, 'wrong': 1, 'pending': 0}


def test_unfinished_matchups_stay_pending(probe):
    assert probe['week2'] == {'week': 2, 'correct': 0, 'wrong': 1, 'pending': 1}


def test_scoreboard_shows_season_record_and_each_week(probe):
    html = probe['html']
    assert '1–2 (33%)' in html
    assert '<span>Wk 1</span><strong>1–1</strong>' in html
    assert '<span>Wk 2</span><strong>0–1, 1 pending</strong>' in html
    assert 'projection-week current' in html


def test_seasons_without_projections_hide_the_scoreboard(probe):
    assert probe['pastHtml'] == ''
