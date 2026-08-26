"""Atomic multi-file JSON updates using the GitHub Git Data API."""

from __future__ import annotations

import base64
import copy
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError

from api.github_content import decode_json_payload


class StoreError(RuntimeError):
    pass


class RefConflictError(StoreError):
    pass


class _MutationAbortedError(Exception):
    def __init__(self, error: Exception):
        self.error = error


def _settings() -> tuple[str, str, str, dict[str, str]]:
    owner = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
    repo = os.environ.get('GITHUB_REPO', 'scoring')
    branch = os.environ.get('GITHUB_BRANCH', 'main')
    token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
    if not token:
        raise StoreError('GitHub credentials are not configured')
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Atomic-Store',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    return owner, repo, branch, headers


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    owner, repo, _branch, headers = _settings()
    url = f'https://api.github.com/repos/{owner}/{repo}{path}'
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:
        body = response.read()
    return json.loads(body.decode()) if body else {}


def _get_head() -> str:
    _owner, _repo, branch, _headers = _settings()
    encoded_branch = urllib.parse.quote(branch, safe='')
    return _request('GET', f'/git/ref/heads/{encoded_branch}')['object']['sha']


def _read_json_at(path: str, commit_sha: str, default: Any) -> Any:
    encoded_path = urllib.parse.quote(path, safe='/')
    try:
        result = _request('GET', f'/contents/{encoded_path}?ref={commit_sha}')
    except HTTPError as error:
        if error.code == 404:
            return copy.deepcopy(default)
        raise
    try:
        payload = result
        if result.get('encoding') == 'none':
            blob_sha = result.get('sha')
            if not isinstance(blob_sha, str) or not blob_sha:
                raise StoreError(f'{path} is missing its Git blob reference')
            payload = _request('GET', f'/git/blobs/{blob_sha}')
        return decode_json_payload(payload)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise StoreError(f'{path} contains malformed JSON') from error


def _create_blob(content: Any) -> str:
    encoded = base64.b64encode(json.dumps(content, separators=(',', ':')).encode()).decode()
    return _request('POST', '/git/blobs', {'content': encoded, 'encoding': 'base64'})['sha']


def _create_tree(head_sha: str, blobs: dict[str, str]) -> str:
    tree = [
        {'path': path, 'mode': '100644', 'type': 'blob', 'sha': sha} for path, sha in blobs.items()
    ]
    return _request('POST', '/git/trees', {'base_tree': head_sha, 'tree': tree})['sha']


def _create_commit(message: str, tree_sha: str, head_sha: str) -> str:
    return _request(
        'POST',
        '/git/commits',
        {'message': message, 'tree': tree_sha, 'parents': [head_sha]},
    )['sha']


def _update_ref(commit_sha: str) -> None:
    _owner, _repo, branch, _headers = _settings()
    encoded_branch = urllib.parse.quote(branch, safe='')
    try:
        _request(
            'PATCH',
            f'/git/refs/heads/{encoded_branch}',
            {'sha': commit_sha, 'force': False},
        )
    except HTTPError as error:
        if error.code in (409, 422):
            raise RefConflictError('branch changed during atomic update') from error
        raise


def _contains_operation_id(value: Any, operation_id: str) -> bool:
    if isinstance(value, dict):
        if value.get('operation_id') == operation_id:
            return True
        return any(_contains_operation_id(item, operation_id) for item in value.values())
    if isinstance(value, list):
        return any(_contains_operation_id(item, operation_id) for item in value)
    return False


def update_json_bundle(
    paths_with_defaults: dict[str, Any],
    mutate_fn: Callable[[dict[str, Any]], tuple[dict[str, Any], Any]],
    commit_message: str,
    operation_id: str,
    max_retries: int = 5,
) -> tuple[bool, Any]:
    """Compare-and-swap several JSON paths through one branch-head commit."""
    last_extra = None
    for _attempt in range(max_retries):
        try:
            head = _get_head()
            snapshot = {
                path: _read_json_at(path, head, default)
                for path, default in paths_with_defaults.items()
            }
            if _contains_operation_id(snapshot, operation_id):
                return True, last_extra
            before = copy.deepcopy(snapshot)
            try:
                updated, extra = mutate_fn(copy.deepcopy(snapshot))
            except Exception as error:
                raise _MutationAbortedError(error) from error
            last_extra = extra
            if set(updated) != set(paths_with_defaults):
                raise StoreError('bundle mutation returned an unexpected path set')
            changed = {
                path: content for path, content in updated.items() if content != before[path]
            }
            if not changed:
                return True, extra
            blobs = {path: _create_blob(content) for path, content in changed.items()}
            tree = _create_tree(head, blobs)
            commit = _create_commit(commit_message, tree, head)
            try:
                _update_ref(commit)
            except RefConflictError:
                continue
            except Exception:
                try:
                    verification_head = _get_head()
                    verification = {
                        path: _read_json_at(path, verification_head, default)
                        for path, default in paths_with_defaults.items()
                    }
                except Exception:
                    return False, 'Could not verify an ambiguous atomic update'
                if _contains_operation_id(verification, operation_id):
                    return True, extra
                return False, 'Atomic update outcome was ambiguous'
            return True, extra
        except RefConflictError:
            continue
        except _MutationAbortedError as aborted:
            raise aborted.error from aborted
        except HTTPError as error:
            return False, f'GitHub API rejected atomic update ({error.code})'
        except StoreError as error:
            return False, str(error)
        except Exception:
            return False, 'Atomic GitHub update failed'
    return False, f'Atomic update conflicted after {max_retries} attempts'
