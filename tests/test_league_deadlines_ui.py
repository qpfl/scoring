import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'

# Week 7: Thursday 10/22 to Monday 10/26 (ET). Week 8 opens Thursday 10/29.
GAME_TIMES = {
    '7': {'LAR': '2026-10-23T00:15:00+00:00', 'KC': '2026-10-27T00:15:00+00:00'},
    '8': {'NO': '2026-10-30T00:15:00+00:00'},
    '11': {'BUF': '2026-11-24T01:15:00+00:00'},
    '17': {'DAL': '2027-01-01T01:15:00+00:00'},
}


def deadlines_at(now: str, current_week: int) -> list[str]:
    app = WEB_APP.read_text(encoding='utf-8')
    helpers = app[
        app.index('const MIDSEASON_DRAFT_AFTER_WEEK') : app.index('function renderHomeDeadlines')
    ]
    data = {
        'season': 2026,
        'is_offseason': False,
        'current_week': current_week,
        'trade_deadline_week': 12,
        'game_times': GAME_TIMES,
    }
    script = f"""
process.env.TZ = 'America/New_York';
const LIVE_SEASON = 2026;
const sharedData = {{}};
let data = {json.dumps(data)};
{helpers}
process.stdout.write(JSON.stringify(leagueDeadlines(new Date({json.dumps(now)}))));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    return [f'{d["label"]}: {d["detail"]}' for d in json.loads(result.stdout)]


def test_first_half_shows_the_week_7_taxi_release_and_the_midseason_draft():
    deadlines = deadlines_at('2026-10-20T12:00:00Z', 7)

    assert len(deadlines) == 2
    assert deadlines[0].startswith('Taxi activation deadline: Before Week 7 kicks off')
    assert deadlines[1] == 'Midseason draft: Tue, Oct 27 or Wed, Oct 28'


def test_the_draft_stays_alone_once_the_week_7_taxi_release_passes():
    deadlines = deadlines_at('2026-10-25T12:00:00Z', 7)

    assert [d.split(':')[0] for d in deadlines] == ['Midseason draft']


def test_second_half_deadlines_appear_only_after_the_draft():
    deadlines = deadlines_at('2026-10-30T12:00:00Z', 8)

    assert deadlines[0] == 'Trade deadline: Closes once Week 11 is final (Mon, Nov 23)'
    assert deadlines[1].startswith('Taxi activation deadline: Before Week 17 kicks off')


def test_the_trade_deadline_drops_off_once_trading_closes():
    deadlines = deadlines_at('2026-12-01T12:00:00Z', 12)

    assert [d.split(':')[0] for d in deadlines] == ['Taxi activation deadline']
    assert 'Week 17' in deadlines[0]


def test_nothing_shows_after_championship_week_kicks_off():
    assert deadlines_at('2027-01-02T12:00:00Z', 17) == []


def test_deadlines_render_on_home_and_my_team():
    app = WEB_APP.read_text(encoding='utf-8')
    html = WEB_INDEX.read_text(encoding='utf-8')

    assert 'id="home-deadlines"' in html
    assert 'renderHomeDeadlines();' in app
    assert 'my-team-deadlines-card' in app
