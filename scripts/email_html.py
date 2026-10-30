"""Branded HTML layout and building blocks for QPFL emails.

Email clients ignore <style> blocks unevenly and don't support flexbox or grid,
so everything here is table layout with inline styles. The league logo is sent
as an inline attachment (see email_delivery.send_email) and referenced by
``cid:`` so it shows without the recipient having to load remote images.
"""

import re
from collections.abc import Iterable, Sequence
from html import escape

LOGO_CID = 'qpfl-logo'

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
NAVY = '#0f1f3d'
RED = '#c8102e'
PAGE_BG = '#eef0f4'
CARD_BG = '#ffffff'
BORDER = '#e3e6ec'
TEXT = '#1b1f27'
MUTED = '#6b7280'
GREEN = '#15803d'
GREEN_BG = '#e8f6ee'
AMBER_BG = '#fff6db'
AMBER = '#92600a'
BLUE = '#1d4ed8'
BLUE_BG = '#e8effd'
RED_BG = '#fdecee'

TONES = {
    'green': (GREEN, GREEN_BG),
    'amber': (AMBER, AMBER_BG),
    'blue': (BLUE, BLUE_BG),
    'red': (RED, RED_BG),
    'navy': ('#ffffff', NAVY),
}


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def pill(text: str, tone: str = 'green') -> str:
    color, background = TONES[tone]
    return (
        f'<span style="display:inline-block;padding:2px 7px;border-radius:999px;'
        f'background:{background};color:{color};font-size:10px;font-weight:700;'
        f'letter-spacing:0.06em;text-transform:uppercase;vertical-align:middle;">'
        f'{esc(text)}</span>'
    )


def section_heading(text: str) -> str:
    return (
        f'<div style="margin:28px 0 10px;font-size:12px;font-weight:700;letter-spacing:0.12em;'
        f'text-transform:uppercase;color:{RED};">{esc(text)}</div>'
    )


def card(inner: str, title: str | None = None, subtitle: str | None = None) -> str:
    """A bordered white block; ``inner`` is trusted HTML."""
    header = ''
    if title:
        sub = (
            f'<div style="font-size:12px;font-weight:400;color:{MUTED};margin-top:2px;">'
            f'{esc(subtitle)}</div>'
            if subtitle
            else ''
        )
        header = (
            f'<div style="padding:12px 16px;border-bottom:1px solid {BORDER};'
            f'font-size:15px;font-weight:700;color:{TEXT};">{esc(title)}{sub}</div>'
        )
    return (
        f'<div style="background:{CARD_BG};border:1px solid {BORDER};border-radius:8px;'
        f'margin:0 0 12px;overflow:hidden;">{header}{inner}</div>'
    )


def paragraph(inner: str, muted: bool = False, size: int = 15) -> str:
    """A paragraph; ``inner`` is trusted HTML."""
    color = MUTED if muted else TEXT
    return (
        f'<p style="margin:0 0 14px;font-size:{size}px;line-height:1.55;color:{color};">{inner}</p>'
    )


def quote(text: str, attribution: str) -> str:
    return (
        f'<div style="margin:0 16px 14px;padding:10px 14px;border-left:3px solid {RED};'
        f'background:#f7f8fa;border-radius:0 6px 6px 0;">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;'
        f'color:{MUTED};margin-bottom:4px;">{esc(attribution)}</div>'
        f'<div style="font-size:14px;line-height:1.5;color:{TEXT};font-style:italic;">'
        f'&ldquo;{esc(text)}&rdquo;</div></div>'
    )


def table(
    rows: Iterable[Sequence[str]],
    header: Sequence[str] | None = None,
    align: Sequence[str] | None = None,
    row_backgrounds: Sequence[str | None] | None = None,
    shrink: Sequence[int] = (),
) -> str:
    """A full-width data table; each cell is trusted HTML.

    Columns listed in ``shrink`` hug their content so the rest take the width.
    """
    rows = list(rows)
    width = len(header) if header else max((len(row) for row in rows), default=0)
    align = list(align or ['left'] * width)
    cell = 'padding:9px 12px;font-size:14px;color:{color};text-align:{align};{extra}'
    narrow = 'width:1%;white-space:nowrap;'
    parts = [
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;">'
    ]
    if header:
        parts.append('<tr>')
        for index, label in enumerate(header):
            style = cell.format(
                color=MUTED,
                align=align[index],
                extra=f'font-size:11px;font-weight:700;letter-spacing:0.06em;'
                f'text-transform:uppercase;border-bottom:1px solid {BORDER};'
                + (narrow if index in shrink else ''),
            )
            parts.append(f'<th style="{style}">{esc(label)}</th>')
        parts.append('</tr>')
    for row_index, row in enumerate(rows):
        background = (row_backgrounds or [None] * len(rows))[row_index]
        bg_style = f' style="background:{background};"' if background else ''
        parts.append(f'<tr{bg_style}>')
        for index, value in enumerate(row):
            border = f'border-top:1px solid {BORDER};' if row_index or header else ''
            style = cell.format(
                color=TEXT, align=align[index], extra=border + (narrow if index in shrink else '')
            )
            parts.append(f'<td style="{style}">{value}</td>')
        parts.append('</tr>')
    parts.append('</table>')
    return ''.join(parts)


def muted(text: str) -> str:
    return f'<span style="color:{MUTED};">{esc(text)}</span>'


def small_note(inner: str) -> str:
    """A footer strip inside a card; ``inner`` is trusted HTML."""
    return (
        f'<div style="padding:8px 16px;border-top:1px solid {BORDER};background:#f7f8fa;'
        f'font-size:12px;color:{MUTED};">{inner}</div>'
    )


def button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px auto 4px;">'
        f'<tr><td style="border-radius:6px;background:{RED};">'
        f'<a href="{esc(url)}" style="display:inline-block;padding:12px 26px;font-family:{FONT};'
        f'font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:6px;">'
        f'{esc(label)}</a></td></tr></table>'
    )


def render_email(
    title: str,
    subtitle: str,
    blocks: Iterable[str],
    cta: tuple[str, str] | None = None,
    footnote: str | None = None,
) -> str:
    """Wrap trusted HTML ``blocks`` in the branded page: logo header, body, button, footer."""
    body = ''.join(blocks)
    if cta:
        body += button(*cta)
    if footnote:
        body += (
            f'<p style="margin:14px 0 0;font-size:13px;line-height:1.5;color:{MUTED};'
            f'text-align:center;">{esc(footnote)}</p>'
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{esc(title)}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE_BG};font-family:{FONT};color:{TEXT};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE_BG};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;">
<tr><td style="background:{NAVY};border-radius:10px 10px 0 0;border-bottom:4px solid {RED};padding:22px 24px;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:14px;vertical-align:middle;">
<img src="cid:{LOGO_CID}" width="56" height="56" alt="QPFL" style="display:block;border:0;border-radius:50%;">
</td>
<td style="vertical-align:middle;">
<div style="font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:#aab6cc;">Quarantine Perennial Football League</div>
<div style="font-size:22px;font-weight:800;line-height:1.25;color:#ffffff;margin-top:3px;">{esc(title)}</div>
<div style="font-size:13px;color:#c9d2e3;margin-top:3px;">{esc(subtitle)}</div>
</td>
</tr></table>
</td></tr>
<tr><td style="background:{PAGE_BG};padding:8px 0 0;">
{body}
</td></tr>
<tr><td style="padding:22px 8px 0;text-align:center;font-size:12px;line-height:1.5;color:{MUTED};">
Sent by the QPFL Bot &middot; <a href="https://qpfl.org/" style="color:{MUTED};">qpfl.org</a>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


_URL = re.compile(r'https?://[^\s<>"]+')
_RULE = re.compile(r'^\s*[=\-]{6,}\s*$')


def text_to_html(subject: str, body: str) -> str:
    """Fallback for emails that only build plain text: the same text, in the branded frame."""
    lines = body.rstrip('\n').split('\n')
    rendered = []
    for line in lines:
        if _RULE.match(line):
            rendered.append(f'<div style="border-top:1px solid {BORDER};margin:6px 0;"></div>')
            continue
        escaped = esc(line)
        escaped = _URL.sub(
            lambda match: f'<a href="{match.group(0)}" style="color:{BLUE};">{match.group(0)}</a>',
            escaped,
        )
        rendered.append(escaped or '&nbsp;')
    inner = (
        f'<div style="padding:16px;font-size:14px;line-height:1.55;white-space:pre-wrap;'
        f'color:{TEXT};">{"<br>".join(rendered)}</div>'
    )
    return render_email(subject, '', [card(inner)])
