"""Point-in-time team avatar resolution.

Team avatars (logos) are versioned: each upload is committed to its own file and
recorded in ``data/avatars.json`` against the ``(season, week)`` that was current
when the manager uploaded it. A new avatar takes effect for that week *and every
week after* — completed weeks keep whatever avatar was current then, so the
historical view never shifts retroactively.

This mirrors ``qpfl/name_battles.py``, which stamps point-in-time owner *names*.
Here we resolve, for any ``(season, week)``, the filename of the avatar in effect.
The module is pure (only ``load_manifest`` touches disk); callers pass the loaded
manifest so it stays trivially testable.

Manifest shape (``data/avatars.json``)::

    { "<abbrev>": [ {"season": 2026, "week": 3, "file": "GSA/2026-w3.png"} ] }

The stable identifier is always the team ``abbrev``. ``file`` is stored relative to
``web/images/avatars/``; resolvers return a web-root-relative URL such as
``images/avatars/GSA/2026-w3.png``.
"""

from __future__ import annotations

import json
from pathlib import Path

# Web-root-relative directory the frontend serves avatars from.
AVATAR_URL_PREFIX = 'images/avatars'

# A non-int week (e.g. "Offseason") sorts after every real week within its season,
# so an offseason upload applies to that whole offseason and forward.
_OFFSEASON_WEEK = 1_000_000


def _week_key(week) -> int:
    """Sortable week number; non-int weeks (offseason) sort last within a season."""
    return week if isinstance(week, int) else _OFFSEASON_WEEK


def load_manifest(path: str | Path) -> dict[str, list[dict]]:
    """Load ``data/avatars.json``. Returns ``{}`` when the file is absent."""
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text())
    # Tolerate either a bare mapping or a wrapper {"avatars": {...}}.
    return raw.get('avatars', raw) if isinstance(raw, dict) else {}


def _to_url(file: str | None) -> str | None:
    return f'{AVATAR_URL_PREFIX}/{file}' if file else None


def avatar_at(
    manifest: dict[str, list[dict]], abbrev: str, season: int, week
) -> str | None:
    """Web URL of the avatar in effect for ``abbrev`` as of ``(season, week)``.

    Returns the newest version whose ``(season, week)`` is at or before the target
    (current week inclusive), or ``None`` when the team has no avatar yet at that
    point. ``week`` may be a non-int (offseason), which sorts after that season's
    real weeks.
    """
    versions = manifest.get(abbrev)
    if not versions:
        return None
    target = (season, _week_key(week))
    best: tuple[int, int] | None = None
    best_file: str | None = None
    for v in versions:
        key = (v.get('season', 0), _week_key(v.get('week')))
        if key <= target and (best is None or key > best):
            best = key
            best_file = v.get('file')
    return _to_url(best_file)


def current_avatar(manifest: dict[str, list[dict]], abbrev: str) -> str | None:
    """Web URL of the latest avatar for ``abbrev`` (used by current-state surfaces)."""
    versions = manifest.get(abbrev)
    if not versions:
        return None
    latest = max(versions, key=lambda v: (v.get('season', 0), _week_key(v.get('week'))))
    return _to_url(latest.get('file'))
