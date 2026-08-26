"""Shared HTTP request boundaries for the Vercel API handlers."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

JSON_BODY_LIMIT = 64 * 1024
AVATAR_BODY_LIMIT = 3 * 1024 * 1024
BASE_ALLOWED_ORIGINS = {
    'https://qpfl-scoring.vercel.app',
    'https://qpfl.github.io',
}


class RequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def allowed_origins() -> set[str]:
    configured = {
        origin.strip()
        for origin in os.environ.get('QPFL_ALLOWED_PREVIEW_ORIGINS', '').split(',')
        if origin.strip()
    }
    return BASE_ALLOWED_ORIGINS | configured


def request_origin(handler) -> str | None:
    origin = handler.headers.get('Origin')
    if origin and origin not in allowed_origins():
        raise RequestError(403, 'Origin is not allowed')
    return origin


def read_json_body(handler, max_bytes: int = JSON_BODY_LIMIT) -> dict[str, Any]:
    request_origin(handler)
    content_type = handler.headers.get('Content-Type', '')
    if content_type.split(';', 1)[0].strip().lower() != 'application/json':
        raise RequestError(415, 'Content-Type must be application/json')
    raw_length = handler.headers.get('Content-Length')
    if raw_length is None:
        raise RequestError(411, 'Content-Length is required')
    try:
        content_length = int(raw_length)
    except (TypeError, ValueError) as error:
        raise RequestError(400, 'Invalid Content-Length') from error
    if content_length < 0:
        raise RequestError(400, 'Invalid Content-Length')
    if content_length > max_bytes:
        raise RequestError(413, 'Request body is too large')
    try:
        payload = json.loads(handler.rfile.read(content_length).decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RequestError(400, 'Invalid JSON') from error
    if not isinstance(payload, dict):
        raise RequestError(400, 'JSON body must be an object')
    return payload


def send_json(handler, status: int, data: dict[str, Any]) -> None:
    payload = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    origin = handler.headers.get('Origin')
    if origin in allowed_origins():
        handler.send_header('Access-Control-Allow-Origin', origin)
    handler.send_header('Vary', 'Origin')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Content-Length', str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def handle_options(handler) -> None:
    try:
        origin = request_origin(handler)
    except RequestError as error:
        send_json(handler, error.status, {'error': error.message})
        return
    handler.send_response(204)
    if origin:
        handler.send_header('Access-Control-Allow-Origin', origin)
    handler.send_header('Vary', 'Origin')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type')
    handler.send_header('Access-Control-Max-Age', '86400')
    handler.send_header('Content-Length', '0')
    handler.end_headers()


def request_id() -> str:
    return uuid.uuid4().hex[:12]
