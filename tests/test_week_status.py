from qpfl.week_status import latest_completed_week


def test_latest_completed_week_requires_every_game_to_be_final():
    rows = [
        {'week': 1, 'game_type': 'REG', 'result': 'A 21-17 B'},
        {'week': 1, 'game_type': 'REG', 'result': 'C 24-20 D'},
        {'week': 2, 'game_type': 'REG', 'result': 'E 10-7 F'},
        {'week': 2, 'game_type': 'REG', 'result': None},
    ]
    assert latest_completed_week(rows) == 1


def test_latest_completed_week_ignores_postseason_and_weeks_after_qpfl_finale():
    rows = [
        {'week': 17, 'game_type': 'REG', 'result': 'A 21-17 B'},
        {'week': 18, 'game_type': 'REG', 'result': 'C 24-20 D'},
        {'week': 1, 'game_type': 'WC', 'result': 'E 10-7 F'},
    ]
    assert latest_completed_week(rows) == 17


def test_latest_completed_week_returns_zero_before_any_week_finishes():
    assert latest_completed_week([{'week': 1, 'game_type': 'REG', 'result': None}]) == 0
