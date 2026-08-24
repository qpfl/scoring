import json
from pathlib import Path

from qpfl.lore import build_league_lore, build_week_chronicle, export_league_lore

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _player(name, position, score, starter):
    return {'name': name, 'position': position, 'score': score, 'starter': starter}


def _team(abbrev, name, score, roster):
    return {'abbrev': abbrev, 'name': name, 'total_score': score, 'roster': roster}


def _week():
    return {
        'week': 5,
        'has_scores': True,
        'matchups': [
            {
                'team1': _team(
                    'CGK',
                    'Team Kaminska',
                    20,
                    [_player('Starter A', 'QB', 20, True), _player('Bench A', 'QB', 25, False)],
                ),
                'team2': _team(
                    'CWR',
                    'Team Reardon',
                    21,
                    [_player('Starter B', 'QB', 21, True), _player('Bench B', 'QB', 0, False)],
                ),
            }
        ],
    }


def _config():
    return {
        'rivalries': [
            {
                'id': 'connor_bowl',
                'name': 'Connor Bowl',
                'teams': ['CGK', 'CWR'],
                'description': 'A name is at stake.',
                'stakes': 'Winner keeps the name.',
            }
        ],
        'moments': [],
        'season_notes': {},
        'superlatives': [],
    }


def test_completed_week_gets_deterministic_story_awards_and_lineup_counterfactual():
    chronicle = build_week_chronicle(
        2025,
        _week(),
        {'schedule': [{'week': 5, 'is_rivalry': True}]},
        _config()['rivalries'],
    )

    assert chronicle['headline'] == 'Team Reardon claims the Connor Bowl'
    assert {award['id'] for award in chronicle['awards']} == {
        'weekly_king',
        'nail_biter',
        'beatdown',
        'top_player',
        'heartbreak',
        'bench_crime',
    }
    assert chronicle['matchups'][0]['official_rivalry'] is True
    assert 'flipped the result' in chronicle['matchups'][0]['summary']
    assert chronicle['matchups'][0]['lineup_analysis']['CGK']['optimal'] == 25


def test_incomplete_week_does_not_receive_a_chronicle():
    week = _week()
    week['has_scores'] = False
    assert build_week_chronicle(2025, week, {}, _config()['rivalries']) is None


def test_tied_matchup_does_not_receive_a_heartbreak_award():
    week = _week()
    week['matchups'][0]['team1']['total_score'] = 21
    chronicle = build_week_chronicle(2025, week, {}, _config()['rivalries'])

    assert chronicle['matchups'][0]['winner'] is None
    assert 'tied at 21.0' in chronicle['matchups'][0]['summary']
    assert 'heartbreak' not in {award['id'] for award in chronicle['awards']}


def test_rivalry_book_tracks_all_meetings_official_record_holder_and_next_game():
    meta = {
        'season': 2025,
        'teams': [
            {'abbrev': 'CGK', 'name': 'Team Kaminska', 'owner': 'Connor Kaminska'},
            {'abbrev': 'CWR', 'name': 'Team Reardon', 'owner': 'Connor Reardon'},
        ],
        'schedule': [
            {'week': 5, 'is_rivalry': True, 'matchups': [{'team1': 'CGK', 'team2': 'CWR'}]},
            {'week': 12, 'is_rivalry': False, 'matchups': [{'team1': 'CGK', 'team2': 'CWR'}]},
        ],
    }
    second = _week()
    second['week'] = 12
    second['matchups'][0]['team1']['total_score'] = 30
    second['matchups'][0]['team2']['total_score'] = 10
    lore = build_league_lore(
        [{'season': 2025, 'meta': meta, 'standings': [], 'weeks': [_week(), second]}],
        _config(),
    )

    rivalry = lore['rivalries'][0]
    assert rivalry['record']['games'] == 2
    assert rivalry['official_record']['games'] == 1
    assert rivalry['current_holder'] == 'CGK'
    assert rivalry['current_streak'] == {'team': 'CGK', 'count': 1}
    assert rivalry['next_meeting'] is None


def test_closed_ballot_results_are_preserved_in_the_yearbook():
    config = _config()
    config['superlative_ballots'] = [
        {
            'season': 2025,
            'status': 'closed',
            'categories': [
                {
                    'id': 'funniest_moment',
                    'name': 'Funniest Moment',
                    'nominees': [
                        {'id': 'chat', 'label': 'The chat screenshot'},
                        {'id': 'bench', 'label': 'The bench disaster'},
                    ],
                    'votes': {'GSA': 'chat', 'CGK': 'chat', 'CWR': 'bench'},
                }
            ],
        }
    ]
    lore = build_league_lore(
        [{'season': 2025, 'meta': {'season': 2025}, 'standings': [], 'weeks': []}],
        config,
    )

    assert lore['yearbooks'][0]['superlatives']['winners'] == [
        {
            'category': 'Funniest Moment',
            'winner': 'The chat screenshot',
            'citation': '2 league votes',
        }
    ]


def test_real_lore_export_is_complete_and_repeatable():
    source_web = PROJECT_ROOT / 'web' / 'data'
    source_data = PROJECT_ROOT / 'data' / 'league_lore.json'

    # Use the tracked generated file as a smoke test for the complete historical archive.
    tracked = json.loads((source_web / 'shared' / 'lore.json').read_text())
    assert len(tracked['chronicles']['2025']) == 17
    assert tracked['rivalries'][0]['meetings']
    rivalry_books = {item['id']: item for item in tracked['rivalries']}
    assert rivalry_books['bollywood_bowl']['record']['games'] == 4
    assert rivalry_books['expansion_series']['record']['games'] == 8
    assert all('the The Expansion Series' not in item['title'] for item in tracked['timeline'])
    assert next(item for item in tracked['yearbooks'] if item['season'] == 2025)['champion']
    assert tracked['latest_chronicles'][0]['headline']

    # The source curation file remains schema-shaped and independent of generated prose.
    config = json.loads(source_data.read_text())
    assert {item['id'] for item in config['rivalries']} == {
        'connor_bowl',
        'brother_bowl',
        'kuhl_cup',
        'bollywood_bowl',
        'expansion_series',
    }


def test_export_league_lore_writes_shared_resource(tmp_path):
    data_dir = tmp_path / 'data'
    web_dir = tmp_path / 'web'
    season_dir = web_dir / 'data' / 'seasons' / '2025'
    (season_dir / 'weeks').mkdir(parents=True)
    data_dir.mkdir()
    (data_dir / 'league_lore.json').write_text(json.dumps(_config()))
    (season_dir / 'meta.json').write_text(
        json.dumps(
            {
                'season': 2025,
                'teams': [],
                'schedule': [{'week': 5, 'is_rivalry': True}],
            }
        )
    )
    (season_dir / 'standings.json').write_text('[]')
    (season_dir / 'weeks' / 'week_5.json').write_text(json.dumps(_week()))

    result = export_league_lore(data_dir, web_dir)

    output = web_dir / 'data' / 'shared' / 'lore.json'
    assert output.is_file()
    assert result['chronicles']['2025']['5']['headline'] == 'Team Reardon claims the Connor Bowl'
