"""HTML bodies for the trade and roster-move emails sent from notify.yml."""

from collections.abc import Mapping, Sequence

from scripts import email_html as html

TRADE_TITLES = {
    'accepted': 'Trade completed',
    'rejected': 'Trade rejected',
}

TRANSACTIONS_URL = 'https://qpfl.org/#transactions'


def resolve_trade_player(
    player: object,
    giver: str,
    receiver: str,
    rosters_before: Mapping | None,
    rosters_after: Mapping | None,
) -> object:
    """Turn a bare player name from ``pending_trades.json`` into its roster entry.

    Trades store names only, and names like "Detroit Lions" are ambiguous
    (D/ST vs OL). The giver's roster before the commit holds the player; once
    an accepted trade has moved it, the receiver's roster after the commit
    does. Returns the original value when it can't be resolved.
    """
    if not isinstance(player, str):
        return player
    for rosters, team in ((rosters_before, giver), (rosters_after, receiver), (rosters_after, giver)):
        for entry in (rosters or {}).get(team, []) or []:
            if isinstance(entry, Mapping) and entry.get('name') == player:
                return dict(entry)
    return player


def _item_list(items: Sequence[str]) -> str:
    if not items:
        return f'<div style="padding:12px 16px;">{html.muted("Nothing")}</div>'
    return html.table([(html.esc(item),) for item in items])


def trade_html(
    status: str,
    timestamp: str,
    proposer: str,
    partner: str,
    proposer_sends: Sequence[str],
    partner_sends: Sequence[str],
    comment: str | None = None,
    comment_by: str | None = None,
    takes_effect: str | None = None,
    conditional_notes: str | None = None,
) -> str:
    """``proposer``/``partner`` are display labels such as "Griff (GSA)"."""
    title = TRADE_TITLES.get(status, 'Trade proposal')
    blocks = [
        html.section_heading('The deal'),
        html.card(_item_list(proposer_sends), title=f'{proposer} sends'),
        html.card(_item_list(partner_sends), title=f'{partner} sends'),
    ]
    if comment:
        blocks.append(
            html.card(
                '<div style="height:14px;"></div>'
                + html.quote(comment, f'Message from {comment_by or proposer}')
            )
        )
    if conditional_notes:
        blocks.append(
            html.card(
                '<div style="height:14px;"></div>'
                + html.quote(conditional_notes, 'Conditions / notes')
            )
        )
    if takes_effect:
        blocks.append(html.paragraph(f'Takes effect: <b>{html.esc(takes_effect)}</b>', muted=True))
    return html.render_email(title, timestamp, blocks, cta=('View transactions', TRANSACTIONS_URL))


def roster_moves_html(week: object, timestamp: str, moves: Sequence[Mapping]) -> str:
    """Each move: ``type``, ``team`` (display label), ``added``, ``released``, ``takes_effect``."""
    blocks = []
    for move in moves:
        rows = []
        if move.get('added'):
            rows.append((html.pill('Added', 'green'), f'<b>{html.esc(move["added"])}</b>'))
        if move.get('released'):
            rows.append((html.pill('Released', 'red'), html.esc(move['released'])))
        inner = html.table(rows, shrink=[0])
        if move.get('takes_effect'):
            inner += html.small_note(f'Takes effect: {html.esc(move["takes_effect"])}')
        blocks.append(html.card(inner, title=str(move.get('team', '')), subtitle=move.get('type')))
    title = f'Roster moves · Week {week}' if week is not None else 'Roster moves'
    return html.render_email(title, timestamp, blocks, cta=('View transactions', TRANSACTIONS_URL))
