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


def upload_avatar_file(
    team: str, png_b64: str, github_token: str
) -> tuple[bool, str]:
    """Commit the avatar PNG into the repo via the GitHub Contents API."""
    file_path = f'web/images/avatars/{avatar_slug(team)}.png'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}'

    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Avatar-Bot',
    }

    # An update needs the current file SHA; a first upload does not.
    current_sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            current_data = json.loads(response.read().decode())
            current_sha = current_data['sha']
    except HTTPError as e:
        if e.code != 404:
            return False, f'Failed to check existing avatar: {e}'

    update_data = {
        'message': f"Update team avatar for {team}",
        'content': png_b64,
        'branch': GITHUB_BRANCH,
    }
    if current_sha:
        update_data['sha'] = current_sha

    try:
        req = urllib.request.Request(
            api_url, data=json.dumps(update_data).encode(), headers=headers, method='PUT'
        )
        with urllib.request.urlopen(req) as response:
            if response.status in (200, 201):
                return True, 'Avatar updated successfully'
            return False, f'GitHub API returned status {response.status}'
    except HTTPError as e:
        error_body = e.read().decode() if hasattr(e, 'read') else str(e)
        return False, f'Failed to upload avatar: {error_body}'


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

            if not team or not password:
                return self._send_json(400, {'error': 'Missing team or password'})

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
            success, message = upload_avatar_file(team, png_b64, github_token)

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
