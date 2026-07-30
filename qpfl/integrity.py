"""Cross-file integrity invariants over data/ that no single schema can express.

Complements qpfl/data_validation.py (per-file structural validation). Each
check function takes already-loaded data and returns a list of human-readable
violation strings; check_all() runs everything against DATA_DIR.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qpfl.constants import ALL_TEAMS, DATA_DIR
from qpfl.utils import load_json_safe


def check_roster_invariants(rosters: dict[str, list[dict]], league_config: dict) -> list[str]:
    """Every player on at most one roster; slot limits respected; taxi one-per-position."""
    errors: list[str] = []
    roster_slots = league_config.get('roster_slots', {})
    taxi_slots = league_config.get('taxi_slots')

    # D/ST and OL are drafted from the same pool of NFL team names but are
    # independent draftable units (e.g. "Chicago Bears" can be one team's
    # D/ST and another team's OL simultaneously) — so ownership uniqueness is
    # scoped by (name, position), not name alone.
    seen: dict[tuple[str, str], str] = {}
    for team, players in rosters.items():
        active_counts: dict[str, int] = {}
        taxi_positions: set[str] = set()
        taxi_count = 0
        seen_on_team: set[tuple[str, str, bool]] = set()

        for p in players:
            name, pos, is_taxi = p['name'], p['position'], p.get('taxi', False)

            dup_key = (name, pos, is_taxi)
            if dup_key in seen_on_team:
                errors.append(
                    f'roster[{team}]: duplicate entry for {name!r} ({pos}, taxi={is_taxi})'
                )
            seen_on_team.add(dup_key)

            owner_key = (name, pos)
            if owner_key in seen and seen[owner_key] != team:
                errors.append(
                    f'{name!r} ({pos}) appears on both {seen[owner_key]!r} and {team!r} rosters'
                )
            seen[owner_key] = team

            if is_taxi:
                taxi_count += 1
                if pos in taxi_positions:
                    errors.append(f'roster[{team}]: taxi squad has more than one {pos}')
                taxi_positions.add(pos)
            else:
                active_counts[pos] = active_counts.get(pos, 0) + 1

        for pos, count in active_counts.items():
            limit = roster_slots.get(pos)
            if limit is not None and count > limit:
                errors.append(f'roster[{team}]: {count} active {pos} exceeds limit of {limit}')

        if taxi_slots is not None and taxi_count > taxi_slots:
            errors.append(
                f'roster[{team}]: {taxi_count} taxi players exceeds limit of {taxi_slots}'
            )

    return errors


def check_lineup_starters_on_roster(lineup_file: dict, rosters: dict[str, list[dict]]) -> list[str]:
    """Every submitted starter must be on the team's active (non-taxi) roster
    at the submitted position — mirrors api/lineup.py's live check, applied
    retroactively/repo-wide."""
    errors: list[str] = []
    week = lineup_file.get('week')

    for team, entry in lineup_file.get('lineups', {}).items():
        active_by_pos: dict[str, set[str]] = {}
        for p in rosters.get(team, []):
            if not p.get('taxi'):
                active_by_pos.setdefault(p['position'], set()).add(p['name'])

        for key, val in entry.items():
            if key in ('submitted_at', 'comment') or not isinstance(val, list):
                continue
            pos = key
            for starter in val:
                if starter not in active_by_pos.get(pos, set()):
                    errors.append(
                        f'week {week} lineup[{team}]: starter {starter!r} at {pos} '
                        f'not found on active roster'
                    )
    return errors


def check_pending_trades(pending: dict, rosters: dict[str, list[dict]]) -> list[str]:
    """Proposed players still owned by the offering side (for still-pending
    trades); no trade stuck in-progress for more than an hour."""
    errors: list[str] = []
    now = datetime.now(timezone.utc)

    for trade in pending.get('trades', []):
        status = trade.get('status')
        proposer = trade.get('proposer')
        offered = trade.get('proposer_gives', {}).get('players', [])

        if status == 'pending':
            owned = {p['name'] for p in rosters.get(proposer, [])}
            for name in offered:
                if name not in owned:
                    errors.append(
                        f'pending trade {trade.get("id")}: {proposer!r} offers '
                        f'{name!r} but does not own it'
                    )

        if trade.get('execution') == 'in_progress':
            started = _parse_timestamp(trade.get('proposed_at'))
            age_hours = (now - started).total_seconds() / 3600 if started else None
            if age_hours is not None and age_hours > 1:
                errors.append(
                    f'trade {trade.get("id")} stuck in execution:in_progress for '
                    f'{age_hours:.1f}h — needs commissioner reconciliation'
                )

    return errors


def check_draft_picks(draft_picks: dict) -> list[str]:
    """Each (year, round, original_team) pick exists exactly once; owners are valid teams."""
    errors: list[str] = []
    seen: dict[tuple, int] = {}

    for pick in draft_picks.get('picks', []):
        key = (str(pick['year']), pick['round'], pick.get('draft_type'), pick['original_team'])
        seen[key] = seen.get(key, 0) + 1
        if pick['current_owner'] not in ALL_TEAMS:
            errors.append(
                f'draft pick {key}: current_owner {pick["current_owner"]!r} is not a known team'
            )

    for key, count in seen.items():
        if count > 1:
            errors.append(f'draft pick {key} appears {count} times (expected exactly once)')

    return errors


def _parse_timestamp(raw: str) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        ts = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # A handful of 2023-era entries use "MM-DD-YYT..." instead of ISO order.
    for fmt in ('%m-%d-%yT%H:%M:%S', '%m-%d-%YT%H:%M:%S'):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# A batch of 2023 entries were backfilled from historical records without a
# known exact date and share this placeholder timestamp; they're intentionally
# excluded from ordering checks (real corruption isn't hiding in known noise).
_PLACEHOLDER_TIMESTAMP = '2023-01-01T00:00:00'


def check_transaction_log_ordering(transaction_log: dict) -> list[str]:
    """Log is append-newest-first; every timestamp must parse."""
    errors: list[str] = []
    timestamps: list[tuple[int, datetime]] = []

    for i, txn in enumerate(transaction_log.get('transactions', [])):
        raw = txn.get('timestamp')
        if raw == _PLACEHOLDER_TIMESTAMP:
            continue
        ts = _parse_timestamp(raw)
        if ts is None:
            errors.append(f'transaction_log[{i}]: unparseable timestamp {raw!r}')
            continue
        timestamps.append((i, ts))

    for (i, ts), (prev_i, prev_ts) in zip(timestamps[1:], timestamps, strict=False):
        if ts > prev_ts:
            errors.append(
                f'transaction_log: entry {i} ({ts}) is newer than entry '
                f'{prev_i} ({prev_ts}) — expected newest-first ordering'
            )

    return errors


def check_all(data_dir: Path | str = DATA_DIR) -> list[str]:
    data_dir = Path(data_dir)
    errors: list[str] = []

    rosters: dict[str, Any] = load_json_safe(data_dir / 'rosters.json', default={})
    league_config: dict[str, Any] = load_json_safe(data_dir / 'league_config.json', default={})
    pending: dict[str, Any] = load_json_safe(
        data_dir / 'pending_trades.json', default={'trades': []}
    )
    draft_picks: dict[str, Any] = load_json_safe(
        data_dir / 'draft_picks.json', default={'picks': []}
    )
    transaction_log: dict[str, Any] = load_json_safe(
        data_dir / 'transaction_log.json', default={'transactions': []}
    )

    if rosters and league_config:
        errors.extend(check_roster_invariants(rosters, league_config))

    # rosters.json reflects only the *current* roster state (post-trade/draft),
    # so this check only makes sense for the current season's lineup files —
    # a prior season's rosters have since changed via trades/drafts.
    current_season = league_config.get('current_season')
    lineups_dir = data_dir / 'lineups' / str(current_season) if current_season else None
    if lineups_dir and lineups_dir.is_dir() and rosters:
        for week_file in sorted(lineups_dir.glob('week_*.json')):
            lineup_file = load_json_safe(week_file, default=None)
            if lineup_file:
                errors.extend(check_lineup_starters_on_roster(lineup_file, rosters))

    if rosters:
        errors.extend(check_pending_trades(pending, rosters))

    errors.extend(check_draft_picks(draft_picks))
    errors.extend(check_transaction_log_ordering(transaction_log))

    return errors
