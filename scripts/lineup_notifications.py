"""Formatting helpers for lineup notification emails."""

from collections.abc import Mapping
from typing import Any

POSITION_ORDER = ('QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL')
METADATA_FIELDS = frozenset({'comment', 'submitted_at', 'starters'})


def _normalized_name(name: str) -> str:
    return ' '.join(name.strip().casefold().split())


def _positions(lineup: Mapping[str, Any], previous: Mapping[str, Any] | None) -> list[str]:
    available = {
        key
        for source in (lineup, previous or {})
        for key, value in source.items()
        if key not in METADATA_FIELDS and isinstance(value, list)
    }
    ordered = [position for position in POSITION_ORDER if position in available]
    return ordered + sorted(available.difference(POSITION_ORDER))


def _players(lineup: Mapping[str, Any], position: str) -> list[str]:
    value = lineup.get(position, [])
    if not isinstance(value, list):
        return []
    return [name for name in value if isinstance(name, str) and name.strip()]


def format_lineup_rows(
    lineup: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> list[str]:
    """Render the full current lineup while marking changes from the prior submission."""
    rows: list[str] = []
    previous_lineup = previous or {}
    is_update = bool(previous_lineup) and (
        bool(previous_lineup.get('submitted_at'))
        or any(
            _players(previous_lineup, position) for position in _positions(lineup, previous_lineup)
        )
    )

    for position in _positions(lineup, previous):
        current_players = _players(lineup, position)
        if not is_update:
            rows.extend(f'  {position}: {player}' for player in current_players)
            continue

        previous_players = _players(previous_lineup, position)
        current_names = {_normalized_name(player) for player in current_players}
        previous_names = {_normalized_name(player) for player in previous_players}
        removed = [
            player for player in previous_players if _normalized_name(player) not in current_names
        ]
        added = [
            player for player in current_players if _normalized_name(player) not in previous_names
        ]
        replacement_for = dict(zip(added, removed, strict=False))

        for player in current_players:
            if player in replacement_for:
                rows.append(f'  {position}: {replacement_for[player]} → {player}  [CHANGED]')
            elif player in added:
                rows.append(f'  {position}: [OPEN] → {player}  [CHANGED]')
            else:
                rows.append(f'  {position}: {player}')

        for player in removed[len(added) :]:
            rows.append(f'  {position}: {player} → [OPEN]  [CHANGED]')

    return rows


def format_lineup_notification(
    team_code: str,
    owner: str,
    week: str | int | None,
    lineup: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> str:
    """Format one team's section in the multi-team lineup notification email."""
    lines = [
        '------------------------------',
        f'Week {week} - {owner} ({team_code})',
        '------------------------------',
        *format_lineup_rows(lineup, previous),
    ]

    comment = lineup.get('comment')
    if isinstance(comment, str) and comment.strip():
        lines.extend(('', f'Message from {owner}:', f'"{comment.strip()}"'))

    return '\n'.join(lines) + '\n\n'
