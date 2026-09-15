"""Shared stdlib-only HTTP helpers for GitHub API calls from Vercel functions.

Vercel functions can't import ``qpfl`` (not bundled), so this module is
intentionally self-contained, like ``api/github_content.py`` and
``api/github_store.py``.
"""

from __future__ import annotations

import random
import time
import urllib.request
from collections.abc import Callable
from urllib.error import HTTPError

#: Bounded so a hung GitHub connection can't outlive the calling Vercel
#: function and leave the caller with no idea whether a write landed.
GITHUB_TIMEOUT = 8.0

#: Transient failures worth retrying: rate limiting and server-side errors.
#: A real conflict (409/422) is the caller's own compare-and-swap retry to
#: handle, not this module's; other 4xx codes are not retried.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def open_github(request: urllib.request.Request, timeout: float = GITHUB_TIMEOUT):
    """``urlopen`` with a bounded default timeout."""
    return urllib.request.urlopen(request, timeout=timeout)


def is_retryable_http_error(error: HTTPError) -> bool:
    """Whether ``error`` is a transient GitHub failure worth retrying."""
    return error.code in RETRYABLE_STATUS_CODES


def retry_delay_seconds(
    error: HTTPError, attempt: int, *, base: float = 0.5, cap: float = 8.0
) -> float:
    """Jittered exponential backoff, honoring ``Retry-After`` when GitHub sends one."""
    headers = getattr(error, 'headers', None)
    retry_after = headers.get('Retry-After') if headers else None
    if retry_after:
        try:
            return min(float(retry_after), cap)
        except (TypeError, ValueError):
            pass
    return min(cap, base * (2**attempt)) * random.uniform(0.5, 1.0)


def open_github_with_retry(
    request: urllib.request.Request,
    *,
    max_retries: int = 4,
    timeout: float = GITHUB_TIMEOUT,
    opener: Callable = open_github,
    sleep: Callable[[float], None] = time.sleep,
):
    """Open ``request``, retrying transient GitHub failures (429/5xx) with
    jittered backoff. A real conflict (409/422) or other 4xx is raised
    immediately for the caller's own compare-and-swap retry to handle.
    """
    for attempt in range(max_retries):
        try:
            return opener(request, timeout=timeout)
        except HTTPError as error:
            if not is_retryable_http_error(error) or attempt == max_retries - 1:
                raise
            sleep(retry_delay_seconds(error, attempt))
    raise AssertionError('unreachable')  # pragma: no cover
