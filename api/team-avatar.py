"""Vercel Serverless Function for team avatar (logo) uploads.

Mirrors team-name.py: authenticates a manager by team password, then commits the
uploaded image into the repo at web/images/avatars/{slug}.png via the GitHub
Contents API. Vercel redeploys from the repo, so the new avatar is served at
/images/avatars/{slug}.png on the next deploy.

The frontend resizes/crops the image to a small square PNG client-side before
upload, so the committed files stay tiny.
"""

import base64
import json
import os
import re
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

# GitHub repo info
GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')

# Cap the committed image size. The client resizes to 256x256 PNG (tens of KB),
# so this is a generous ceiling that still rejects abuse.
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB decoded
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def get_team_password(team_abbrev: str) -> str | None:
    """Get the password for a team from environment variables."""
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


def avatar_slug(team_abbrev: str) -> str:
    """Filesystem-safe slug for a team abbrev (e.g. "S/T" -> "S_T").

    Must stay in sync with avatarSlug() in web/app.js so the committed filename
    matches the <img src> the frontend requests.
    """
    return re.sub(r'[^A-Za-z0-9]', '_', team_abbrev)


def avatar_rel_path(team: str, season: int, week: int) -> str:
    """Versioned avatar path relative to web/images/avatars/.

    Avatars are versioned per (season, week) so a new upload applies from its week
    forward without overwriting earlier weeks. Must match the ``file`` field that
    qpfl/avatars.py resolves and stamps onto team objects at export.
    """
    return f'{avatar_slug(team)}/{season}-w{week}.png'


def _github_headers(github_token: str) -> dict:
    return {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Avatar-Bot',
    }


def _get_file_sha(api_url: str, headers: dict) -> tuple[str | None, str | None]:
    """Return (sha, raw_text) for an existing repo file, or (None, None) if absent.

    Raises nothing for 404; returns an error string in the second slot only on
    unexpected HTTP failures (signalled by a non-None error via the caller check).
    """
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            current = json.loads(response.read().decode())
            content = base64.b64decode(current['content']).decode() if current.get('content') else None
            return current['sha'], content
    except HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def _put_file(
    file_path: str, content_b64: str, message: str, sha: str | None, headers: dict
) -> tuple[bool, str]:
    """Create or update a repo file via the GitHub Contents API."""
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}'
    update_data = {'message': message, 'content': content_b64, 'branch': GITHUB_BRANCH}
    if sha:
        update_data['sha'] = sha
    try:
        req = urllib.request.Request(
            api_url, data=json.dumps(update_data).encode(), headers=headers, method='PUT'
        )
        with urllib.request.urlopen(req) as response:
            if response.status in (200, 201):
                return True, 'ok'
            return False, f'GitHub API returned status {response.status}'
    except HTTPError as e:
        error_body = e.read().decode() if hasattr(e, 'read') else str(e)
        return False, f'GitHub API error: {error_body}'


def update_avatar_manifest(
    team: str, rel_path: str, season: int, week: int, github_token: str
) -> tuple[bool, str]:
    """Record this version in data/avatars.json so the exporter can resolve the
    point-in-time avatar for each week. Replaces any existing entry for the same
    (team, season, week)."""
    file_path = 'data/avatars.json'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}'
    headers = _github_headers(github_token)

    try:
        sha, raw = _get_file_sha(api_url, headers)
    except HTTPError as e:
        return False, f'Failed to read avatar manifest: {e}'

    try:
        manifest = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}

    versions = manifest.get(team)
    if not isinstance(versions, list):
        versions = []
    # Drop any prior entry for this exact week, then append the new one.
    versions = [
        v for v in versions
        if not (isinstance(v, dict) and v.get('season') == season and v.get('week') == week)
    ]
    versions.append({'season': season, 'week': week, 'file': rel_path})
    versions.sort(key=lambda v: (v.get('season', 0), v.get('week', 0)))
    manifest[team] = versions

    content_b64 = base64.b64encode(
        (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    ).decode()
    return _put_file(
        file_path, content_b64, f'Record avatar version for {team} ({season} w{week})',
        sha, headers,
    )


def upload_avatar_file(
    team: str, png_b64: str, season: int, week: int, github_token: str
) -> tuple[bool, str]:
    """Commit the versioned avatar PNG and update the manifest via the Contents API."""
    rel_path = avatar_rel_path(team, season, week)
    file_path = f'web/images/avatars/{rel_path}'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}'
    headers = _github_headers(github_token)

    # Same-week re-upload overwrites in place (needs the current SHA); a new week
    # is a fresh file.
    try:
        sha, _ = _get_file_sha(api_url, headers)
    except HTTPError as e:
        return False, f'Failed to check existing avatar: {e}'

    ok, msg = _put_file(
        file_path, png_b64, f'Update team avatar for {team} ({season} w{week})', sha, headers
    )
    if not ok:
        return False, f'Failed to upload avatar: {msg}'

    ok, msg = update_avatar_manifest(team, rel_path, season, week, github_token)
    if not ok:
        return False, f'Avatar uploaded but manifest update failed: {msg}'
    return True, 'Avatar updated successfully'


def _decode_image(image_data: str) -> tuple[bytes | None, str | None]:
    """Strip an optional data-URL prefix and base64-decode, validating PNG."""
    if not image_data:
        return None, 'Missing image data'

    # Accept "data:image/png;base64,...." or a bare base64 string.
    if image_data.startswith('data:'):
        if 'image/png' not in image_data.split(',', 1)[0]:
            return None, 'Image must be a PNG'
        image_data = image_data.split(',', 1)[1]

    try:
        raw = base64.b64decode(image_data, validate=True)
    except Exception:
        return None, 'Invalid base64 image data'

    if len(raw) > MAX_IMAGE_BYTES:
        return None, 'Image is too large'
    if not raw.startswith(PNG_MAGIC):
        return None, 'Image must be a PNG'

    return raw, None


def _effective_point(season, week) -> tuple[int | None, int]:
    """Normalize the (season, week) an upload takes effect from.

    The frontend sends the live ``season`` and ``current_week``; the new avatar
    applies from that week forward (current week inclusive). Week defaults to 0
    (offseason / preseason) when absent or unparseable, which makes the avatar the
    season's baseline. Returns (None, 0) for an invalid season so the caller rejects.
    """
    try:
        season_i = int(season)
    except (TypeError, ValueError):
        return None, 0
    if season_i <= 0:
        return None, 0
    try:
        week_i = int(week)
    except (TypeError, ValueError):
        week_i = 0
    return season_i, max(week_i, 0)


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        """Handle CORS preflight - no auth needed."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '86400')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests - just for testing."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(
            json.dumps({'status': 'Team Avatar API is running', 'method': 'GET'}).encode()
        )

    def do_POST(self):
        """Handle avatar upload."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}

            team = data.get('team')
            password = data.get('password')
            image_data = data.get('imageData')
            season, week = _effective_point(data.get('season'), data.get('week'))

            if not team or not password:
                return self._send_json(400, {'error': 'Missing team or password'})

            if season is None:
                return self._send_json(400, {'error': 'Missing or invalid season'})

            raw, err = _decode_image(image_data)
            if err:
                return self._send_json(400, {'error': err})

            expected_password = get_team_password(team)
            if not expected_password:
                return self._send_json(500, {'error': 'Team not configured'})

            if password != expected_password:
                return self._send_json(401, {'error': 'Invalid password'})

            github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
            if not github_token:
                return self._send_json(500, {'error': 'Server configuration error'})

            # Re-encode the validated bytes so we commit exactly what we verified.
            png_b64 = base64.b64encode(raw).decode()
            success, message = upload_avatar_file(team, png_b64, season, week, github_token)

            if success:
                return self._send_json(
                    200, {'success': True, 'message': message, 'slug': avatar_slug(team)}
                )
            return self._send_json(500, {'error': message})

        except json.JSONDecodeError:
            return self._send_json(400, {'error': 'Invalid JSON'})
        except Exception as e:  # noqa: BLE001
            return self._send_json(500, {'error': str(e)})

    def _send_json(self, status_code: int, data: dict):
        """Send JSON response with CORS headers."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
