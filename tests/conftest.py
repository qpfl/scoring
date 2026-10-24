import copy

import pytest


@pytest.fixture(autouse=True)
def _no_nflverse_retry_waits(monkeypatch):
    """Download retries wait up to minutes in production; tests fail fast."""
    monkeypatch.setattr('qpfl.data_fetcher.LOAD_RETRY_DELAYS_SECONDS', ())


@pytest.fixture(autouse=True)
def failed_login_store(monkeypatch):
    """Keep failed-login counts in memory instead of on the auth-state branch."""
    from api import auth_limit

    store = {'state': {}, 'sha': None, 'writes': 0}

    def load_state():
        return copy.deepcopy(store['state']), store['sha']

    def save_state(state, sha):
        store['state'] = copy.deepcopy(state)
        store['writes'] += 1
        store['sha'] = f'sha-{store["writes"]}'

    monkeypatch.setenv('AUTH_LIMIT_SECRET', 'test-secret')
    monkeypatch.setattr(auth_limit, '_load_state', load_state)
    monkeypatch.setattr(auth_limit, '_save_state', save_state)
    return store
