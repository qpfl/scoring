import pytest


@pytest.fixture(autouse=True)
def _no_nflverse_retry_waits(monkeypatch):
    """Download retries wait up to minutes in production; tests fail fast."""
    monkeypatch.setattr('qpfl.data_fetcher.LOAD_RETRY_DELAYS_SECONDS', ())
