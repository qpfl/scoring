import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.email_delivery import (
    LOGO_PATH,
    all_recipients,
    build_message,
    eastern_timestamp,
    recipients_for,
    recipients_for_teams,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_coowner_recipient_matrix(monkeypatch):
    monkeypatch.setenv('CWR_EMAIL', 'cwr@example.com')
    monkeypatch.setenv('CWR_COOWNER_EMAIL', 'coowner@example.com')
    monkeypatch.setenv('J_J_EMAIL', 'jj@example.com')
    monkeypatch.setenv('JRW_EMAIL', 'jrw@example.com')

    assert recipients_for('CWR') == ['coowner@example.com', 'cwr@example.com']
    assert recipients_for('J/J') == ['jj@example.com', 'jrw@example.com']
    assert recipients_for_teams(['CWR', 'J/J']) == [
        'coowner@example.com',
        'cwr@example.com',
        'jj@example.com',
        'jrw@example.com',
    ]
    assert set(all_recipients()) >= {
        'coowner@example.com',
        'cwr@example.com',
        'jj@example.com',
        'jrw@example.com',
    }


def test_disabled_email_mode_routes_everything_to_commissioner(monkeypatch):
    monkeypatch.setenv('DISABLE_EMAILS', 'true')
    monkeypatch.setenv('GSA_EMAIL', 'commissioner@example.com')
    monkeypatch.setenv('CWR_EMAIL', 'manager@example.com')

    assert recipients_for_teams(['CWR', 'J/J']) == ['commissioner@example.com']
    assert all_recipients() == ['commissioner@example.com']


def test_eastern_timestamp_uses_real_dst_boundaries():
    assert eastern_timestamp(datetime(2026, 7, 1, 16, tzinfo=timezone.utc)).endswith('12:00 PM ET')
    assert eastern_timestamp(datetime(2026, 12, 1, 17, tzinfo=timezone.utc)).endswith('12:00 PM ET')


def test_notification_workflows_use_shared_delivery_and_coowner_secrets():
    # Lineup/trade/transaction notifications live in notify.yml, split out of
    # score.yml so they don't share its concurrency group (docs/ROADMAP_2026.md
    # P3.1 / the in-season reliability plan, phase 2.5).
    workflows = [
        PROJECT_ROOT / '.github' / 'workflows' / 'notify.yml',
        PROJECT_ROOT / '.github' / 'workflows' / 'expire-trades.yml',
    ]
    for path in workflows:
        source = path.read_text(encoding='utf-8')
        assert 'from scripts.email_delivery import (' in source
        assert 'CWR_COOWNER_EMAIL: ${{ secrets.CWR_COOWNER_EMAIL }}' in source
        assert 'JRW_EMAIL: ${{ secrets.JRW_EMAIL }}' in source
        assert 'TEAM_EMAIL_VARS = {' not in source
        assert 'delivery_failures.append(subject)' in source

    # score.yml's own score-update summary email (send_score_update.py) and
    # failure alert still need the same secrets available.
    score_source = (PROJECT_ROOT / '.github' / 'workflows' / 'score.yml').read_text(
        encoding='utf-8'
    )
    assert 'CWR_COOWNER_EMAIL: ${{ secrets.CWR_COOWNER_EMAIL }}' in score_source
    assert 'JRW_EMAIL: ${{ secrets.JRW_EMAIL }}' in score_source


def test_lineup_notification_links_to_canonical_site():
    notify = (PROJECT_ROOT / '.github' / 'workflows' / 'notify.yml').read_text(encoding='utf-8')

    assert 'View lineups: https://qpfl.org/' in notify
    assert 'View lineups: https://qpfl-scoring.vercel.app/' not in notify


def test_messages_carry_text_html_and_the_inline_logo():
    message = build_message(
        'QPFL Week 8: Sunday scores',
        'plain body',
        ['a@example.com'],
        'bot@example.com',
        html='<p>rich body</p>',
    )

    assert message['From'] == 'QPFL Bot <bot@example.com>'
    assert message.get_body(('plain',)).get_content().strip() == 'plain body'
    assert '<p>rich body</p>' in message.get_body(('html',)).get_content()
    logo = next(part for part in message.walk() if part['Content-ID'] == '<qpfl-logo>')
    assert logo.get_content_type() == 'image/png'
    assert logo.get_content() == LOGO_PATH.read_bytes()


def test_text_only_messages_get_the_branded_frame():
    message = build_message(
        'QPFL: scoring health check failed',
        'Week 8 <stale>\nhttps://qpfl.org/',
        ['a@example.com'],
        'bot@example.com',
    )

    html = message.get_body(('html',)).get_content()
    assert 'cid:qpfl-logo' in html
    assert 'Week 8 &lt;stale&gt;' in html
    assert '<a href="https://qpfl.org/"' in html


def test_email_preview_workflow_can_only_reach_the_commissioner():
    workflow = (PROJECT_ROOT / '.github' / 'workflows' / 'email-preview.yml').read_text(
        encoding='utf-8'
    )
    script = (PROJECT_ROOT / 'scripts' / 'send_email_previews.py').read_text(encoding='utf-8')

    secrets = set(re.findall(r'secrets\.(\w+)', workflow))
    assert secrets == {'GSA_EMAIL', 'SMTP_USERNAME', 'SMTP_PASSWORD'}
    assert "os.environ['DISABLE_EMAILS'] = 'true'" in script
