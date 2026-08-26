import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from qpfl.schemas import TeamNamesFile
from qpfl.team_names import (
    apply_team_names,
    normalize_team_name_history,
    resolve_team_name,
)
from scripts.export_current import export_current_season


def test_normalizes_legacy_strings_and_seasonless_entries():
    history = normalize_team_name_history(
        {
            'GSA': 'First Name',
            'WJK': [{'effective_week': 8, 'name': 'Week Eight'}],
        }
    )

    assert history['GSA'] == [{'season': 2025, 'effective_week': 0, 'name': 'First Name'}]
    assert history['WJK'] == [{'season': 2025, 'effective_week': 8, 'name': 'Week Eight'}]


def test_normalizer_ignores_malformed_legacy_shapes():
    assert normalize_team_name_history(None) == {}
    assert normalize_team_name_history({'team_names': []}) == {}
    assert normalize_team_name_history({'GSA': 7}) == {}
    assert normalize_team_name_history({'GSA': [None]}) == {'GSA': []}


def test_resolver_preserves_history_and_carries_forward():
    history = {
        'GSA': [
            {'season': 2026, 'effective_week': 0, 'name': 'Spring Name'},
            {'season': 2026, 'effective_week': 8, 'name': 'Week Eight Name'},
            {'season': 2027, 'effective_week': 3, 'name': 'Future Name'},
        ]
    }

    assert resolve_team_name(history, 'GSA', 2025, 17, 'Original') == 'Original'
    assert resolve_team_name(history, 'GSA', 2026, 7, 'Original') == 'Spring Name'
    assert resolve_team_name(history, 'GSA', 2026, 8, 'Original') == 'Week Eight Name'
    assert resolve_team_name(history, 'GSA', 2027, 0, 'Original') == 'Week Eight Name'
    assert resolve_team_name(history, 'GSA', 2027, 3, 'Original') == 'Future Name'


def test_schema_validates_team_name_contract():
    parsed = TeamNamesFile.model_validate(
        {'team_names': {'GSA': [{'season': 2026, 'effective_week': 0, 'name': '  A Name  '}]}}
    )
    assert parsed.team_names['GSA'][0].name == 'A Name'

    with pytest.raises(ValidationError, match='Invalid team abbreviation'):
        TeamNamesFile.model_validate(
            {'team_names': {'BAD': [{'season': 2026, 'effective_week': 0, 'name': 'Nope'}]}}
        )
    with pytest.raises(ValidationError, match='control characters'):
        TeamNamesFile.model_validate(
            {'team_names': {'GSA': [{'season': 2026, 'effective_week': 0, 'name': 'Bad\nName'}]}}
        )


def test_apply_team_names_updates_current_and_point_in_time_surfaces():
    data = {
        'teams': [{'abbrev': 'GSA', 'name': 'Original'}],
        'standings': [{'abbrev': 'GSA', 'name': 'Original', 'team_name': 'Original'}],
    }
    data['weeks'] = [
        {
            'week': week,
            'teams': [{'abbrev': 'GSA', 'name': 'Original'}],
            'matchups': [
                {
                    'team1': {'abbrev': 'GSA', 'name': 'Original'},
                    'team2': {'abbrev': 'WJK', 'name': 'Other'},
                }
            ],
        }
        for week in (7, 8)
    ]
    history = {'GSA': [{'season': 2026, 'effective_week': 8, 'name': 'Renamed'}]}

    apply_team_names(data, history, 2026, 8)

    assert data['teams'][0]['name'] == 'Renamed'
    assert data['standings'][0]['team_name'] == 'Renamed'
    assert data['weeks'][0]['teams'][0]['name'] == 'Original'
    assert data['weeks'][1]['teams'][0]['name'] == 'Renamed'
    assert data['weeks'][1]['matchups'][0]['team1']['name'] == 'Renamed'


def test_apply_team_names_tolerates_wrapped_standings_and_incomplete_weeks():
    data = {
        'teams': [{'name': 'Missing abbreviation'}],
        'standings': {'standings': [{'abbrev': 'GSA', 'name': 'Original'}]},
        'weeks': [
            {'week': 'unknown', 'teams': []},
            {'week': 1, 'matchups': [{'team1': 'GSA', 'team2': None}]},
        ],
    }

    apply_team_names(data, {'GSA': 'Renamed'}, 2026, 1)

    assert data['standings']['standings'][0]['name'] == 'Renamed'


def test_current_export_applies_names_to_legacy_and_split_payloads(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    web_dir = tmp_path / 'web'
    season_dir = web_dir / 'data' / 'seasons' / '2026'
    season_dir.mkdir(parents=True)
    (season_dir / 'weeks').mkdir()
    teams = {
        'teams': [
            {'abbrev': 'GSA', 'name': 'Original GSA', 'owner': 'A'},
            {'abbrev': 'WJK', 'name': 'Original WJK', 'owner': 'B'},
        ]
    }
    (data_dir / 'teams.json').write_text(json.dumps(teams))
    (season_dir / 'meta.json').write_text(json.dumps({'season': 2026}))
    (season_dir / 'standings.json').write_text(
        json.dumps(
            {
                'standings': [
                    {
                        'abbrev': 'GSA',
                        'name': 'Original GSA',
                        'team_name': 'Original GSA',
                    }
                ]
            }
        )
    )
    (data_dir / 'team_names.json').write_text(
        json.dumps(
            {
                'team_names': {
                    'GSA': [
                        {
                            'season': 2026,
                            'effective_week': 1,
                            'name': 'Renamed GSA',
                        }
                    ]
                }
            }
        )
    )
    (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': False}))

    with (
        patch('scripts.export_current.get_current_nfl_week', return_value=1),
        patch('scripts.export_current.enrich_live_roster_context', return_value={}),
    ):
        data = export_current_season(data_dir, web_dir, 2026)

    assert data['teams'][0]['name'] == 'Renamed GSA'
    assert data['standings'][0]['name'] == 'Renamed GSA'
    meta = json.loads((web_dir / 'data' / 'seasons' / '2026' / 'meta.json').read_text())
    standings = json.loads((web_dir / 'data' / 'seasons' / '2026' / 'standings.json').read_text())
    assert meta['teams'][0]['name'] == 'Renamed GSA'
    assert standings['standings'][0]['name'] == 'Renamed GSA'
