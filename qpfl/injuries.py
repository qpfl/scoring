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

ESPN_INJURIES_URL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries'
SOURCE = 'ESPN'
# The whole league is one small request, so refresh often enough for scoring
# runs to pick up Wednesday-Friday practice reports and game-day decisions.
CACHE_TTL = timedelta(hours=3)
SUPPORTED_POSITIONS = {'QB', 'RB', 'WR', 'TE', 'K'}

_SUFFIX_RE = re.compile(r'\s+(?:sr\.?|jr\.?|ii|iii|iv|v)$', re.IGNORECASE)
_TEAM_ALIASES = {
    'JAX': 'JAC',
    'LA': 'LAR',
    'WSH': 'WAS',
}
_POSITION_ALIASES = {'PK': 'K'}
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
# ESPN's ``status`` is the last official designation, so a player ruled out of
# last week's game still reads "Out" until his team files its next report. Its
# ``fantasyStatus`` is the forward-looking call for the team's next game, which
# is what a manager setting a lineup cares about.
_FANTASY_STATUSES = {
    'OUT': ('Out', 'O'),
    'DOUBTFUL': ('Doubtful', 'D'),
    'QUESTIONABLE': ('Questionable', 'Q'),
    'IR': ('Injured Reserve', 'IR'),
    'IR-R': ('Injured Reserve', 'IR'),
    'PUP': ('PUP', 'PUP'),
    'PUP-R': ('PUP', 'PUP'),
    'NFI': ('NFI', 'NFI'),
    'NFI-R': ('NFI', 'NFI'),
    'SUSPENSION': ('Suspended', 'SUS'),
    'SUSPENDED': ('Suspended', 'SUS'),
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


def _return_is_after_next_game(
    record: Mapping[str, Any], next_kickoffs: Mapping[str, str] | None
) -> bool:
    """Whether ESPN expects the player back only after his team's next game."""
    return_date = str(record.get('return_date') or '')[:10]
    next_game = str((next_kickoffs or {}).get(normalize_team(record.get('team'))) or '')
    if not return_date or not next_game:
        return False
    if len(next_game) == 10:
        game_date = next_game  # already an Eastern game date
    else:
        kickoff = _parse_timestamp(next_game)
        if kickoff is None:
            return False
        # Kickoffs are UTC; a primetime ET game lands on the next UTC day.
        game_date = (kickoff - timedelta(hours=5)).date().isoformat()
    return return_date > game_date


def _status_details(
    record: Mapping[str, Any], next_kickoffs: Mapping[str, str] | None = None
) -> tuple[str, str] | None:
    """The coming-week designation for one ESPN injury row, or ``None``."""
    status = str(record.get('status') or '').strip()
    if status.casefold() in _EMPTY_STATUSES | {'active'}:
        # "Active" rows are news items, not designations.
        return None

    fantasy_status = str(record.get('fantasy_status') or '').strip().upper()
    if fantasy_status in _FANTASY_STATUSES:
        return _FANTASY_STATUSES[fantasy_status]
    if fantasy_status == 'INACTIVE':
        # A game-day inactive from the last game says nothing about the next
        # one unless ESPN does not expect him back for it.
        return ('Out', 'O') if _return_is_after_next_game(record, next_kickoffs) else None
    if fantasy_status in {'ACTIVE', 'PROBABLE'}:
        return None

    normalized_status = status.casefold()
    abbreviation = _STATUS_ABBREVIATIONS.get(normalized_status)
    if not abbreviation:
        abbreviation = status.upper() if len(status) <= 4 else status[:3].upper()
    return status, abbreviation


def match_injuries(
    targets: list[dict[str, str]],
    espn_records: Iterable[Mapping[str, Any]],
    next_kickoffs: Mapping[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Match current QPFL players to ESPN by normalized name, position, and team."""
    by_identity: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in espn_records:
        if not isinstance(record, Mapping):
            continue
        position = str(record.get('position') or '').strip().upper()
        normalized_name = normalize_player_name(record.get('name'))
        if position in SUPPORTED_POSITIONS and normalized_name:
            by_identity[(normalized_name, position)].append(record)

    injuries: dict[str, dict[str, str]] = {}
    for target in targets:
        candidates = by_identity.get(
            (normalize_player_name(target['name']), target['position']), []
        )
        same_team = [
            record for record in candidates if normalize_team(record.get('team')) == target['team']
        ]
        if len(same_team) == 1:
            match = same_team[0]
        elif len(candidates) == 1:
            match = candidates[0]
        else:
            continue

        details = _status_details(match, next_kickoffs)
        if not details:
            continue
        status, abbreviation = details
        entry = {
            'status': status,
            'abbreviation': abbreviation,
        }
        body_part = str(match.get('body_part') or '').strip()
        notes = str(match.get('notes') or '').strip()
        return_date = str(match.get('return_date') or '').strip()[:10]
        if body_part:
            entry['body_part'] = body_part
        if notes:
            entry['notes'] = notes
        if return_date and abbreviation not in {'IR', 'PUP', 'NFI', 'SUS'}:
            entry['return_date'] = return_date
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
        return {'source': SOURCE, 'updated_at': None, 'players': {}}
    return {
        'source': cache.get('source') or SOURCE,
        'updated_at': cache.get('updated_at'),
        'players': cache.get('players', {}),
    }


def _flatten_espn_injuries(payload: Any) -> list[dict[str, Any]]:
    """Flatten ESPN's ``{injuries: [{injuries: [...]}, ...]}`` into one row per player."""
    teams = payload.get('injuries') if isinstance(payload, Mapping) else None
    if not isinstance(teams, list):
        raise ValueError('ESPN injury response must contain an injuries list')
    records: list[dict[str, Any]] = []
    for team in teams:
        for item in (team or {}).get('injuries') or []:
            if not isinstance(item, Mapping):
                continue
            athlete = item.get('athlete') or {}
            details = item.get('details') or {}
            detail = str(details.get('detail') or '').strip()
            position = str((athlete.get('position') or {}).get('abbreviation') or '').upper()
            records.append(
                {
                    'name': athlete.get('displayName')
                    or ' '.join(
                        part for part in (athlete.get('firstName'), athlete.get('lastName')) if part
                    ),
                    'position': _POSITION_ALIASES.get(position, position),
                    'team': (athlete.get('team') or {}).get('abbreviation'),
                    'status': item.get('status'),
                    'fantasy_status': (details.get('fantasyStatus') or {}).get('abbreviation'),
                    'return_date': details.get('returnDate'),
                    'body_part': details.get('type'),
                    'notes': '' if detail.casefold() in {'', 'not specified'} else detail,
                }
            )
    return records


def _fetch_espn_injuries(opener: Callable[..., Any]) -> list[dict[str, Any]]:
    # No custom User-Agent: ESPN answers 403 to unfamiliar agents but accepts
    # urllib's default.
    request = urllib.request.Request(ESPN_INJURIES_URL, headers={'Accept': 'application/json'})
    with opener(request, timeout=30) as response:
        payload = json.load(response)
    return _flatten_espn_injuries(payload)


def load_injury_statuses(
    rosters: Any,
    cache_path: Path,
    *,
    now: datetime | None = None,
    opener: Callable[..., Any] | None = None,
    next_kickoffs: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return coming-week injury badges, refreshing the compact cache every few hours.

    ``next_kickoffs`` (``{team: iso kickoff or game date}``) lets a game-day inactive from
    the last game keep an Out badge when ESPN does not expect him back in time.
    The committed compact cache preserves the last good data during a provider
    outage.
    """
    targets = _target_players(rosters)
    if not targets:
        return {'source': SOURCE, 'updated_at': None, 'players': {}}

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    fingerprint = _target_fingerprint(targets)
    cached = _read_cache(Path(cache_path))
    cached_at = _parse_timestamp(cached.get('updated_at')) if cached else None
    cache_age = current_time - cached_at if cached_at else None
    cache_is_fresh = (
        cached is not None
        # A cache written from another provider has different semantics.
        and cached.get('source') == SOURCE
        and cache_age is not None
        and cache_age < CACHE_TTL
    )
    if cache_is_fresh:
        return _public_payload(cached)

    try:
        records = _fetch_espn_injuries(opener or urllib.request.urlopen)
        injuries = match_injuries(targets, records, next_kickoffs)
    except Exception as exc:
        print(f'  Could not refresh NFL injury statuses; using cached data: {exc}')
        return _public_payload(cached)

    refreshed = {
        'source': SOURCE,
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
