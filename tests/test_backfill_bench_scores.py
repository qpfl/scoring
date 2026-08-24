import json
from types import SimpleNamespace

from scripts import backfill_bench_scores as backfill


def test_backfill_scores_taxi_defense_with_canonical_position(tmp_path, monkeypatch):
    team = {
        'abbrev': 'WJK',
        'roster': [],
        'taxi_squad': [
            {
                'name': 'Atlanta Falcons',
                'nfl_team': 'ATL',
                'position': 'DEF',
                'score': 0,
            }
        ],
    }
    season_data = {
        'weeks': [
            {
                'week': 1,
                'has_scores': True,
                'matchups': [
                    {
                        'team1': team,
                        'team2': {'abbrev': 'CGK', 'roster': [], 'taxi_squad': []},
                    }
                ],
            }
        ]
    }
    web_dir = tmp_path / 'web'
    web_dir.mkdir()
    data_path = web_dir / 'data_2025.json'
    data_path.write_text(json.dumps(season_data))

    class Scorer:
        def score_player(self, name, nfl_team, position):
            assert (name, nfl_team, position) == ('Atlanta Falcons', 'ATL', 'D/ST')
            return SimpleNamespace(found_in_stats=True, total_points=7)

    class SeasonData:
        def __init__(self, season):
            assert season == 2025

        def scorer(self, week):
            assert week == 1
            return Scorer()

    monkeypatch.setattr(backfill, 'PROJECT_DIR', tmp_path)
    monkeypatch.setattr(backfill, 'SeasonData', SeasonData)

    stats = backfill.backfill_season(2025, write=True, validate=False, recompute_all=False)
    written_player = json.loads(data_path.read_text())['weeks'][0]['matchups'][0]['team1'][
        'taxi_squad'
    ][0]

    assert stats['filled'] == 1
    assert written_player['position'] == 'D/ST'
    assert written_player['score'] == 7
