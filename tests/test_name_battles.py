"""Tests for the automated "name battle" engine (qpfl/name_battles.py).

The engine derives who currently holds each contested name (Connor Bowl, Brother
Bowl, Kuhl Cup) from head-to-head game results, and rewrites owner display names
point-in-time. These tests use small synthetic fixtures plus the real
``data/name_battles.json`` config; they do not touch the network.
"""

from pathlib import Path

import pytest

from qpfl import name_battles as nb

CONFIG_PATH = Path(__file__).resolve().parent.parent / 'data' / 'name_battles.json'


def _week(num, *matchups, has_scores=True):
    """Build a week dict from (abbrev_a, score_a, abbrev_b, score_b) tuples."""
    return {
        'week': num,
        'has_scores': has_scores,
        'matchups': [
            {
                'team1': {'abbrev': a, 'total_score': sa},
                'team2': {'abbrev': b, 'total_score': sb},
            }
            for (a, sa, b, sb) in matchups
        ],
    }


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_config_loads_three_battles():
    battles = nb.load_config(CONFIG_PATH)
    ids = {b.id for b in battles}
    assert ids == {'connor_bowl', 'brother_bowl', 'kuhl_cup'}
    connor = next(b for b in battles if b.id == 'connor_bowl')
    assert connor.affects_first_name is True
    assert set(connor.combatants) == {'CGK', 'CWR'}


# --------------------------------------------------------------------------- #
# find_h2h_winner
# --------------------------------------------------------------------------- #
def test_h2h_picks_latest_meeting():
    weeks = [
        _week(5, ('CWR', 123.0, 'CGK', 88.0)),  # Reardon wins
        _week(12, ('CGK', 72.0, 'CWR', 47.0)),  # Kaminska wins (latest)
    ]
    assert nb.find_h2h_winner(weeks, 'CGK', 'CWR') == ('CGK', 12)


def test_h2h_ignores_unrelated_and_ties_and_unscored():
    weeks = [
        _week(1, ('CGK', 100.0, 'AYP', 90.0)),  # not the pair
        _week(2, ('CGK', 80.0, 'CWR', 80.0)),  # tie -> ignored
        _week(3, ('CGK', 0.0, 'CWR', 0.0), has_scores=False),  # unscored
    ]
    assert nb.find_h2h_winner(weeks, 'CGK', 'CWR') == (None, None)


def test_h2h_skips_zero_score_forfeit():
    # A 0 means no lineup submitted (bye/forfeit) and must not flip the title,
    # even though it is the latest meeting. Mirrors WJK's 0-78 week 17.
    weeks = [
        _week(10, ('WJK', 62.0, 'J/J', 44.0)),  # Bill wins (real game)
        _week(17, ('J/J', 78.0, 'WJK', 0.0)),  # Bill 0 -> skipped
    ]
    assert nb.find_h2h_winner(weeks, 'WJK', 'J/J') == ('WJK', 10)


# --------------------------------------------------------------------------- #
# apply_to_owner / apply_all
# --------------------------------------------------------------------------- #
def test_apply_redacts_loser_keeps_holder_canonical():
    battles = nb.load_config(CONFIG_PATH)
    holders = {'connor_bowl': 'CGK', 'brother_bowl': 'GSA', 'kuhl_cup': 'WJK'}
    assert nb.apply_all('Connor Kaminska', battles, holders) == 'Connor Kaminska'
    assert nb.apply_all('Connor Reardon', battles, holders) == 'Redacted Reardon'
    assert nb.apply_all('Ryan Ansel', battles, holders) == 'Ryan Redacted'  # last-name battle
    assert nb.apply_all('Griffin Ansel', battles, holders) == 'Griffin Ansel'


def test_apply_is_idempotent_on_already_redacted_input():
    battles = nb.load_config(CONFIG_PATH)
    holders = {'connor_bowl': 'CGK'}
    # Input already redacted but holder is CGK -> CWR stays redacted, CGK canonical.
    assert nb.apply_all('Redacted Reardon', battles, holders) == 'Redacted Reardon'
    assert nb.apply_all('Redacted Kaminska', battles, holders) == 'Connor Kaminska'


def test_apply_coowned_team_only_touches_the_combatant_substring():
    battles = nb.load_config(CONFIG_PATH)
    # Bill holds Kuhl -> Joe Kuhl becomes Joe Censored, but "Censored Ward" (a
    # non-combatant) must be left exactly as-is.
    holders = {'kuhl_cup': 'WJK'}
    assert (
        nb.apply_all('Joe Kuhl/Censored Ward', battles, holders)
        == 'Joe Censored/Censored Ward'
    )
    # Joe holds Kuhl -> stays canonical.
    holders = {'kuhl_cup': 'J/J'}
    assert (
        nb.apply_all('Joe Kuhl/Censored Ward', battles, holders) == 'Joe Kuhl/Censored Ward'
    )


# --------------------------------------------------------------------------- #
# Timing: a result in week N takes effect for weeks > N
# --------------------------------------------------------------------------- #
def test_holder_changes_the_week_after_the_game():
    battles = nb.load_config(CONFIG_PATH)
    weeks = [
        _week(5, ('CWR', 123.0, 'CGK', 88.0)),
        _week(12, ('CGK', 72.0, 'CWR', 47.0)),
    ]
    start = {'connor_bowl': 'CWR'}  # Reardon entered the season holding it
    # During and before week 12, Reardon still holds (game decides *after*).
    assert nb.holders_for_week(battles, weeks, start, 12)['connor_bowl'] == 'CWR'
    # Week 13 onward, Kaminska holds.
    assert nb.holders_for_week(battles, weeks, start, 13)['connor_bowl'] == 'CGK'
    # No games yet this season -> season-start holder.
    assert nb.holders_for_week(battles, weeks, start, 1)['connor_bowl'] == 'CWR'


# --------------------------------------------------------------------------- #
# Cross-season carryover
# --------------------------------------------------------------------------- #
def test_season_start_carries_from_most_recent_prior_season():
    battles = nb.load_config(CONFIG_PATH)
    prior_2025 = [_week(10, ('CGK', 72.0, 'CWR', 47.0))]  # Kaminska last won
    prior_2024 = [_week(8, ('CWR', 90.0, 'CGK', 70.0))]  # older Reardon win
    holders = nb.compute_season_start_holders(battles, [prior_2025, prior_2024])
    assert holders['connor_bowl'] == 'CGK'  # newest season wins


def test_season_start_falls_back_when_recent_season_had_no_meeting():
    battles = nb.load_config(CONFIG_PATH)
    prior_2025 = [_week(3, ('CGK', 50.0, 'AYP', 40.0))]  # no Connor H2H
    prior_2024 = [_week(8, ('CWR', 90.0, 'CGK', 70.0))]  # Reardon won here
    holders = nb.compute_season_start_holders(battles, [prior_2025, prior_2024])
    assert holders['connor_bowl'] == 'CWR'


def test_season_start_is_none_when_never_met():
    battles = nb.load_config(CONFIG_PATH)
    holders = nb.compute_season_start_holders(battles, [[_week(1, ('CGK', 5.0, 'AYP', 4.0))]])
    assert holders['connor_bowl'] is None


def test_current_holder_prefers_this_season_over_carryover():
    battles = nb.load_config(CONFIG_PATH)
    current = [_week(4, ('CWR', 100.0, 'CGK', 80.0))]  # Reardon won this season
    start = {'connor_bowl': 'CGK'}
    holders = nb.current_holders(battles, current, start)
    assert holders['connor_bowl'] == 'CWR'
    # With no current games, falls back to carryover.
    assert nb.current_holders(battles, [], start)['connor_bowl'] == 'CGK'


# --------------------------------------------------------------------------- #
# Transaction labels (point-in-time, first-name battles only)
# --------------------------------------------------------------------------- #
def test_first_name_label_point_in_time():
    battles = nb.load_config(CONFIG_PATH)
    seasons = {
        2024: [_week(10, ('CWR', 80.0, 'CGK', 60.0))],  # Reardon ended 2024 holding
        2025: [_week(12, ('CGK', 72.0, 'CWR', 47.0))],  # Kaminska wins wk12
    }
    # Early 2025 (before wk12): Reardon is "Connor", Kaminska "Redacted".
    assert nb.first_name_label_at('CWR', battles, seasons, 2025, 5) == 'Connor'
    assert nb.first_name_label_at('CGK', battles, seasons, 2025, 5) == 'Redacted'
    # Late 2025 (after wk12): flipped.
    assert nb.first_name_label_at('CGK', battles, seasons, 2025, 13) == 'Connor'
    assert nb.first_name_label_at('CWR', battles, seasons, 2025, 13) == 'Redacted'
    # Offseason (non-int week) carries from the prior season's end.
    assert nb.first_name_label_at('CGK', battles, seasons, 2026, 'Offseason') == 'Connor'


def test_first_name_label_none_for_last_name_battles():
    battles = nb.load_config(CONFIG_PATH)
    seasons = {2025: [_week(5, ('WJK', 80.0, 'J/J', 60.0))]}
    # Kuhl Cup / Brother Bowl don't change a first name -> no label override.
    assert nb.first_name_label_at('WJK', battles, seasons, 2025, 10) is None
    assert nb.first_name_label_at('GSA', battles, seasons, 2025, 10) is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
