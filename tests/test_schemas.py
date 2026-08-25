"""Schema regression tests (docs/DURABILITY_PLAN.md workstream 2).

qpfl/schemas.py models the *actual* on-disk shape of every file in data/, not
an aspirational redesign. These tests pin two things: (1) the real repo data
validates today, so the schemas can't silently drift from reality, and (2)
representative bad inputs are actually rejected, so the checker has teeth.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qpfl import schemas
from qpfl.constants import DATA_DIR
from qpfl.data_validation import validate_data_dir


def test_real_data_directory_validates_clean():
    errors = validate_data_dir(DATA_DIR)
    assert errors == [], '\n'.join(errors)


def test_rosters_file_rejects_unknown_team():
    with pytest.raises(ValidationError):
        schemas.RostersFile.model_validate({'ZZZ': []})


def test_rosters_file_rejects_unknown_position():
    with pytest.raises(ValidationError):
        schemas.RostersFile.model_validate(
            {'GSA': [{'name': 'Bad Player', 'nfl_team': 'BUF', 'position': 'LB'}]}
        )


def test_rosters_file_accepts_taxi_flag():
    parsed = schemas.RostersFile.model_validate(
        {'GSA': [{'name': 'Rookie Guy', 'nfl_team': 'BUF', 'position': 'RB', 'taxi': True}]}
    )
    assert parsed.root['GSA'][0].taxi is True


def test_lineup_week_file_rejects_starter_limit_shape_mismatch():
    """The per-team dict mixes position lists with string metadata keys —
    a string where a list is expected (or vice versa) must fail loudly."""
    with pytest.raises(ValidationError):
        schemas.LineupWeekFile.model_validate({'week': 1, 'lineups': {'GSA': {'QB': 'Josh Allen'}}})


def test_lineup_week_file_accepts_metadata_keys():
    parsed = schemas.LineupWeekFile.model_validate(
        {
            'week': 1,
            'lineups': {
                'GSA': {
                    'QB': ['Josh Allen'],
                    'submitted_at': '2026-09-08T12:00:00',
                    'comment': 'go team',
                }
            },
        }
    )
    assert parsed.lineups['GSA'].root['submitted_at'] == '2026-09-08T12:00:00'


def test_pending_trades_rejects_unknown_status():
    with pytest.raises(ValidationError):
        schemas.PendingTradesFile.model_validate(
            {
                'trades': [
                    {
                        'id': 'x',
                        'proposer': 'GSA',
                        'partner': 'CGK',
                        'proposer_gives': {'players': [], 'picks': []},
                        'proposer_receives': {'players': [], 'picks': []},
                        'status': 'not_a_real_status',
                        'proposed_at': '2026-01-01T00:00:00',
                        'week': 1,
                    }
                ]
            }
        )


def test_score_adjustment_shape():
    parsed = schemas.ScoreAdjustmentsFile.model_validate(
        [
            {
                'season': 2026,
                'week': 5,
                'team': 'GSA',
                'player': 'Andy Reid',
                'points': -5,
                'reason': 'fired',
            }
        ]
    )
    assert parsed.root[0].points == -5


def test_league_config_rejects_bad_slot_count():
    bad = {
        'current_season': 2026,
        'is_offseason': True,
        'trade_deadline_week': 12,
        'roster_slots': {'QB': 99},
        'starter_slots': {'QB': 1},
        'taxi_slots': 4,
        'playoff_structure': {'championship_seeds': [1, 2, 3, 4]},
        'regular_season_weeks': 15,
        'playoff_weeks': [16, 17],
    }
    with pytest.raises(ValidationError):
        schemas.LeagueConfig.model_validate(bad)


def test_league_config_requires_explicit_boolean_offseason_setting():
    config = json.loads(
        (Path(__file__).resolve().parent.parent / 'data/league_config.json').read_text()
    )
    config['is_offseason'] = 'true'

    with pytest.raises(ValidationError):
        schemas.LeagueConfig.model_validate(config)
