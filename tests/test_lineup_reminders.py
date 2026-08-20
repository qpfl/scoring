from datetime import datetime, timedelta, timezone
from pathlib import Path

import scripts.send_lineup_reminders as reminders
from scripts.send_lineup_reminders import (
    first_kickoffs_by_week,
    lineup_is_submitted,
    missing_teams,
    reminder_period,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'
WORKFLOW = PROJECT_ROOT / '.github' / 'workflows' / 'lineup-reminders.yml'

STARTER_SLOTS = {
    'QB': 1,
    'RB': 2,
    'WR': 2,
    'TE': 1,
    'K': 1,
    'D/ST': 1,
    'HC': 1,
    'OL': 1,
}


def complete_lineup():
    return {
        position: [f'{position}-{index}' for index in range(count)]
        for position, count in STARTER_SLOTS.items()
    }


def test_first_kickoff_and_reminder_window_follow_the_nfl_schedule():
    rows = [
        {'game_type': 'PRE', 'week': 1, 'gameday': '2026-08-20', 'gametime': '20:00'},
        {'game_type': 'REG', 'week': 1, 'gameday': '2026-09-10', 'gametime': '20:20'},
        {'game_type': 'REG', 'week': 1, 'gameday': '2026-09-13', 'gametime': '13:00'},
        {'game_type': 'REG', 'week': 2, 'gameday': '2026-09-17', 'gametime': '20:15'},
    ]

    kickoffs = first_kickoffs_by_week(rows)

    assert kickoffs[1] == datetime(2026, 9, 11, 0, 20, tzinfo=timezone.utc)
    assert reminder_period(
        kickoffs,
        datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
        timedelta(hours=24),
    ) == (1, kickoffs[1])
    assert (
        reminder_period(
            kickoffs,
            datetime(2026, 9, 9, 23, 0, tzinfo=timezone.utc),
            timedelta(hours=24),
        )
        is None
    )


def test_missing_teams_respects_submissions_legacy_lineups_and_sent_state():
    timestamped = {'submitted_at': '2026-09-10T12:00:00Z'}
    lineups = {
        'GSA': timestamped,
        'CGK': complete_lineup(),
        'CWR': {'QB': ['QB-0']},
    }

    assert lineup_is_submitted(timestamped, STARTER_SLOTS)
    assert lineup_is_submitted(lineups['CGK'], STARTER_SLOTS)
    assert not lineup_is_submitted(lineups['CWR'], STARTER_SLOTS)
    assert missing_teams(
        ['GSA', 'CGK', 'CWR', 'AYP'],
        lineups,
        STARTER_SLOTS,
        already_sent={'CWR'},
    ) == ['AYP']


def test_reminder_delivery_is_recorded_and_not_repeated(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    lineup_dir = data_dir / 'lineups' / '2026'
    lineup_dir.mkdir(parents=True)
    (data_dir / 'league_config.json').write_text(
        '{"current_season": 2026, "starter_slots": {"QB": 1}}', encoding='utf-8'
    )
    (data_dir / 'teams.json').write_text(
        '{"teams": ['
        '{"abbrev": "GSA", "name": "Submitted", "owner": "Griffin"},'
        '{"abbrev": "AYP", "name": "Missing", "owner": "Arnav"}'
        ']}',
        encoding='utf-8',
    )
    (lineup_dir / 'week_1.json').write_text(
        '{"lineups": {"GSA": {"submitted_at": "2026-09-10T12:00:00Z"}}}',
        encoding='utf-8',
    )
    schedule_rows = [{'game_type': 'REG', 'week': 1, 'gameday': '2026-09-10', 'gametime': '20:20'}]
    deliveries = []
    monkeypatch.setattr(reminders, 'load_schedule_rows', lambda _season: schedule_rows)
    monkeypatch.setattr(
        reminders,
        'send_email',
        lambda subject, body, recipients: deliveries.append((subject, body, recipients)) or True,
    )
    monkeypatch.setenv('AYP_EMAIL', 'arnav@example.com')
    monkeypatch.setattr(
        'sys.argv',
        [
            'send_lineup_reminders.py',
            '--root',
            str(tmp_path),
            '--now',
            '2026-09-10T01:00:00Z',
        ],
    )

    assert reminders.main() == 0
    assert len(deliveries) == 1
    assert deliveries[0][2] == ['arnav@example.com']
    assert 'Missing has not submitted a Week 1 lineup' in deliveries[0][1]

    state = reminders.load_json(data_dir / 'lineup_reminders.json')
    assert set(state['sent']['2026']['1']) == {'AYP'}

    assert reminders.main() == 0
    assert len(deliveries) == 1


def test_logged_in_warning_is_prominent_accessible_and_links_to_set_lineup():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'id="lineup-reminder-banner" role="alert"' in html
    assert 'aria-labelledby="lineup-reminder-title"' in html
    assert 'id="lineup-reminder-action">Set Lineup</button>' in html
    assert 'function renderLineupReminder()' in app
    assert 'const week = data?.lineup_week || data?.current_week;' in app
    assert "status.tone !== 'warning'" in app
    assert "await navigateToView('manage');" in app
    assert "switchTxTab('lineup');" in app
    assert 'renderLineupReminder();' in app
    assert '.lineup-reminder-banner[hidden]' in styles


def test_reminder_workflow_runs_twice_daily_and_persists_delivery_state():
    workflow = WORKFLOW.read_text(encoding='utf-8')

    assert "cron: '17 0,12 * 1,2,9-12 *'" in workflow
    assert 'python scripts/send_lineup_reminders.py --window-hours 36' in workflow
    assert 'SMTP_USERNAME: ${{ secrets.SMTP_USERNAME }}' in workflow
    assert 'S_T_EMAIL: ${{ secrets.S_T_EMAIL }}' in workflow
    assert 'J_J_EMAIL: ${{ secrets.J_J_EMAIL }}' in workflow
    assert 'git add data/lineup_reminders.json' in workflow
    assert 'continue-on-error: true' in workflow
