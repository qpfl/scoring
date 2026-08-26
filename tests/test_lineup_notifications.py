from pathlib import Path

from scripts.lineup_notifications import format_lineup_notification, format_lineup_rows

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


def test_scoring_workflow_uses_the_tested_lineup_formatter():
    workflow = (PROJECT_ROOT / '.github' / 'workflows' / 'score.yml').read_text()

    assert 'from scripts.lineup_notifications import format_lineup_notification' in workflow
    assert 'body += format_lineup_notification(' in workflow
