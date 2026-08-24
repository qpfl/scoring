import copy
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_lore_api():
    spec = importlib.util.spec_from_file_location('qpfl_lore_api', PROJECT_ROOT / 'api' / 'lore.py')
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def ballot_file(status='open'):
    return {
        'rivalries': [],
        'moments': [],
        'season_notes': {},
        'superlative_ballots': [
            {
                'season': 2026,
                'status': status,
                'categories': [
                    {
                        'id': 'funniest_moment',
                        'name': 'Funniest Moment',
                        'description': '',
                        'nominees': [
                            {'id': 'group_chat', 'label': 'The group chat', 'detail': ''},
                            {'id': 'bench', 'label': 'The bench decision', 'detail': ''},
                        ],
                        'votes': {},
                    }
                ],
            }
        ],
        'superlatives': [],
    }


def install_memory_update(monkeypatch, module, content):
    state = {'content': content, 'messages': []}

    def update_lore(mutate, message, max_retries=5):
        try:
            updated, result = mutate(copy.deepcopy(state['content']))
        except module.LoreError as error:
            return False, error
        state['content'] = updated
        state['messages'].append(message)
        return True, result

    monkeypatch.setattr(module, 'update_lore', update_lore)
    return state


def vote_payload(nominee='group_chat'):
    return {
        'team': 'GSA',
        'password': 'correct-password',
        'season': 2026,
        'category': 'funniest_moment',
        'nominee': nominee,
    }


def test_vote_is_authenticated_recorded_and_removable(monkeypatch):
    module = load_lore_api()
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'correct-password')
    state = install_memory_update(monkeypatch, module, ballot_file())

    status, result = module.handle_superlative_vote(vote_payload())

    assert status == 200
    assert result == {
        'success': True,
        'category': 'funniest_moment',
        'nominee': 'group_chat',
    }
    votes = state['content']['superlative_ballots'][0]['categories'][0]['votes']
    assert votes == {'GSA': 'group_chat'}
    assert state['messages'] == ['2026 superlative vote by GSA: funniest_moment']

    status, result = module.handle_superlative_vote(vote_payload(None))

    assert status == 200
    assert result['nominee'] is None
    assert votes != state['content']['superlative_ballots'][0]['categories'][0]['votes']
    assert state['content']['superlative_ballots'][0]['categories'][0]['votes'] == {}


def test_vote_rejects_bad_password_unknown_nominee_and_closed_ballot(monkeypatch):
    module = load_lore_api()
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'correct-password')
    state = install_memory_update(monkeypatch, module, ballot_file())

    payload = vote_payload()
    payload['password'] = 'wrong-password'
    assert module.handle_superlative_vote(payload) == (401, {'error': 'Invalid password'})

    status, result = module.handle_superlative_vote(vote_payload('not_on_ballot'))
    assert status == 400
    assert result == {'error': 'Nominee is not on this ballot'}

    state['content']['superlative_ballots'][0]['status'] = 'closed'
    status, result = module.handle_superlative_vote(vote_payload())
    assert status == 409
    assert result == {'error': 'This superlative ballot is not open'}


def test_vote_validates_request_types_before_updating(monkeypatch):
    module = load_lore_api()
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'correct-password')
    state = install_memory_update(monkeypatch, module, ballot_file())

    payload = vote_payload()
    payload['season'] = True
    assert module.handle_superlative_vote(payload) == (
        400,
        {'error': 'A numeric season is required'},
    )

    payload = vote_payload()
    payload['nominee'] = 7
    assert module.handle_superlative_vote(payload) == (
        400,
        {'error': 'Nominee must be a string or null'},
    )
    assert state['messages'] == []
