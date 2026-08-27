"""Current NFL injury designations for QPFL roster players."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SLEEPER_PLAYERS_URL = 'https://api.sleeper.app/v1/players/nfl'
CACHE_TTL = timedelta(hours=24)
SUPPORTED_POSITIONS = {'QB', 'RB', 'WR', 'TE', 'K'}

_SUFFIX_RE = re.compile(r'\s+(?:sr\.?|jr\.?|ii|iii|iv|v)$', re.IGNORECASE)
_TEAM_ALIASES = {
    'JAX': 'JAC',
    'LA': 'LAR',
    'WSH': 'WAS',
}
_STATUS_ABBREVIATIONS = {
    'questionable': 'Q',
    'doubtful': 'D',
    'out': 'O',
    'ir': 'IR',
    'injured reserve': 'IR',
    'pup': 'PUP',
    'physically unable to perform': 'PUP',
    'nfi': 'NFI',
    'non-football injury': 'NFI',
    'suspended': 'SUS',
    'covid-19': 'C19',
    'probable': 'P',
}
_EMPTY_STATUSES = {'', 'na', 'n/a', 'none', 'healthy'}


def normalize_player_name(value: str | None) -> str:
    """Normalize suffix and punctuation differences between roster sources."""
    name = str(value or '').replace('’', "'").strip().casefold()
    name = _SUFFIX_RE.sub('', name)
    return re.sub(r'[^a-z0-9]+', ' ', name).strip()


def normalize_team(value: str | None) -> str:
    team = str(value or '').strip().upper()
    return _TEAM_ALIASES.get(team, team)


def injury_identity_key(name: str | None, position: str | None) -> str:
    return f'{str(position or "").strip().upper()}|{normalize_player_name(name)}'


def _iter_roster_players(rosters: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(rosters, Mapping):
        return
    for roster in rosters.values():
        if isinstance(roster, list):
            players = roster
        elif isinstance(roster, Mapping):
            players = [*(roster.get('roster') or []), *(roster.get('taxi_squad') or [])]
        else:
            continue
        for player in players:
            if isinstance(player, Mapping):
                yield player


def _target_players(rosters: Any) -> list[dict[str, str]]:
    targets: dict[str, dict[str, str]] = {}
    for player in _iter_roster_players(rosters):
        name = str(player.get('name') or '').strip()
        position = str(player.get('position') or '').strip().upper()
        if not name or position not in SUPPORTED_POSITIONS:
            continue
        key = injury_identity_key(name, position)
        targets[key] = {
            'name': name,
            'position': position,
            'team': normalize_team(player.get('nfl_team')),
        }
    return [targets[key] for key in sorted(targets)]


def _target_fingerprint(targets: list[dict[str, str]]) -> str:
    encoded = json.dumps(targets, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _status_details(player: Mapping[str, Any]) -> tuple[str, str] | None:
    injury_status = str(player.get('injury_status') or '').strip()
    normalized_status = injury_status.casefold()
    if normalized_status in _EMPTY_STATUSES:
        roster_status = str(player.get('status') or '').strip()
        normalized_roster_status = roster_status.casefold()
        if normalized_roster_status not in _STATUS_ABBREVIATIONS:
            return None
        injury_status = roster_status
        normalized_status = normalized_roster_status

    abbreviation = _STATUS_ABBREVIATIONS.get(normalized_status)
    if not abbreviation:
        abbreviation = (
            injury_status.upper() if len(injury_status) <= 4 else injury_status[:3].upper()
        )
    return injury_status, abbreviation


def match_injuries(
    targets: list[dict[str, str]], sleeper_players: Mapping[str, Any]
) -> dict[str, dict[str, str]]:
    """Match current QPFL players to Sleeper by normalized name, position, and team."""
    by_identity: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for player in sleeper_players.values():
        if not isinstance(player, Mapping):
            continue
        position = str(player.get('position') or '').strip().upper()
        name = player.get('full_name') or ' '.join(
            part for part in (player.get('first_name'), player.get('last_name')) if part
        )
        normalized_name = normalize_player_name(str(name))
        if position in SUPPORTED_POSITIONS and normalized_name:
            by_identity[(normalized_name, position)].append(player)

    injuries: dict[str, dict[str, str]] = {}
    for target in targets:
        candidates = by_identity.get(
            (normalize_player_name(target['name']), target['position']), []
        )
        same_team = [
            player for player in candidates if normalize_team(player.get('team')) == target['team']
        ]
        if len(same_team) == 1:
            match = same_team[0]
        elif len(candidates) == 1:
            match = candidates[0]
        else:
            continue

        details = _status_details(match)
        if not details:
            continue
        status, abbreviation = details
        entry = {
            'status': status,
            'abbreviation': abbreviation,
        }
        body_part = str(match.get('injury_body_part') or '').strip()
        notes = str(match.get('injury_notes') or '').strip()
        if body_part:
            entry['body_part'] = body_part
        if notes:
            entry['notes'] = notes
        injuries[injury_identity_key(target['name'], target['position'])] = entry
    return injuries


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('players'), dict):
        return None
    return payload


def _public_payload(cache: Mapping[str, Any] | None) -> dict[str, Any]:
    if not cache:
        return {'source': 'Sleeper', 'updated_at': None, 'players': {}}
    return {
        'source': 'Sleeper',
        'updated_at': cache.get('updated_at'),
        'players': cache.get('players', {}),
    }


def _fetch_sleeper_players(opener: Callable[..., Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        SLEEPER_PLAYERS_URL,
        headers={
            'Accept': 'application/json',
            'User-Agent': 'QPFL-Scoring/1.0',
        },
    )
    with opener(request, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError('Sleeper player response must be a JSON object')
    return payload


def load_injury_statuses(
    rosters: Any,
    cache_path: Path,
    *,
    now: datetime | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return current injury badges, refreshing the compact cache at most daily.

    Sleeper asks consumers not to download its full NFL player map more than
    once per day. The committed compact cache lets every scoring run reuse the
    last download, and also preserves the last good data during a provider
    outage.
    """
    targets = _target_players(rosters)
    if not targets:
        return {'source': 'Sleeper', 'updated_at': None, 'players': {}}

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    fingerprint = _target_fingerprint(targets)
    cached = _read_cache(Path(cache_path))
    cached_at = _parse_timestamp(cached.get('updated_at')) if cached else None
    cache_age = current_time - cached_at if cached_at else None
    cache_is_fresh = cached is not None and cache_age is not None and cache_age < CACHE_TTL
    if cache_is_fresh:
        return _public_payload(cached)

    try:
        players = _fetch_sleeper_players(opener or urllib.request.urlopen)
        injuries = match_injuries(targets, players)
    except Exception as exc:
        print(f'  Could not refresh NFL injury statuses; using cached data: {exc}')
        return _public_payload(cached)

    refreshed = {
        'source': 'Sleeper',
        'updated_at': current_time.isoformat(),
        'target_fingerprint': fingerprint,
        'players': injuries,
    }
    path = Path(cache_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f'{path.suffix}.tmp')
        temporary_path.write_text(json.dumps(refreshed, separators=(',', ':')), encoding='utf-8')
        temporary_path.replace(path)
    except OSError as exc:
        print(f'  Could not save NFL injury cache: {exc}')
    return _public_payload(refreshed)
