import importlib.util
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_PATH = PROJECT_ROOT / 'api' / 'nfl-draft.py'


def load_api_module():
    spec = importlib.util.spec_from_file_location('qpfl_api_nfl_draft_config', API_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nfl_draft = load_api_module()


def challenge_config(**overrides):
    config = {
        'year': 2030,
        'enabled': True,
        'title': '2030 NFL Draft',
        'lock_time': '2099-04-25T00:00:00Z',
        'pick_count': 4,
        'max_player_name_length': 80,
        'scoring': {
            'graduated_through_pick': 2,
            'flat_points_after': 7,
        },
        'prospect_source': 'Test board',
        'prospects': ['Player One', 'Player Two'],
    }
    config.update(overrides)
    return config


def test_checked_in_2026_challenge_is_annual_and_enabled():
    challenge_dir = PROJECT_ROOT / 'data' / 'nfl_draft_challenges'
    config = json.loads((challenge_dir / '2026_config.json').read_text())
    state = json.loads((challenge_dir / '2026.json').read_text())

    assert config['year'] == state['year'] == 2026
    assert config['enabled'] is True
    assert config['title'] == '2026 NFL Draft'
    assert config['lock_time'] == '2026-04-24T00:00:00Z'
    assert len(config['prospects']) == 250
    assert 'lock_time' not in state


def test_scoring_and_payload_limits_come_from_annual_config():
    config = challenge_config()
    actual = [{'pick': 1, 'player': 'Player One'}, {'pick': 3, 'player': 'Player Two'}]
    entries = {
        'GSA': {'picks': [{'pick': 1, 'player': 'Player One'}, {'pick': 3, 'player': 'Player Two'}]}
    }

    assert nfl_draft.compute_scores(actual, entries, config)['GSA'] == {
        'points': 8,
        'correct': 2,
    }
    assert nfl_draft.compute_max_points(config) == 17

    cleaned, error = nfl_draft.validate_picks_payload([{'pick': 5, 'player': 'Too Late'}], config)
    assert cleaned is None
    assert error == 'pick must be between 1 and 4'


def test_state_response_exposes_the_selected_year_configuration():
    config = challenge_config()
    state = {'year': 2030, 'actual_picks': [], 'picks_by_team': {}, 'updated_at': None}

    response = nfl_draft.build_state_response(state, config, None)

    assert response['year'] == 2030
    assert response['title'] == '2030 NFL Draft'
    assert response['lock_time'] == config['lock_time']
    assert response['pick_count'] == 4
    assert response['prospects'] == ['Player One', 'Player Two']
    assert response['max_points'] == 17


def test_missing_request_year_uses_league_configuration(monkeypatch):
    monkeypatch.setattr(
        nfl_draft,
        'fetch_repo_json',
        lambda path, _token: (
            ({'current_season': 2031}, 'sha')
            if path == nfl_draft.LEAGUE_CONFIG_PATH
            else (None, None)
        ),
    )

    assert nfl_draft.resolve_challenge_year(None, 'token') == 2031


def test_disabled_template_cannot_be_opened():
    config = challenge_config(enabled=False, lock_time=None)

    try:
        nfl_draft.validate_challenge_config(config, 2030)
    except ValueError as error:
        assert str(error) == '2030 Draft Challenge is not enabled'
    else:
        raise AssertionError('Disabled Draft Challenge config should not validate for API use')


def test_api_has_no_season_specific_challenge_defaults():
    source = API_PATH.read_text(encoding='utf-8')

    assert '2026 NFL Draft' not in source
    assert '2026-04-24T00:00:00Z' not in source
    assert 'DEFAULT_LOCK_TIME' not in source
    assert 'CHALLENGE_FILE_PATH' not in source
    assert "f'{CHALLENGE_DIR}/{year}_config.json'" in source
    assert "f'{CHALLENGE_DIR}/{year}.json'" in source
