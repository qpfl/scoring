#!/usr/bin/env python3
"""Email each team that has not submitted a lineup before the week's first kickoff."""

import argparse
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

TEAM_EMAIL_VARS = {
    'GSA': 'GSA_EMAIL',
    'CGK': 'CGK_EMAIL',
    'CWR': 'CWR_EMAIL',
    'AYP': 'AYP_EMAIL',
    'AST': 'AST_EMAIL',
    'WJK': 'WJK_EMAIL',
    'SLS': 'SLS_EMAIL',
    'RPA': 'RPA_EMAIL',
    'S/T': 'S_T_EMAIL',
    'J/J': 'J_J_EMAIL',
}

EASTERN = ZoneInfo('America/New_York')


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def row_kickoff(row: dict) -> datetime | None:
    """Convert an nflverse schedule row's Eastern date/time to UTC."""
    gameday = row.get('gameday')
    gametime = row.get('gametime')
    if not gameday or not gametime:
        return None
    try:
        local = datetime.fromisoformat(f'{str(gameday)[:10]}T{gametime}')
    except (TypeError, ValueError):
        return None
    if local.tzinfo is None:
        local = local.replace(tzinfo=EASTERN)
    return local.astimezone(timezone.utc)


def first_kickoffs_by_week(rows) -> dict[int, datetime]:
    """Return the first regular-season kickoff for each fantasy week."""
    first_kickoffs = {}
    for row in rows:
        if row.get('game_type') != 'REG':
            continue
        try:
            week = int(row.get('week'))
        except (TypeError, ValueError):
            continue
        if not 1 <= week <= 17:
            continue
        kickoff = row_kickoff(row)
        if kickoff and (week not in first_kickoffs or kickoff < first_kickoffs[week]):
            first_kickoffs[week] = kickoff
    return first_kickoffs


def reminder_period(
    first_kickoffs: dict[int, datetime],
    now: datetime,
    window: timedelta,
) -> tuple[int, datetime] | None:
    """Select the next week only when its first kickoff is inside the reminder window."""
    now = now.astimezone(timezone.utc)
    eligible = [
        (week, kickoff) for week, kickoff in first_kickoffs.items() if now < kickoff <= now + window
    ]
    return min(eligible, key=lambda item: item[1]) if eligible else None


def lineup_is_submitted(lineup: dict, starter_slots: dict[str, int]) -> bool:
    """Honor explicit submissions while retaining compatibility with complete legacy lineups."""
    if not isinstance(lineup, dict):
        return False
    if lineup.get('submitted_at'):
        return True
    return all(
        isinstance(lineup.get(position), list) and len(lineup[position]) == required
        for position, required in starter_slots.items()
    )


def missing_teams(
    team_codes: list[str],
    lineups: dict,
    starter_slots: dict[str, int],
    already_sent: set[str] | None = None,
) -> list[str]:
    already_sent = already_sent or set()
    return [
        team
        for team in team_codes
        if team not in already_sent
        and not lineup_is_submitted(lineups.get(team, {}), starter_slots)
    ]


def recipients_for(team: str) -> list[str]:
    email_var = (
        'GSA_EMAIL'
        if os.environ.get('DISABLE_EMAILS', '').lower() == 'true'
        else TEAM_EMAIL_VARS.get(team)
    )
    if not email_var:
        return []
    return sorted(
        {address.strip() for address in os.environ.get(email_var, '').split(',') if address.strip()}
    )


def send_email(subject: str, body: str, recipients: list[str]) -> bool:
    if not recipients:
        print(f'No email address configured for {subject}')
        return False

    smtp_user = os.environ.get('SMTP_USERNAME')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    if not smtp_user or not smtp_password:
        print('SMTP_USERNAME or SMTP_PASSWORD is not configured')
        return False

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = f'QPFL Bot <{smtp_user}>'
    message['To'] = ', '.join(recipients)
    message.set_content(body)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(message)
        return True
    except Exception as error:
        print(f'Could not send {subject}: {error}')
        return False


def load_schedule_rows(season: int):
    import nflreadpy as nfl

    return nfl.load_schedules(seasons=season).iter_rows(named=True)


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f'{path.suffix}.tmp')
    temporary_path.write_text(f'{json.dumps(state, indent=2)}\n', encoding='utf-8')
    temporary_path.replace(path)


def parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int)
    parser.add_argument('--now', help='Override the current time with an ISO 8601 timestamp')
    parser.add_argument('--window-hours', type=float, default=24)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    config = load_json(args.root / 'data' / 'league_config.json', {})
    season = args.season or int(config['current_season'])
    now = parse_now(args.now)
    first_kickoffs = first_kickoffs_by_week(load_schedule_rows(season))
    if not first_kickoffs:
        print(f'No regular-season kickoff data is available for {season}')
        return 1
    period = reminder_period(first_kickoffs, now, timedelta(hours=args.window_hours))
    if not period:
        print(f'No {season} first kickoff is within the next {args.window_hours:g} hours')
        return 0

    week, first_kickoff = period
    teams_data = load_json(args.root / 'data' / 'teams.json', {'teams': []})
    teams = teams_data.get('teams', [])
    team_codes = [team['abbrev'] for team in teams]
    team_names = {team['abbrev']: team.get('name', team['abbrev']) for team in teams}
    team_owners = {team['abbrev']: team.get('owner', 'Manager') for team in teams}
    starter_slots = {key: int(value) for key, value in config.get('starter_slots', {}).items()}
    if not team_codes or not starter_slots:
        print('Team or starter-slot configuration is empty')
        return 1

    lineup_path = args.root / 'data' / 'lineups' / str(season) / f'week_{week}.json'
    lineup_data = load_json(lineup_path, {'lineups': {}})
    lineups = lineup_data.get('lineups', {}) if isinstance(lineup_data, dict) else {}

    state_path = args.root / 'data' / 'lineup_reminders.json'
    state = load_json(state_path, {'sent': {}})
    sent_for_week = (
        state.setdefault('sent', {}).setdefault(str(season), {}).setdefault(str(week), {})
    )
    teams_to_remind = missing_teams(team_codes, lineups, starter_slots, set(sent_for_week))
    if not teams_to_remind:
        print(f'No unsent Week {week} lineup reminders are needed')
        return 0

    kickoff_label = first_kickoff.astimezone(EASTERN).strftime('%A, %B %-d at %-I:%M %p ET')
    site_url = os.environ.get('QPFL_SITE_URL', 'https://qpfl-scoring.vercel.app/#manage')
    failures = []
    sent_at = now.isoformat()

    for team in teams_to_remind:
        subject = f'QPFL Week {week}: lineup reminder'
        body = (
            f'Hi {team_owners[team]},\n\n'
            f'{team_names[team]} has not submitted a Week {week} lineup. '
            f'The first NFL game kicks off {kickoff_label}.\n\n'
            f'Set your lineup: {site_url}\n\n'
            'You will not receive another reminder for this week after this email.\n'
        )
        if args.dry_run:
            print(f'Would remind {team} for Week {week}')
            continue
        if send_email(subject, body, recipients_for(team)):
            sent_for_week[team] = sent_at
            print(f'Sent Week {week} lineup reminder to {team}')
        else:
            failures.append(team)

    if not args.dry_run and any(team in sent_for_week for team in teams_to_remind):
        write_state(state_path, state)

    if failures:
        print(f'Failed lineup reminders: {", ".join(failures)}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
