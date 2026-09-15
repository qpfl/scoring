"""Tests for api/github_http.py - shared timeout/retry helpers for GitHub calls."""

from urllib.error import HTTPError

import pytest

from api import github_http


def _http_error(code, headers=None):
    return HTTPError('https://api.github.test/x', code, 'error', headers or {}, None)


class TestIsRetryableHttpError:
    @pytest.mark.parametrize('code', [429, 500, 502, 503, 504])
    def test_retryable_codes(self, code):
        assert github_http.is_retryable_http_error(_http_error(code)) is True

    @pytest.mark.parametrize('code', [400, 401, 403, 404, 409, 422])
    def test_non_retryable_codes(self, code):
        assert github_http.is_retryable_http_error(_http_error(code)) is False


class TestRetryDelaySeconds:
    def test_honors_retry_after_header(self):
        error = _http_error(429, headers={'Retry-After': '2'})
        assert github_http.retry_delay_seconds(error, attempt=0) == 2.0

    def test_caps_retry_after_header(self):
        error = _http_error(429, headers={'Retry-After': '9999'})
        assert github_http.retry_delay_seconds(error, attempt=0, cap=4.0) == 4.0

    def test_falls_back_to_jittered_backoff_without_header(self):
        error = _http_error(503)
        delay = github_http.retry_delay_seconds(error, attempt=2, base=0.5, cap=8.0)
        assert 0 < delay <= 8.0

    def test_ignores_malformed_retry_after_header(self):
        error = _http_error(429, headers={'Retry-After': 'not-a-number'})
        delay = github_http.retry_delay_seconds(error, attempt=0, base=0.5, cap=8.0)
        assert 0 < delay <= 8.0


class TestOpenGithubWithRetry:
    def test_succeeds_immediately_without_error(self):
        calls = []

        def opener(request, timeout):
            calls.append(timeout)
            return 'response'

        result = github_http.open_github_with_retry('req', opener=opener, sleep=lambda _s: None)

        assert result == 'response'
        assert calls == [github_http.GITHUB_TIMEOUT]

    def test_retries_transient_failure_then_succeeds(self):
        attempts = []
        sleeps = []

        def opener(_request, timeout):
            attempts.append(timeout)
            if len(attempts) < 3:
                raise _http_error(502)
            return 'response'

        result = github_http.open_github_with_retry(
            'req', opener=opener, sleep=sleeps.append, max_retries=5
        )

        assert result == 'response'
        assert len(attempts) == 3
        assert len(sleeps) == 2

    def test_non_retryable_error_raises_immediately(self):
        attempts = []

        def opener(_request, timeout):
            attempts.append(timeout)
            raise _http_error(404)

        with pytest.raises(HTTPError) as excinfo:
            github_http.open_github_with_retry('req', opener=opener, sleep=lambda _s: None)

        assert excinfo.value.code == 404
        assert len(attempts) == 1

    def test_exhausts_retries_and_raises_last_error(self):
        def opener(_request, timeout):
            raise _http_error(503)

        with pytest.raises(HTTPError) as excinfo:
            github_http.open_github_with_retry(
                'req', opener=opener, max_retries=3, sleep=lambda _s: None
            )

        assert excinfo.value.code == 503
