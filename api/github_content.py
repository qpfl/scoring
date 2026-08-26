"""Decode JSON files returned by the GitHub Contents API."""

from __future__ import annotations

import base64
import json
import urllib.request
from collections.abc import Callable
from typing import Any


class GitHubContentError(ValueError):
    pass


def _response_json(request, opener: Callable) -> dict[str, Any]:
    with opener(request) as response:
        payload = json.loads(response.read().decode())
    if not isinstance(payload, dict):
        raise GitHubContentError('GitHub returned malformed content metadata')
    return payload


def _decode_base64_json(payload: dict[str, Any]) -> Any:
    content = payload.get('content')
    encoding = payload.get('encoding')
    if encoding not in (None, 'base64') or not isinstance(content, str) or not content:
        raise GitHubContentError('GitHub did not return decodable file content')
    try:
        return json.loads(base64.b64decode(content).decode())
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise GitHubContentError('GitHub file does not contain valid JSON') from error


def fetch_json_file(
    api_url: str,
    headers: dict[str, str],
    *,
    opener: Callable = urllib.request.urlopen,
) -> tuple[dict[str, Any], Any]:
    """Return Contents API metadata and decoded JSON, including files over 1 MiB."""
    request = urllib.request.Request(api_url, headers=headers)
    metadata = _response_json(request, opener)
    payload = metadata
    if metadata.get('encoding') == 'none':
        git_url = metadata.get('git_url')
        if not isinstance(git_url, str) or not git_url:
            raise GitHubContentError('GitHub omitted the large file blob URL')
        payload = _response_json(urllib.request.Request(git_url, headers=headers), opener)
    return metadata, _decode_base64_json(payload)


def decode_json_payload(payload: dict[str, Any]) -> Any:
    """Decode a base64 JSON response from GitHub's Git Blobs API."""
    return _decode_base64_json(payload)
