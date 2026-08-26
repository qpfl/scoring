import base64
import json

import pytest

from api.github_content import GitHubContentError, fetch_json_file


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def encoded_payload(content):
    return {
        'encoding': 'base64',
        'content': base64.b64encode(json.dumps(content).encode()).decode(),
    }


def test_fetch_json_file_decodes_inline_contents():
    metadata = {'sha': 'inline-sha', **encoded_payload({'week': 1})}

    returned_metadata, content = fetch_json_file(
        'https://api.github.test/contents/data.json',
        {},
        opener=lambda _request: FakeResponse(metadata),
    )

    assert returned_metadata == metadata
    assert content == {'week': 1}


def test_fetch_json_file_follows_blob_for_files_over_one_megabyte():
    metadata = {
        'sha': 'large-sha',
        'encoding': 'none',
        'content': '',
        'git_url': 'https://api.github.test/git/blobs/large-sha',
    }
    responses = iter([metadata, encoded_payload({'season': 2026, 'lineup_week': 1})])
    urls = []

    def opener(request):
        urls.append(request.full_url)
        return FakeResponse(next(responses))

    returned_metadata, content = fetch_json_file(
        'https://api.github.test/contents/web/data.json', {}, opener=opener
    )

    assert returned_metadata == metadata
    assert content == {'season': 2026, 'lineup_week': 1}
    assert urls == [
        'https://api.github.test/contents/web/data.json',
        'https://api.github.test/git/blobs/large-sha',
    ]


def test_large_file_without_blob_reference_is_rejected():
    metadata = {'sha': 'large-sha', 'encoding': 'none', 'content': ''}

    with pytest.raises(GitHubContentError, match='blob URL'):
        fetch_json_file(
            'https://api.github.test/contents/web/data.json',
            {},
            opener=lambda _request: FakeResponse(metadata),
        )
