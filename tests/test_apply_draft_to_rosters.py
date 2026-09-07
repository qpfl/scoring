"""Tests for scripts/apply_draft_to_rosters.py."""

import pytest

from scripts.apply_draft_to_rosters import (
    DraftApplier,
    normalize,
    parse_player_cell,
    split_drops,
    team_code,
)


@pytest.fixture
def applier(monkeypatch):
    """A DraftApplier with the nflreadpy lookups stubbed out."""
    monkeypatch.setattr(
        'scripts.apply_draft_to_rosters.load_lookups',
        lambda season: (
            {'new guy': 'WR', 'backup qb': 'QB'},
            {'new guy': 'KC'},
            {'some coach'},
            {'chicago bears', 'green bay packers'},
        ),
    )
    rosters = {
        'GSA': [
            {'name': 'Old Guy', 'nfl_team': 'SF', 'position': 'WR'},
            {'name': 'Chicago Bears', 'nfl_team': 'CHI', 'position': 'D/ST'},
        ],
        'CGK': [
            {'name': 'Chicago Bears', 'nfl_team': 'CHI', 'position': 'OL'},
            {'name': 'Jake Elliott', 'nfl_team': 'PHI', 'position': 'K'},
        ],
    }
    return DraftApplier(rosters, 2026)


def test_parse_player_cell_tolerates_workbook_bracket_typos():
    assert parse_player_cell('Zach Ertz {WAS)') == ('Zach Ertz', 'WAS')
    assert parse_player_cell('Jonnu Smith (GB(') == ('Jonnu Smith', 'GB')
    assert parse_player_cell('Ty Simpson (LA)') == ('Ty Simpson', 'LAR')
    assert parse_player_cell('Unlabelled Player') == ('Unlabelled Player', '')


def test_parse_player_cell_straightens_apostrophes():
    assert parse_player_cell('Wan’Dale Robinson (TEN)') == ("Wan'Dale Robinson", 'TEN')


def test_team_code_strips_the_via_chain():
    assert team_code('RPA (via J/J → WJK → CWR)') == 'RPA'
    assert team_code('S/T') == 'S/T'


def test_split_drops_handles_a_two_player_cell():
    assert split_drops('Tyrone Tracy Jr., Aaron Jones Sr.') == [
        'Tyrone Tracy Jr.',
        'Aaron Jones Sr.',
    ]


def test_normalize_ignores_suffixes_and_punctuation():
    assert normalize('Michael Penix Jr.') == normalize('Michael Penix')


def test_a_pick_drops_and_adds_on_the_same_roster(applier):
    applier.apply_pick(
        '1', {'pick': '1', 'team': 'GSA', 'player': 'New Guy (KC)', 'dropped': 'Old Guy'}
    )

    names = {p['name']: p for p in applier.rosters['GSA']}
    assert 'Old Guy' not in names
    assert names['New Guy'] == {'name': 'New Guy', 'nfl_team': 'KC', 'position': 'WR'}
    assert applier.warnings == []


def test_a_pass_still_records_its_drop(applier):
    applier.apply_pick('4', {'pick': '1', 'team': 'GSA', 'player': 'PASS', 'dropped': 'Old Guy'})

    assert [p['name'] for p in applier.rosters['GSA']] == ['Chicago Bears']


def test_taxi_rounds_flag_the_selection(applier):
    applier.apply_pick('TAXI Round 1', {'pick': '1', 'team': 'CGK', 'player': 'Backup QB (KC)'})

    added = next(p for p in applier.rosters['CGK'] if p['name'] == 'Backup QB')
    assert added['taxi'] is True


def test_a_misspelled_drop_matches_the_rostered_player(applier):
    applier.apply_pick(
        '3', {'pick': '1', 'team': 'CGK', 'player': 'PASS', 'dropped': 'Jake Elliot'}
    )

    assert 'Jake Elliott' not in {p['name'] for p in applier.rosters['CGK']}
    assert applier.corrections == ["CGK: read 'Jake Elliot' as 'Jake Elliott'"]
    assert applier.warnings == []


def test_a_team_unit_replaces_its_own_kind_and_leaves_the_other_pool_alone(applier):
    """ "Chicago Bears" can be one roster's D/ST and another's OL at once."""
    applier.apply_pick(
        '4',
        {
            'pick': '1',
            'team': 'CGK',
            'player': 'Green Bay Packers (GB)',
            'dropped': 'Chicago Bears',
        },
    )

    assert {(p['name'], p['position']) for p in applier.rosters['CGK']} == {
        ('Green Bay Packers', 'OL'),
        ('Jake Elliott', 'K'),
    }
    # GSA's Chicago Bears D/ST is a different asset and must survive.
    assert ('Chicago Bears', 'D/ST') in {(p['name'], p['position']) for p in applier.rosters['GSA']}


def test_an_unresolvable_position_warns_rather_than_guessing(applier):
    applier.apply_pick('6', {'pick': '1', 'team': 'GSA', 'player': 'Mystery Rookie (NYJ)'})

    assert applier.warnings == [
        "6.1 GSA: could not resolve a position for 'Mystery Rookie'",
    ]
