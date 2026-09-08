import json

from qpfl.availability import (
    build_availability_lookup,
    compact_roster_rows,
    is_listed_head_coach,
    load_coach_overrides,
)


def _roster_row(name, position, team, status):
    return {'full_name': name, 'position': position, 'team': team, 'status': status}


def test_compact_roster_rows_keeps_only_what_the_lookup_needs():
    rows = compact_roster_rows([{'full_name': 'A B', 'position': 'RB', 'team': 'GB', 'jersey': 8}])

    assert rows == [{'full_name': 'A B', 'team': 'GB', 'position': 'RB', 'status': None}]


def test_active_players_are_absent_from_the_lookup():
    lookup = build_availability_lookup([_roster_row('Josh Allen', 'QB', 'BUF', 'ACT')])

    assert lookup == {}


def test_non_active_roster_statuses_are_reported_with_a_reason():
    lookup = build_availability_lookup(
        [
            _roster_row('Josh Jacobs', 'RB', 'GB', 'EXE'),
            _roster_row('Some Rookie', 'WR', 'GB', 'DEV'),
            _roster_row('Old Timer', 'TE', 'GB', 'RET'),
            _roster_row('Hurt Guy', 'RB', 'KC', 'RES'),
            _roster_row('Mystery Code', 'K', 'KC', 'ZZZ'),
        ]
    )

    assert lookup == {
        'RB|josh jacobs': 'exempt',
        'WR|some rookie': 'practice_squad',
        'TE|old timer': 'retired',
        'RB|hurt guy': 'reserve',
        'K|mystery code': 'inactive',
    }


def test_non_fantasy_positions_are_ignored():
    lookup = build_availability_lookup([_roster_row('Some Guard', 'G', 'GB', 'CUT')])

    assert lookup == {}


def test_ambiguous_names_with_conflicting_statuses_are_skipped():
    lookup = build_availability_lookup(
        [
            _roster_row('Mike Williams', 'WR', 'NYJ', 'ACT'),
            _roster_row('Mike Williams', 'WR', 'PIT', 'CUT'),
        ]
    )

    assert lookup == {}


def test_matching_names_with_the_same_status_still_resolve():
    lookup = build_availability_lookup(
        [
            _roster_row('Mike Williams', 'WR', 'NYJ', 'CUT'),
            _roster_row('Mike Williams', 'WR', 'PIT', 'CUT'),
        ]
    )

    assert lookup == {'WR|mike williams': 'not_on_roster'}


def test_injury_designations_that_rule_a_player_out():
    lookup = build_availability_lookup(
        None,
        {
            'players': {
                'RB|out guy': {'status': 'Out', 'abbreviation': 'O'},
                'RB|shelved guy': {'status': 'Injured Reserve', 'abbreviation': 'IR'},
                'QB|iffy guy': {'status': 'Questionable', 'abbreviation': 'Q'},
                'WR|probable guy': {'status': 'Probable', 'abbreviation': 'P'},
            }
        },
    )

    assert lookup == {'RB|out guy': 'out', 'RB|shelved guy': 'ir'}


def test_injury_status_wins_over_a_generic_roster_status():
    lookup = build_availability_lookup(
        [_roster_row('Hurt Guy', 'RB', 'KC', 'RES')],
        {'players': {'RB|hurt guy': {'status': 'PUP'}}},
    )

    assert lookup == {'RB|hurt guy': 'pup'}


def test_empty_feeds_produce_an_empty_lookup():
    assert build_availability_lookup() == {}
    assert build_availability_lookup([], {}) == {}


def test_is_listed_head_coach_matches_across_punctuation_differences():
    assert is_listed_head_coach('Kevin O’Connell', "Kevin O'Connell", None)
    assert is_listed_head_coach('Mike Macdonald', 'Mike Macdonald', None)
    assert not is_listed_head_coach('Joe Brady', 'Sean McDermott', None)


def test_is_listed_head_coach_prefers_the_override():
    assert is_listed_head_coach('Joe Brady', 'Sean McDermott', 'Joe Brady')
    assert not is_listed_head_coach('Sean McDermott', 'Sean McDermott', 'Joe Brady')


def test_is_listed_head_coach_fails_open_without_a_reference():
    assert is_listed_head_coach('Anybody At All', None, None)


def test_load_coach_overrides_reads_and_normalizes(tmp_path):
    path = tmp_path / 'coach_overrides.json'
    path.write_text(
        json.dumps({'_comment': 'ignored', 'coaches': {'buf': ' Joe Brady ', 'KC': ''}}),
        encoding='utf-8',
    )

    assert load_coach_overrides(path) == {'BUF': 'Joe Brady'}


def test_load_coach_overrides_tolerates_a_missing_or_broken_file(tmp_path):
    assert load_coach_overrides(tmp_path / 'nope.json') == {}

    broken = tmp_path / 'broken.json'
    broken.write_text('{not json', encoding='utf-8')
    assert load_coach_overrides(broken) == {}

    wrong_shape = tmp_path / 'wrong.json'
    wrong_shape.write_text(json.dumps(['BUF']), encoding='utf-8')
    assert load_coach_overrides(wrong_shape) == {}
