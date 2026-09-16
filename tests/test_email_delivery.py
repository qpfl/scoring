from datetime import datetime, timezone
from pathlib import Path

from scripts.email_delivery import (
    all_recipients,
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
    notify = (PROJECT_ROOT / '.github' / 'workflows' / 'notify.yml').read_text(
        encoding='utf-8'
    )

    assert 'View lineups: https://qpfl.org/' in notify
    assert 'View lineups: https://qpfl-scoring.vercel.app/' not in notify
