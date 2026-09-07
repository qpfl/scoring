"""Tests for scripts/seed_fa_pool.py (docs/ROADMAP_2026.md P2.4)."""

import json

import polars as pl

from scripts.seed_fa_pool import lookup_player, normalize_team, split_position


def _player_db():
    """The (frame, name column, team column) tables lookup_player walks."""
    frame = pl.DataFrame(
        [
            {'display_name': 'Some Free Agent', 'team': 'KC', 'position': 'WR'},
            {'display_name': 'Another Guy', 'team': 'LA', 'position': 'RB'},
            {'display_name': 'Two Way Player', 'team': 'KC', 'position': 'CB'},
        ]
    )
    return [(frame, 'display_name', 'team')]


def test_lookup_player_exact_match():
    result = lookup_player(_player_db(), 'Some Free Agent')
    assert result == {'name': 'Some Free Agent', 'nfl_team': 'KC', 'position': 'WR'}


def test_lookup_player_normalizes_team_abbrev():
    result = lookup_player(_player_db(), 'Another Guy')
    assert result['nfl_team'] == 'LAR'


def test_lookup_player_not_found_returns_none():
    assert lookup_player(_player_db(), 'Nobody At All') is None


def test_lookup_player_falls_back_to_later_tables():
    empty = pl.DataFrame(schema={'full_name': pl.Utf8, 'position': pl.Utf8, 'team': pl.Utf8})
    tables = [(empty, 'full_name', 'team'), *_player_db()]
    assert lookup_player(tables, 'Some Free Agent')['nfl_team'] == 'KC'


def test_lookup_player_explicit_position_overrides_the_feed():
    result = lookup_player(_player_db(), 'Two Way Player', 'WR')
    assert result == {'name': 'Two Way Player', 'nfl_team': 'KC', 'position': 'WR'}


def test_split_position_parses_the_suffix():
    assert split_position('New York Giants:D/ST') == ('New York Giants', 'D/ST')
    assert split_position('Some Free Agent') == ('Some Free Agent', None)


def test_normalize_team_unmapped_passthrough():
    assert normalize_team('KC') == 'KC'
    assert normalize_team(None) == 'FA'


def test_main_appends_and_dedupes(tmp_path, monkeypatch, capsys):
    import scripts.seed_fa_pool as seed_fa_pool

    fa_pool_path = tmp_path / 'fa_pool.json'
    fa_pool_path.write_text(
        json.dumps(
            [{'name': 'Already Here', 'nfl_team': 'BUF', 'position': 'QB', 'available': True}]
        )
    )

    monkeypatch.setattr(seed_fa_pool, 'load_player_db', lambda season: _player_db())
    monkeypatch.setattr(
        'sys.argv',
        [
            'seed_fa_pool.py',
            'Some Free Agent',
            'Already Here',
            'Nobody At All',
            '--fa-pool',
            str(fa_pool_path),
        ],
    )

    seed_fa_pool.main()

    pool = json.loads(fa_pool_path.read_text())
    names = {p['name'] for p in pool}
    assert names == {'Already Here', 'Some Free Agent'}
    new_entry = next(p for p in pool if p['name'] == 'Some Free Agent')
    assert new_entry['available'] is True
    assert new_entry['nfl_team'] == 'KC'
