from datetime import datetime, timezone

from qpfl.week_status import latest_completed_week, week_games_are_final, week_is_locked


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


def _row(week, gameday, gametime, season=2026, game_type='REG'):
    return {
        'season': season,
        'week': week,
        'game_type': game_type,
        'gameday': gameday,
        'gametime': gametime,
    }


def test_week_is_locked_once_next_weeks_first_game_has_kicked_off():
    rows = [
        _row(1, '2026-09-11', '20:15'),
        _row(2, '2026-09-18', '20:15'),
        _row(2, '2026-09-21', '13:00'),
    ]
    before_kickoff = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)
    after_kickoff = datetime(2026, 9, 19, 1, 0, tzinfo=timezone.utc)
    assert week_is_locked(rows, 1, 2026, now=before_kickoff) is False
    assert week_is_locked(rows, 1, 2026, now=after_kickoff) is True


def test_week_is_locked_is_not_fooled_by_the_current_weeks_own_games_ending():
    """A week being complete is not the same as being locked - only the next
    week's kickoff locks it, even days after every game in this week is final."""
    rows = [
        _row(1, '2026-09-11', '20:15'),
        _row(2, '2026-09-18', '20:15'),
    ]
    week_1_over_but_week_2_not_started = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    assert week_is_locked(rows, 1, 2026, now=week_1_over_but_week_2_not_started) is False


def test_week_is_locked_fails_closed_with_no_resolvable_next_week_kickoff():
    assert week_is_locked([], 1, 2026, now=datetime.now(timezone.utc)) is False
    rows = [_row(2, None, None)]
    assert week_is_locked(rows, 1, 2026, now=datetime.now(timezone.utc)) is False


def test_week_is_locked_ignores_other_seasons_and_postseason_rows():
    rows = [
        _row(2, '2020-09-18', '20:15', season=2020),
        _row(2, '2026-09-18', '20:15', game_type='WC'),
    ]
    assert week_is_locked(rows, 1, 2026, now=datetime(2026, 9, 19, tzinfo=timezone.utc)) is False
