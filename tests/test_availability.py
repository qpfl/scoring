import json

from qpfl.availability import (
    build_availability_lookup,
    compact_depth_chart_rows,
    compact_roster_rows,
    is_listed_head_coach,
    load_coach_overrides,
)


def _roster_row(name, position, team, status):
    return {'full_name': name, 'position': position, 'team': team, 'status': status}


def _depth_row(name, team, pos_abb, pos_rank, dt='2026-09-14T00:00:00Z'):
    return {'dt': dt, 'team': team, 'player_name': name, 'pos_abb': pos_abb, 'pos_rank': pos_rank}


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


def test_compact_depth_chart_rows_keeps_only_what_the_lookup_needs():
    rows = compact_depth_chart_rows(
        [{'dt': '2026-09-14', 'team': 'BUF', 'player_name': 'Kyle Allen', 'pos_abb': 'QB',
          'pos_rank': 2, 'espn_id': 'x'}]
    )

    assert rows == [
        {'dt': '2026-09-14', 'team': 'BUF', 'player_name': 'Kyle Allen', 'pos_abb': 'QB', 'pos_rank': 2}
    ]


def test_healthy_backup_qb_projects_a_backup_reason():
    lookup = build_availability_lookup(
        depth_chart_rows=[
            _depth_row('Josh Allen', 'BUF', 'QB', 1),
            _depth_row('Kyle Allen', 'BUF', 'QB', 2),
        ]
    )

    assert lookup == {'QB|kyle allen': 'backup'}


def test_the_starter_himself_is_never_marked_a_backup():
    lookup = build_availability_lookup(
        depth_chart_rows=[
            _depth_row('Josh Allen', 'BUF', 'QB', 1),
            _depth_row('Kyle Allen', 'BUF', 'QB', 2),
        ]
    )

    assert 'QB|josh allen' not in lookup


def test_backup_is_not_zeroed_when_the_starter_ahead_is_hurt():
    """An injured starter promotes the backup to a real workload - the depth
    chart can lag that by a day or two, so it must not zero the new starter."""
    lookup = build_availability_lookup(
        [_roster_row('Josh Allen', 'QB', 'BUF', 'RES')],
        depth_chart_rows=[
            _depth_row('Josh Allen', 'BUF', 'QB', 1),
            _depth_row('Kyle Allen', 'BUF', 'QB', 2),
        ],
    )

    assert lookup == {'QB|josh allen': 'reserve'}


def test_third_string_qb_is_zeroed_only_if_someone_ahead_is_healthy():
    lookup = build_availability_lookup(
        depth_chart_rows=[
            _depth_row('Josh Allen', 'BUF', 'QB', 1),
            _depth_row('Kyle Allen', 'BUF', 'QB', 2),
            _depth_row('Shane Buechele', 'BUF', 'QB', 3),
        ]
    )

    assert lookup == {'QB|kyle allen': 'backup', 'QB|shane buechele': 'backup'}


def test_non_qb_backups_are_left_alone():
    """WR2/RB2 aren't the all-or-nothing case this exists for - a real backup
    at those positions routinely starts or splits a committee."""
    lookup = build_availability_lookup(
        depth_chart_rows=[
            _depth_row('Star Receiver', 'KC', 'WR', 1),
            _depth_row('Second Receiver', 'KC', 'WR', 2),
        ]
    )

    assert lookup == {}


def test_only_the_latest_depth_chart_snapshot_counts():
    """An earlier snapshot where the backup was still ranked 1 (before a trade
    or a demotion) must not stick around once a newer one supersedes it."""
    lookup = build_availability_lookup(
        depth_chart_rows=[
            _depth_row('Kyle Allen', 'BUF', 'QB', 1, dt='2026-03-01T00:00:00Z'),
            _depth_row('Josh Allen', 'BUF', 'QB', 1, dt='2026-09-14T00:00:00Z'),
            _depth_row('Kyle Allen', 'BUF', 'QB', 2, dt='2026-09-14T00:00:00Z'),
        ]
    )

    assert lookup == {'QB|kyle allen': 'backup'}


def test_injury_reason_wins_over_a_backup_designation():
    """A backup with his own injury designation keeps that reason rather than
    being overwritten by the generic 'backup' one."""
    lookup = build_availability_lookup(
        [_roster_row('Kyle Allen', 'QB', 'BUF', 'RES')],
        depth_chart_rows=[
            _depth_row('Josh Allen', 'BUF', 'QB', 1),
            _depth_row('Kyle Allen', 'BUF', 'QB', 2),
        ],
    )

    assert lookup == {'QB|kyle allen': 'reserve'}


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
