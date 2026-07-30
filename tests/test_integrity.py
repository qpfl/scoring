"""Cross-file integrity invariant tests (docs/DURABILITY_PLAN.md workstream 3)."""

from qpfl.constants import DATA_DIR
from qpfl.integrity import (
    check_all,
    check_draft_picks,
    check_lineup_starters_on_roster,
    check_pending_trades,
    check_roster_invariants,
    check_transaction_log_ordering,
)

LEAGUE_CONFIG = {
    'roster_slots': {'QB': 3, 'RB': 4, 'WR': 5, 'TE': 3, 'K': 2, 'D/ST': 2, 'HC': 2, 'OL': 2},
    'taxi_slots': 4,
}


def test_real_repo_data_has_no_integrity_violations():
    errors = check_all(DATA_DIR)
    assert errors == [], '\n'.join(errors)


def test_duplicate_player_across_rosters_flagged():
    rosters = {
        'GSA': [{'name': 'Josh Allen', 'nfl_team': 'BUF', 'position': 'QB'}],
        'CGK': [{'name': 'Josh Allen', 'nfl_team': 'BUF', 'position': 'QB'}],
    }
    errors = check_roster_invariants(rosters, LEAGUE_CONFIG)
    assert any('Josh Allen' in e and 'GSA' in e and 'CGK' in e for e in errors)


def test_same_nfl_team_name_as_dst_and_ol_on_different_teams_is_legal():
    """D/ST and OL are independent draftable pools sharing NFL team names."""
    rosters = {
        'GSA': [{'name': 'Chicago Bears', 'nfl_team': 'CHI', 'position': 'D/ST'}],
        'CGK': [{'name': 'Chicago Bears', 'nfl_team': 'CHI', 'position': 'OL'}],
    }
    errors = check_roster_invariants(rosters, LEAGUE_CONFIG)
    assert errors == []


def test_roster_slot_overflow_flagged():
    rosters = {
        'GSA': [{'name': f'QB{i}', 'nfl_team': 'BUF', 'position': 'QB'} for i in range(4)],
    }
    errors = check_roster_invariants(rosters, LEAGUE_CONFIG)
    assert any('exceeds limit' in e for e in errors)


def test_taxi_one_per_position_flagged():
    rosters = {
        'GSA': [
            {'name': 'A', 'nfl_team': 'BUF', 'position': 'RB', 'taxi': True},
            {'name': 'B', 'nfl_team': 'MIA', 'position': 'RB', 'taxi': True},
        ],
    }
    errors = check_roster_invariants(rosters, LEAGUE_CONFIG)
    assert any('more than one RB' in e for e in errors)


def test_lineup_starter_not_on_roster_flagged():
    rosters = {'GSA': [{'name': 'Josh Allen', 'nfl_team': 'BUF', 'position': 'QB'}]}
    lineup_file = {'week': 1, 'lineups': {'GSA': {'QB': ['Some Rando']}}}
    errors = check_lineup_starters_on_roster(lineup_file, rosters)
    assert any('Some Rando' in e for e in errors)


def test_lineup_starter_on_taxi_squad_flagged():
    rosters = {
        'GSA': [{'name': 'Taxi Guy', 'nfl_team': 'BUF', 'position': 'RB', 'taxi': True}],
    }
    lineup_file = {'week': 1, 'lineups': {'GSA': {'RB': ['Taxi Guy']}}}
    errors = check_lineup_starters_on_roster(lineup_file, rosters)
    assert any('Taxi Guy' in e for e in errors)


def test_pending_trade_offering_unowned_player_flagged():
    rosters = {'GSA': [{'name': 'Josh Allen', 'nfl_team': 'BUF', 'position': 'QB'}]}
    pending = {
        'trades': [
            {
                'id': 'x',
                'proposer': 'GSA',
                'partner': 'CGK',
                'status': 'pending',
                'proposed_at': '2026-01-01T00:00:00',
                'proposer_gives': {'players': ['Not Owned Guy'], 'picks': []},
            }
        ]
    }
    errors = check_pending_trades(pending, rosters)
    assert any('Not Owned Guy' in e for e in errors)


def test_trade_stuck_in_progress_flagged():
    rosters = {'GSA': []}
    pending = {
        'trades': [
            {
                'id': 'stuck1',
                'proposer': 'GSA',
                'partner': 'CGK',
                'status': 'accepted',
                'execution': 'in_progress',
                'proposed_at': '2020-01-01T00:00:00',
                'proposer_gives': {'players': [], 'picks': []},
            }
        ]
    }
    errors = check_pending_trades(pending, rosters)
    assert any('stuck1' in e for e in errors)


def test_duplicate_draft_pick_flagged():
    draft_picks = {
        'picks': [
            {
                'year': '2027',
                'round': 1,
                'draft_type': 'offseason',
                'original_team': 'GSA',
                'current_owner': 'GSA',
            },
            {
                'year': '2027',
                'round': 1,
                'draft_type': 'offseason',
                'original_team': 'GSA',
                'current_owner': 'CGK',
            },
        ]
    }
    errors = check_draft_picks(draft_picks)
    assert any('appears 2 times' in e for e in errors)


def test_draft_pick_unknown_owner_flagged():
    draft_picks = {
        'picks': [
            {
                'year': '2027',
                'round': 1,
                'draft_type': 'offseason',
                'original_team': 'GSA',
                'current_owner': 'ZZZ',
            },
        ]
    }
    errors = check_draft_picks(draft_picks)
    assert any('not a known team' in e for e in errors)


def test_transaction_log_out_of_order_flagged():
    log = {
        'transactions': [
            {'type': 'trade', 'timestamp': '2026-01-01T00:00:00'},
            {'type': 'trade', 'timestamp': '2026-06-01T00:00:00'},
        ]
    }
    errors = check_transaction_log_ordering(log)
    assert any('newest-first' in e for e in errors)


def test_transaction_log_placeholder_timestamps_excluded_from_ordering():
    log = {
        'transactions': [
            {'type': 'transaction', 'timestamp': '2023-01-01T00:00:00'},
            {'type': 'transaction', 'timestamp': '2023-01-01T00:00:00'},
        ]
    }
    assert check_transaction_log_ordering(log) == []


def test_transaction_log_legacy_date_format_parses():
    log = {
        'transactions': [
            {'type': 'trade', 'timestamp': '11-15-23T00:00:00'},
            {'type': 'trade', 'timestamp': '11-11-23T00:00:00'},
        ]
    }
    assert check_transaction_log_ordering(log) == []
