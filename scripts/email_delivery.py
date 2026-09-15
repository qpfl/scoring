#!/usr/bin/env python3
"""Shared SMTP delivery, recipient lookup, and JSON state helpers for QPFL emails."""

import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

# Co-owners who keep a separate address get an extra variable for the same team
# (JRW is the J/J co-owner), so each team maps to a tuple of secret names.
TEAM_EMAIL_VARS = {
    'GSA': ('GSA_EMAIL',),
    'CGK': ('CGK_EMAIL',),
    'CWR': ('CWR_EMAIL', 'CWR_COOWNER_EMAIL'),
    'AYP': ('AYP_EMAIL',),
    'AST': ('AST_EMAIL',),
    'WJK': ('WJK_EMAIL',),
    'SLS': ('SLS_EMAIL',),
    'RPA': ('RPA_EMAIL',),
    'S/T': ('S_T_EMAIL',),
    'J/J': ('J_J_EMAIL', 'JRW_EMAIL'),
}


def emails_disabled() -> bool:
    return os.environ.get('DISABLE_EMAILS', '').lower() == 'true'


def _addresses(*email_vars: str) -> set[str]:
    return {
        address.strip()
        for email_var in email_vars
        for address in os.environ.get(email_var, '').split(',')
        if address.strip()
    }


def recipients_for(team: str) -> list[str]:
    """Return the addresses for one team, or the commissioner when emails are disabled."""
    return recipients_for_teams([team])


def recipients_for_teams(teams: list[str]) -> list[str]:
    """Return de-duplicated addresses for one or more league teams."""
    if emails_disabled():
        return sorted(_addresses('GSA_EMAIL'))
    return sorted(
        _addresses(*(email_var for team in teams for email_var in TEAM_EMAIL_VARS.get(team, ())))
    )


def all_recipients() -> list[str]:
    """Return every team's addresses, or the commissioner when emails are disabled."""
    if emails_disabled():
        return sorted(_addresses('GSA_EMAIL'))
    return sorted(_addresses(*(var for vars_ in TEAM_EMAIL_VARS.values() for var in vars_)))


def eastern_timestamp(now: datetime | None = None) -> str:
    """Format an aware timestamp in America/New_York, including DST correctly."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %Y at %I:%M %p ET')


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


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


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
