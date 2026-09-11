from qpfl.week_status import latest_completed_week, week_games_are_final


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


def test_week_games_are_final_requires_the_whole_week():
    """The Thursday game being over is the exact case this exists to reject."""
    rows = [
        {'season': 2026, 'week': 1, 'game_type': 'REG', 'result': 'A 21-17 B'},
        {'season': 2026, 'week': 1, 'game_type': 'REG', 'result': None},
        {'season': 2026, 'week': 2, 'game_type': 'REG', 'result': None},
    ]
    assert week_games_are_final(rows, 1) is False
    assert week_games_are_final(rows, 2) is False

    rows[1]['result'] = 'C 24-20 D'
    assert week_games_are_final(rows, 1) is True


def test_week_games_are_final_is_false_for_a_week_with_no_games():
    assert week_games_are_final([], 1) is False
    assert week_games_are_final([{'week': 2, 'game_type': 'REG', 'result': 'A 1-0 B'}], 1) is False


def test_week_games_are_final_ignores_other_seasons_when_given_one():
    """Projection history carries the prior season, whose games are all final."""
    rows = [
        {'season': 2025, 'week': 1, 'game_type': 'REG', 'result': 'A 21-17 B'},
        {'season': 2026, 'week': 1, 'game_type': 'REG', 'result': None},
    ]
    assert week_games_are_final(rows, 1, 2026) is False
    assert week_games_are_final(rows, 1, 2025) is True
    # Without a season the prior year's finals cannot rescue an unplayed week.
    assert week_games_are_final(rows, 1) is False


def test_week_games_are_final_ignores_postseason_games():
    rows = [
        {'season': 2026, 'week': 1, 'game_type': 'REG', 'result': 'A 21-17 B'},
        {'season': 2026, 'week': 1, 'game_type': 'WC', 'result': None},
    ]
    assert week_games_are_final(rows, 1, 2026) is True
