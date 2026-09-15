"""Whether a rostered player is actually expected to take the field this week.

Projections are built from historical scoring, so a player who will not play at
all still projects a full workload until something tells the model otherwise.
Three feeds answer that question:

* nflverse weekly rosters — an NFL roster status per player (``ACT``, ``RES``,
  ``EXE``, ...). This catches situations Sleeper misses entirely, such as a
  player placed on the commissioner exempt list.
* Sleeper injury designations — the payload already cached in
  ``data/injury_statuses.json`` by :mod:`qpfl.injuries`.
* nflverse depth charts — a healthy backup quarterback behind an active
  starter (Kyle Allen behind Josh Allen) is on the active roster and has no
  injury designation, so neither feed above catches him, and a player with
  little or no scoring history of his own falls back to the *starting* QB
  position average. See ``_healthy_backup_reasons``.

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


#: Positions where the depth-chart #1 takes essentially every snap, so a
#: backup with no track record of his own should project near zero rather
#: than the starter average. Deliberately narrow: a WR2/RB2/TE2 "backup"
#: still starts three-wide sets or splits a committee and routinely outscores
#: the QB-style all-or-nothing case this exists for.
BACKUP_ZERO_POSITIONS = {'QB'}

_DEPTH_CHART_ROW_KEYS = ('dt', 'team', 'player_name', 'pos_abb', 'pos_rank')


def compact_depth_chart_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep only each team's latest relevant depth chart.

    nflverse returns a season-long history with hundreds of thousands of rows.
    Backup detection only considers quarterbacks and only the newest chart for
    each team, so retaining older/non-QB rows wastes snapshot space.
    """
    compacted = [
        {key: row.get(key) for key in _DEPTH_CHART_ROW_KEYS}
        for row in rows
        if str(row.get('pos_abb') or '').strip().upper() in BACKUP_ZERO_POSITIONS
        and str(row.get('team') or '').strip()
    ]
    latest_dt: dict[tuple[str, str], str] = {}
    for row in compacted:
        key = (str(row['team']).strip().upper(), str(row['pos_abb']).strip().upper())
        latest_dt[key] = max(latest_dt.get(key, ''), str(row.get('dt') or ''))

    return [
        row
        for row in compacted
        if str(row.get('dt') or '')
        == latest_dt[(str(row['team']).strip().upper(), str(row['pos_abb']).strip().upper())]
    ]


def load_projection_depth_chart_rows(season: int) -> list[dict[str, Any]]:
    """Fetch this season's NFL depth charts from nflverse."""
    import nflreadpy as nfl

    return compact_depth_chart_rows(nfl.load_depth_charts(seasons=[season]).iter_rows(named=True))


def _healthy_backup_reasons(
    depth_chart_rows: Iterable[Mapping[str, Any]], out_reasons: Mapping[str, str]
) -> dict[str, str]:
    """``{injury_identity_key: 'backup'}`` for a healthy backup behind a healthy starter.

    Only positions in :data:`BACKUP_ZERO_POSITIONS` are considered. A player is
    only marked a backup when everyone ranked ahead of him at the same
    team+position is *not already* in ``out_reasons`` — an injured starter
    promotes the next man up to a real workload, and the depth-chart feed can
    lag that promotion by a day or two, so this must never zero the new
    starter along with the old one.
    """
    latest_dt: dict[tuple[str, str], str] = {}
    for row in depth_chart_rows or []:
        position = str(row.get('pos_abb') or '').strip().upper()
        team = str(row.get('team') or '').strip().upper()
        if position not in BACKUP_ZERO_POSITIONS or not team:
            continue
        dt = str(row.get('dt') or '')
        key = (team, position)
        if dt > latest_dt.get(key, ''):
            latest_dt[key] = dt

    ranked_by_team_position: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for row in depth_chart_rows or []:
        position = str(row.get('pos_abb') or '').strip().upper()
        team = str(row.get('team') or '').strip().upper()
        rank = row.get('pos_rank')
        name = normalize_player_name(row.get('player_name'))
        if position not in BACKUP_ZERO_POSITIONS or not team or not name:
            continue
        if not isinstance(rank, int) or str(row.get('dt') or '') != latest_dt.get((team, position)):
            continue
        ranked_by_team_position[(team, position)].append((rank, name))

    reasons: dict[str, str] = {}
    for (_team, position), ranked in ranked_by_team_position.items():
        ranked.sort()
        for i, (_rank, name) in enumerate(ranked):
            ahead = ranked[:i]
            if not ahead:
                continue  # the starter himself - nobody is ahead of #1
            identity = injury_identity_key(name, position)
            healthy_ahead = any(
                injury_identity_key(other_name, position) not in out_reasons
                for _, other_name in ahead
            )
            if healthy_ahead:
                reasons[identity] = 'backup'
    return reasons


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
    depth_chart_rows: Iterable[Mapping[str, Any]] | None = None,
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

    # Depth chart last, and only filling gaps: a player already flagged by his
    # own roster/injury status keeps that more specific reason.
    if depth_chart_rows:
        for identity, reason in _healthy_backup_reasons(depth_chart_rows, lookup).items():
            lookup.setdefault(identity, reason)

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
