from pathlib import Path

from scripts.lineup_notifications import (
    format_lineup_notification,
    format_lineup_rows,
    lineup_changed,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_first_submission_lists_every_starter_without_change_markers():
    lineup = {
        'QB': ['Patrick Mahomes II'],
        'RB': ['Saquon Barkley', 'Derrick Henry'],
        'submitted_at': '2026-08-26T22:14:48+00:00',
    }

    assert format_lineup_rows(lineup, {}) == [
        '  QB: Patrick Mahomes II',
        '  RB: Saquon Barkley',
        '  RB: Derrick Henry',
    ]


def test_update_lists_unchanged_starters_and_highlights_one_for_one_swap():
    previous = {
        'QB': ['Patrick Mahomes II'],
        'RB': ['Saquon Barkley', 'Derrick Henry'],
        'submitted_at': '2026-08-26T22:14:48+00:00',
    }
    lineup = {
        'QB': ['Patrick Mahomes II'],
        'RB': ['Saquon Barkley', 'TreVeyon Henderson'],
        'submitted_at': '2026-08-26T23:14:48+00:00',
    }

    assert format_lineup_rows(lineup, previous) == [
        '  QB: Patrick Mahomes II',
        '  RB: Saquon Barkley',
        '  RB: Derrick Henry → TreVeyon Henderson  [CHANGED]',
    ]


def test_update_marks_additions_and_opened_slots():
    previous = {
        'RB': ['Saquon Barkley'],
        'WR': ['Justin Jefferson'],
        'submitted_at': '2026-08-26T22:14:48+00:00',
    }
    lineup = {
        'RB': ['Saquon Barkley', 'TreVeyon Henderson'],
        'WR': [],
        'submitted_at': '2026-08-26T23:14:48+00:00',
    }

    assert format_lineup_rows(lineup, previous) == [
        '  RB: Saquon Barkley',
        '  RB: [OPEN] → TreVeyon Henderson  [CHANGED]',
        '  WR: Justin Jefferson → [OPEN]  [CHANGED]',
    ]


def test_notification_includes_submitted_comment():
    notification = format_lineup_notification(
        'GSA',
        'Griff',
        1,
        {
            'QB': ['Patrick Mahomes II'],
            'comment': 'Testing submission',
            'submitted_at': '2026-08-26T22:14:48+00:00',
        },
    )

    assert 'Week 1 - Griff (GSA)' in notification
    assert '  QB: Patrick Mahomes II' in notification
    assert 'Message from Griff:\n"Testing submission"' in notification


def test_resave_with_only_new_timestamp_is_not_a_change():
    previous = {'QB': ['Bo Nix'], 'submitted_at': '2026-09-22T15:51:35+00:00'}
    current = {'QB': ['Bo Nix'], 'submitted_at': '2026-09-25T19:48:22+00:00'}

    assert lineup_changed(current, previous) is False


def test_comment_or_starter_change_is_a_change():
    previous = {'QB': ['Bo Nix'], 'submitted_at': '2026-09-22T15:51:35+00:00'}

    assert lineup_changed({**previous, 'comment': 'Locked in'}, previous) is True
    assert lineup_changed({**previous, 'QB': ['Josh Allen']}, previous) is True
    assert lineup_changed(previous, {}) is True


def test_notify_workflow_uses_the_tested_lineup_formatter():
    """Lineup/trade/transaction notifications live in their own workflow
    (notify.yml), split out of score.yml so they don't share its concurrency
    group - see docs/ROADMAP_2026.md P3.1 / the in-season reliability plan,
    phase 2.5."""
    workflow = (PROJECT_ROOT / '.github' / 'workflows' / 'notify.yml').read_text()

    assert (
        'from scripts.lineup_notifications import format_lineup_notification, lineup_changed'
        in workflow
    )
    assert 'if lineup_changed(lineup, prev_lineup):' in workflow
    assert 'body += format_lineup_notification(' in workflow


def test_notify_workflow_has_no_concurrency_group():
    """Every push must get its own notify run - a shared/queued concurrency
    group is exactly the bug being fixed (a cancelled pending run's
    notifications were never sent)."""
    workflow = (PROJECT_ROOT / '.github' / 'workflows' / 'notify.yml').read_text()

    assert 'concurrency:' not in workflow


def test_score_workflow_no_longer_sends_lineup_trade_transaction_notifications():
    workflow = (PROJECT_ROOT / '.github' / 'workflows' / 'score.yml').read_text()

    assert 'format_lineup_notification' not in workflow
    assert 'TRADE NOTIFICATIONS' not in workflow
