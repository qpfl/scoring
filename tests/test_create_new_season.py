"""Tests for the season-freeze additions to scripts/create_new_season.py
(docs/DURABILITY_PLAN.md workstream 5): auto-updating protect_historical.yml
so a newly frozen season can't be forgotten (docs/ROADMAP_2026.md P0.7)."""

import json
from pathlib import Path

from scripts.create_new_season import add_historical_protection, update_season_index

PROTECT_YML = (
    Path(__file__).resolve().parent.parent / '.github' / 'workflows' / 'protect_historical.yml'
).read_text()


def test_adds_new_season_before_historical_catchall():
    updated = add_historical_protection(PROTECT_YML, 2026)
    assert updated is not None
    assert "- 'web/data_2026.json'" in updated
    # Must land before the catch-all glob, not after.
    assert updated.index('web/data_2026.json') < updated.index('web/data/historical/**')


def test_returns_none_when_already_present():
    updated = add_historical_protection(PROTECT_YML, 2025)
    assert updated is None


def test_returns_none_when_insertion_point_missing():
    assert add_historical_protection('no catch-all here', 2030) is None


def test_update_season_index_adds_and_marks_new_season(tmp_path):
    index_path = tmp_path / 'index.json'
    index_path.write_text('{"current_season": 2025, "seasons": [2025, 2024]}')

    assert update_season_index(index_path, 2026) is True

    index = json.loads(index_path.read_text())
    assert index['current_season'] == 2026
    assert index['seasons'] == [2026, 2025, 2024]


def test_update_season_index_dry_run_does_not_write(tmp_path):
    index_path = tmp_path / 'index.json'
    original = '{"current_season": 2025, "seasons": [2025]}'
    index_path.write_text(original)

    assert update_season_index(index_path, 2026, dry_run=True) is True
    assert index_path.read_text() == original
