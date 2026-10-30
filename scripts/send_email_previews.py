#!/usr/bin/env python3
"""Send one of each QPFL email to the commissioner only, to check how they render.

Always runs with DISABLE_EMAILS=true, so every message goes to GSA_EMAIL and no
other manager. Scores come from the current season's latest weeks; the lineup,
trade, roster-move, and admin-alert emails use sample data. Subjects are
prefixed "[Preview]".
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ['DISABLE_EMAILS'] = 'true'

from scripts import email_html as html  # noqa: E402
from scripts import send_score_update as scores  # noqa: E402
from scripts.email_delivery import all_recipients, load_json, send_email  # noqa: E402
from scripts.lineup_notifications import (  # noqa: E402
    format_lineup_notification,
    lineup_notification_html,
)
from scripts.transaction_emails import roster_moves_html, trade_html  # noqa: E402

SITE = 'https://qpfl.org/'

PREVIOUS_LINEUP = {
    'QB': ['Josh Allen'],
    'RB': ['James Cook III', 'Javonte Williams'],
    'WR': ['Zay Flowers', 'DK Metcalf'],
    'TE': ['Kyle Pitts'],
    'K': ['Jason Myers'],
    'D/ST': ['Chicago Bears'],
    'HC': ['Mike Macdonald'],
    'OL': ['Buffalo Bills'],
    'submitted_at': '2026-10-29T20:00:00+00:00',
}
LINEUP = {
    **PREVIOUS_LINEUP,
    'WR': ['Zay Flowers', 'DJ Moore'],
    'comment': 'Sample message from the manager',
    'submitted_at': '2026-10-29T21:00:00+00:00',
}


def score_emails(root: Path, season: int, now: datetime) -> list[tuple[str, str, str]]:
    season_dir = root / 'web' / 'data' / 'seasons' / str(season)
    weeks = scores.load_week_files(season_dir / 'weeks')
    standings = (load_json(season_dir / 'standings.json', {}) or {}).get('standings', [])
    finished = [week for week, data in weeks.items() if data.get('games_final')]
    in_progress = [week for week, data in weeks.items() if data.get('has_scores')]
    emails = []
    for week, slot in (
        (max(finished, default=None), 'final'),
        (max(in_progress, default=None), 'sunday'),
    ):
        if week is None or (slot == 'sunday' and week in finished):
            continue
        args = (week, slot, weeks[week], standings, now, SITE, weeks.get(16))
        emails.append(
            (
                f'QPFL Week {week}: {scores.SLOT_LABELS[slot]}',
                scores.build_body(*args),
                scores.build_html(*args),
            )
        )
    return emails


def sample_emails(stamp: str) -> list[tuple[str, str, str | None]]:
    return [
        (
            'CGK Lineup Week 8 (sample)',
            format_lineup_notification('CGK', 'Kaminska', 8, LINEUP, PREVIOUS_LINEUP),
            html.render_email(
                'Week 8 lineup update',
                stamp,
                [lineup_notification_html('CGK', 'Kaminska', 8, LINEUP, PREVIOUS_LINEUP)],
                cta=('View lineups', SITE),
            ),
        ),
        (
            'QPFL Trade Proposal (sample)',
            'Sample trade proposal',
            trade_html(
                'pending',
                stamp,
                'Griff (GSA)',
                'Arnav (AYP)',
                ['RB Bijan Robinson (ATL)', '2027 Round 2 pick'],
                ['WR Puka Nacua (LAR) [Condition: if healthy]'],
                comment='Sample trade message',
                comment_by='Griff',
            ),
        ),
        (
            'QPFL Roster Move (sample)',
            'Sample roster move',
            roster_moves_html(
                8,
                stamp,
                [
                    {
                        'type': 'Fa Pickup',
                        'team': 'Bill (WJK)',
                        'added': 'WR Romeo Doubs (GB)',
                        'released': 'TE Cade Otton (TB)',
                        'takes_effect': 'Week 9',
                    }
                ],
            ),
        ),
        (
            'QPFL: admin alert (sample)',
            'Sample admin alert\n==============================\n'
            'Plain-text emails are wrapped in the branded frame.\n\nhttps://qpfl.org/',
            None,
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=_PROJECT_ROOT)
    args = parser.parse_args()

    recipients = all_recipients()
    if not recipients:
        print('GSA_EMAIL is not configured')
        return 1

    config = load_json(args.root / 'data' / 'league_config.json', {}) or {}
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(scores.EASTERN).strftime('%b %d, %Y at %-I:%M %p ET')
    emails = score_emails(args.root, int(config['current_season']), now) + sample_emails(stamp)

    failures = 0
    for subject, body, html_body in emails:
        if send_email(f'[Preview] {subject}', body, recipients, html=html_body):
            print(f'Sent: {subject}')
        else:
            failures += 1
    print(f'{len(emails) - failures} of {len(emails)} previews sent to the commissioner')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
