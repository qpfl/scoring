"""Formatting helpers for lineup notification emails."""

from collections.abc import Mapping
from typing import Any

from scripts import email_html as html

POSITION_ORDER = ('QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL')
METADATA_FIELDS = frozenset({'comment', 'submitted_at', 'starters'})
OPEN = '[OPEN]'


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


def lineup_changed(lineup: Mapping[str, Any], previous: Mapping[str, Any] | None) -> bool:
    """Whether a team's lineup differs from its prior version in anything but
    submitted_at, so re-saving an unchanged lineup doesn't send an email.
    A comment change alone still counts."""

    def meaningful(entry: Mapping[str, Any] | None) -> dict[str, Any]:
        return {key: value for key, value in (entry or {}).items() if key != 'submitted_at'}

    return meaningful(lineup) != meaningful(previous)


def lineup_slots(
    lineup: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> list[tuple[str, str | None, str | None]]:
    """Every slot of the current lineup as (position, previous player, current player).

    The previous player is set only where the slot changed; None on either side
    of a change means an open slot. A first submission reports no changes.
    """
    slots: list[tuple[str, str | None, str | None]] = []
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
            slots.extend((position, None, player) for player in current_players)
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
                slots.append((position, replacement_for[player], player))
            elif player in added:
                slots.append((position, OPEN, player))
            else:
                slots.append((position, None, player))

        for player in removed[len(added) :]:
            slots.append((position, player, OPEN))

    return slots


def format_lineup_rows(
    lineup: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> list[str]:
    """Render the full current lineup while marking changes from the prior submission."""
    rows = []
    for position, before, after in lineup_slots(lineup, previous):
        if before is None:
            rows.append(f'  {position}: {after}')
        else:
            rows.append(f'  {position}: {before} → {after}  [CHANGED]')
    return rows


def _comment(lineup: Mapping[str, Any]) -> str | None:
    comment = lineup.get('comment')
    return comment.strip() if isinstance(comment, str) and comment.strip() else None


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

    comment = _comment(lineup)
    if comment:
        lines.extend(('', f'Message from {owner}:', f'"{comment}"'))

    return '\n'.join(lines) + '\n\n'


def lineup_notification_html(
    team_code: str,
    owner: str,
    week: str | int | None,
    lineup: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> str:
    """One team's card in the HTML lineup notification email."""
    rows = []
    backgrounds = []
    changes = 0
    for position, before, after in lineup_slots(lineup, previous):
        if before is None:
            player = html.esc(after)
            badge = ''
            backgrounds.append(None)
        else:
            changes += 1
            old = (
                html.muted('Open slot')
                if before == OPEN
                else (
                    f'<span style="color:{html.MUTED};text-decoration:line-through;">'
                    f'{html.esc(before)}</span>'
                )
            )
            new = html.muted('Open slot') if after == OPEN else f'<b>{html.esc(after)}</b>'
            player = f'{old} &rarr; {new}'
            badge = html.pill('Changed', 'amber')
            backgrounds.append(html.AMBER_BG)
        rows.append((html.pill(position, 'blue'), player, badge))

    inner = html.table(
        rows, align=['left', 'left', 'right'], row_backgrounds=backgrounds, shrink=[0, 2]
    )
    comment = _comment(lineup)
    if comment:
        inner += '<div style="height:14px;"></div>' + html.quote(comment, f'Message from {owner}')
    subtitle = f'Week {week}'
    if changes:
        subtitle += f' · {changes} change{"s" if changes != 1 else ""}'
    return html.card(inner, title=f'{owner} ({team_code})', subtitle=subtitle)
