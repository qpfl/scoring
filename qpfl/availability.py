"""Whether a rostered player is actually expected to take the field this week.

Projections are built from historical scoring, so a player who will not play at
all still projects a full workload until something tells the model otherwise.
Two feeds answer that question:

* nflverse weekly rosters — an NFL roster status per player (``ACT``, ``RES``,
  ``EXE``, ...). This catches situations Sleeper misses entirely, such as a
  player placed on the commissioner exempt list.
* Sleeper injury designations — the payload already cached in
  ``data/injury_statuses.json`` by :mod:`qpfl.injuries`.

Every lookup fails open: an unknown player, an unmatched name, or a missing feed
means the projection is left alone. A wrong zero is worse than a stale number.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .injuries import SUPPORTED_POSITIONS, injury_identity_key, normalize_player_name

#: Sleeper designations that mean the player is not expected to play. Anything
#: else — most importantly ``Questionable`` — keeps its full projection.
OUT_INJURY_STATUSES = {
    'out': 'out',
    'doubtful': 'doubtful',
    'ir': 'ir',
    'injured reserve': 'ir',
    'pup': 'pup',
    'physically unable to perform': 'pup',
    'nfi': 'nfi',
    'non-football injury': 'nfi',
    'suspended': 'suspended',
}

#: The only nflverse roster status that means "on the active roster".
AVAILABLE_ROSTER_STATUSES = {'ACT'}

#: nflverse roster status codes mapped to the reason we surface.
ROSTER_STATUS_REASONS = {
    'RES': 'reserve',
    'RET': 'retired',
    'CUT': 'not_on_roster',
    'EXE': 'exempt',
    'DEV': 'practice_squad',
}

_ROSTER_ROW_KEYS = ('full_name', 'team', 'position', 'status')


def compact_roster_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the columns the availability lookup needs.

    Mirrors :func:`qpfl.projections.compact_schedule_rows` so the result is cheap
    to store inside a stat snapshot.
    """
    return [{key: row.get(key) for key in _ROSTER_ROW_KEYS} for row in rows]


def load_projection_roster_rows(season: int) -> list[dict[str, Any]]:
    """Fetch this season's NFL roster statuses from nflverse."""
    import nflreadpy as nfl

    return compact_roster_rows(nfl.load_rosters(seasons=[season]).iter_rows(named=True))


def _roster_status_reason(status: Any) -> str | None:
    code = str(status or '').strip().upper()
    if not code or code in AVAILABLE_ROSTER_STATUSES:
        return None
    return ROSTER_STATUS_REASONS.get(code, 'inactive')


def _injury_status_reason(entry: Any) -> str | None:
    if not isinstance(entry, Mapping):
        return None
    status = str(entry.get('status') or '').strip().casefold()
    return OUT_INJURY_STATUSES.get(status)


def build_availability_lookup(
    roster_rows: Iterable[Mapping[str, Any]] | None = None,
    injury_payload: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Map ``injury_identity_key`` to a reason a player will not play.

    Players who are expected to play are simply absent from the result. Only the
    skill positions Sleeper and nflverse both describe are considered — D/ST, OL,
    and HC availability is handled elsewhere.
    """
    lookup: dict[str, str] = {}

    # Roster status first: it is the broader feed, but ambiguous names get
    # dropped rather than guessed at.
    by_identity: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in roster_rows or []:
        position = str(row.get('position') or '').strip().upper()
        name = normalize_player_name(row.get('full_name'))
        if position in SUPPORTED_POSITIONS and name:
            by_identity[(name, position)].append(row)

    for (name, position), candidates in by_identity.items():
        reasons = {_roster_status_reason(row.get('status')) for row in candidates}
        if len(reasons) != 1:
            # Same name at the same position on two different rosters with
            # conflicting statuses — not worth guessing.
            continue
        reason = reasons.pop()
        if reason:
            lookup[injury_identity_key(name, position)] = reason

    # Sleeper designations win where both feeds have an opinion: they are the
    # more specific signal ("out with a hamstring" beats "not ACT").
    players = (injury_payload or {}).get('players') if injury_payload else None
    if isinstance(players, Mapping):
        for key, entry in players.items():
            reason = _injury_status_reason(entry)
            if reason:
                lookup[str(key)] = reason

    return lookup


# --- Head coaches -----------------------------------------------------------
#
# A rostered HC only scores off his team's game result, so a coach who no longer
# has the job must not keep projecting. The nflverse schedule names the coach for
# every game, but it lags a firing by days — it had Jesse Minter in Baltimore
# immediately while still listing Sean McDermott in Buffalo after Joe Brady was
# promoted. `data/coach_overrides.json` is the manual escape hatch, and it wins.

COACH_OVERRIDES_FILENAME = 'coach_overrides.json'


def load_coach_overrides(path: Path | str) -> dict[str, str]:
    """Read ``{team: head coach}`` overrides, returning ``{}`` when unusable."""
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    coaches = payload.get('coaches') if isinstance(payload, Mapping) else None
    if not isinstance(coaches, Mapping):
        return {}
    return {
        str(team).strip().upper(): str(name).strip()
        for team, name in coaches.items()
        if str(team).strip() and str(name).strip()
    }


def is_listed_head_coach(name: str, scheduled_coach: str | None, override: str | None) -> bool:
    """Whether ``name`` is the head coach of the team he is rostered against.

    Returns ``True`` when there is nothing to check against, so an unknown coach
    keeps his projection.
    """
    expected = override or scheduled_coach
    if not expected:
        return True
    return normalize_player_name(name) == normalize_player_name(expected)
