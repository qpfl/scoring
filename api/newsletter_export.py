"""Build the commissioner's weekly newsletter template as a Word document.

The template mirrors the league's hand-assembled newsletter: standings up top,
the latest results and their "By the Numbers" notes, next week's matchups, the
NFL's primetime games and byes, then empty sections for the commissioner's own
write-up.

Everything comes from the same web JSON the site renders (meta, standings, week
files, and the weekly facts from scripts/export_weekly_facts.py), and the .docx is written as raw WordprocessingML so the Vercel
runtime needs no extra dependency.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from io import BytesIO
from xml.sax.saxutils import escape

try:
    from zoneinfo import ZoneInfo

    EASTERN = ZoneInfo('America/New_York')
except Exception:  # pragma: no cover - tzdata missing on the runtime
    EASTERN = timezone(timedelta(hours=-4))

DOCX_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
FIRST_SEASON = 2020  # Vol. I

# The names the newsletter has always used; anyone missing falls back to owner
# first names joined with "/".
NEWSLETTER_NAMES = {
    'GSA': 'Griff',
    'RPA': 'Ryan',
    'CGK': 'Kaminska',
    'CWR': 'Redacted/Jack',
    'S/T': 'Spencer/Tim',
    'J/J': 'Joe/Joe',
    'SLS': 'Stephen',
    'AYP': 'Arnav',
    'AST': 'Anagh',
    'WJK': 'Bill',
}

# Duplicated from qpfl/constants.py: Vercel functions can't import qpfl.
NFL_TEAM_NAMES = {
    'ARI': 'Arizona Cardinals',
    'ATL': 'Atlanta Falcons',
    'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers',
    'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals',
    'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos',
    'DET': 'Detroit Lions',
    'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans',
    'IND': 'Indianapolis Colts',
    'JAC': 'Jacksonville Jaguars',
    'JAX': 'Jacksonville Jaguars',
    'KC': 'Kansas City Chiefs',
    'LV': 'Las Vegas Raiders',
    'LAC': 'Los Angeles Chargers',
    'LA': 'Los Angeles Rams',
    'LAR': 'Los Angeles Rams',
    'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings',
    'NE': 'New England Patriots',
    'NO': 'New Orleans Saints',
    'NYG': 'New York Giants',
    'NYJ': 'New York Jets',
    'PHI': 'Philadelphia Eagles',
    'PIT': 'Pittsburgh Steelers',
    'SF': 'San Francisco 49ers',
    'SEA': 'Seattle Seahawks',
    'TB': 'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans',
    'WAS': 'Washington Commanders',
}

ROMAN = [(10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
STANDINGS_COLUMNS = [
    ('Team', 3735),
    ('Rank Points', 1500),
    ('Wins', 795),
    ('Top Half', 1125),
    ('PF', 1065),
    ('PA', 1140),
]


# --------------------------------------------------------------------------- #
# Data selection
# --------------------------------------------------------------------------- #


def load_newsletter_sources(read: Callable[[str], object], season: int) -> dict:
    """Gather the JSON the newsletter needs. `read(path)` returns parsed JSON or
    None when the file doesn't exist.

    The results week is the latest week whose games are all final (standings only
    count those), and the preview week is the one after it.
    """
    base = f'web/data/seasons/{season}'
    meta = read(f'{base}/meta.json')
    standings = read(f'{base}/standings.json')
    if not isinstance(meta, dict) or not isinstance(standings, dict):
        raise ValueError(f'{season} season data was not found')

    weeks: dict[int, dict | None] = {}

    def week(number: int) -> dict | None:
        if number < 1:
            return None
        if number not in weeks:
            data = read(f'{base}/weeks/week_{number}.json')
            weeks[number] = data if isinstance(data, dict) else None
        return weeks[number]

    current = int(meta.get('current_week') or 0)
    current_data = week(current)
    if current_data and current_data.get('has_scores') and current_data.get('games_final'):
        results_week = current
    else:
        results_week = current - 1

    facts = read(f'{base}/facts/week_{results_week}.json') if results_week > 0 else None

    return {
        'season': season,
        'meta': meta,
        'standings': standings,
        'results_week': results_week,
        'results': week(results_week),
        'facts': facts if isinstance(facts, dict) else None,
        'upcoming_week': results_week + 1,
        'upcoming': week(results_week + 1),
    }


# --------------------------------------------------------------------------- #
# Content helpers
# --------------------------------------------------------------------------- #


def _roman(number: int) -> str:
    out = ''
    for value, numeral in ROMAN:
        while number >= value:
            out += numeral
            number -= value
    return out or 'I'


def _number(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ''
    return str(int(value)) if value.is_integer() else f'{value:g}'


def _short_names(meta: dict) -> dict[str, str]:
    names = {}
    for team in meta.get('teams', []):
        abbrev = team.get('abbrev')
        if not abbrev:
            continue
        owners = str(team.get('owner') or '').split('&')
        fallback = '/'.join(owner.split()[0] for owner in owners if owner.split()) or abbrev
        names[abbrev] = NEWSLETTER_NAMES.get(abbrev, fallback)
    return names


def _schedule_entry(meta: dict, week: int) -> dict | None:
    for entry in meta.get('schedule', []):
        if entry.get('week') == week:
            return entry
    return None


def _week_label(entry: dict | None, week: int) -> str:
    if entry and entry.get('is_playoffs'):
        return f'Playoffs, Week {week}'
    if entry and entry.get('is_rivalry'):
        return f'Rivalry Week {week}'
    return f'Week {week}'


def _team_label(team, names: dict[str, str]) -> str:
    if isinstance(team, dict):
        team = team.get('abbrev') or team.get('name')
    if not team:
        return 'TBD'
    return names.get(team, str(team))


def _result_lines(
    week_data: dict | None, names: dict[str, str]
) -> list[list[tuple[str, bool, bool]]]:
    """Each matchup as runs of (text, bold, italic): winner listed first and
    bolded, top-half scorers italicized."""
    if not week_data:
        return []
    teams = week_data.get('teams') or []
    half = len(teams) // 2 or 1
    lines = []
    for matchup in week_data.get('matchups') or []:
        one, two = matchup.get('team1') or {}, matchup.get('team2') or {}
        s1, s2 = float(one.get('total_score') or 0), float(two.get('total_score') or 0)
        if s2 > s1:
            one, two, s1, s2 = two, one, s2, s1
        runs = []
        for index, (team, score) in enumerate(((one, s1), (two, s2))):
            won = index == 0 and s1 > s2
            top_half = 0 < int(team.get('score_rank') or 0) <= half
            if index:
                runs.append((', ', False, False))
            runs.append((_team_label(team, names), won, top_half))
            runs.append((f' {_number(score)}', False, False))
        lines.append(runs)
    return lines


def _fact_lines(facts: dict | None, names: dict[str, str]) -> list[str]:
    """Headline facts with `{team:X}` tokens swapped for newsletter names.
    Mirrors qpfl.weekly_facts.render, which Vercel functions can't import."""
    lines = []
    for fact in (facts or {}).get('headline') or []:
        template = fact.get('template') if isinstance(fact, dict) else None
        if template:
            lines.append(
                re.sub(r'\{team:([^}]+)\}', lambda m: names.get(m.group(1), m.group(1)), template)
            )
    return lines


def _nfl_lines(week_data: dict | None) -> list[str]:
    """Primetime/international games and byes, reconstructed from the NFL
    opponent and kickoff stamped on every rostered player."""
    if not week_data:
        return ['Thursday Night Football: ', 'Monday Night Football: ', 'Bye Weeks: ']

    games: dict[tuple[str, str], datetime] = {}
    playing: set[str] = set()
    byes: set[str] = set()
    for team in week_data.get('teams') or []:
        for player in (team.get('roster') or []) + (team.get('taxi_squad') or []):
            nfl_team = player.get('nfl_team')
            if not nfl_team:
                continue
            if player.get('on_bye'):
                byes.add(nfl_team)
                continue
            opponent, kickoff = player.get('nfl_opponent'), player.get('kickoff')
            if not opponent or not kickoff:
                continue
            try:
                start = datetime.fromisoformat(kickoff).astimezone(EASTERN)
            except ValueError:
                continue
            away, home = (opponent, nfl_team) if player.get('nfl_is_home') else (nfl_team, opponent)
            games[(away, home)] = start
            playing.update((away, home))
    byes -= playing

    slots: dict[str, list[str]] = {}
    for (away, home), start in sorted(games.items(), key=lambda item: item[1]):
        day = start.strftime('%A')
        if day == 'Sunday':
            if start.hour < 12:
                label = 'International'
            elif start.hour >= 19:
                label = 'Sunday Night Football'
            else:
                continue
        elif day in ('Thursday', 'Monday'):
            label = f'{day} Night Football'
        else:
            label = day
        slots.setdefault(label, []).append(
            f'{NFL_TEAM_NAMES.get(away, away)} at {NFL_TEAM_NAMES.get(home, home)}'
        )

    order = [
        'Thursday Night Football',
        'Friday',
        'Saturday',
        'International',
        'Sunday Night Football',
        'Monday Night Football',
    ]
    labels = sorted(slots, key=lambda label: order.index(label) if label in order else len(order))
    lines = [f'{label}: {", ".join(slots[label])}' for label in labels]
    bye_names = sorted(NFL_TEAM_NAMES.get(team, team) for team in byes)
    lines.append(f'Bye Weeks: {", ".join(bye_names) if bye_names else "None"}')
    return lines


# --------------------------------------------------------------------------- #
# WordprocessingML
# --------------------------------------------------------------------------- #

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _run(text: str, bold=False, italic=False, underline=False, size: int | None = None) -> str:
    props = ''
    if bold:
        props += '<w:b/><w:bCs/>'
    if italic:
        props += '<w:i/><w:iCs/>'
    if underline:
        props += '<w:u w:val="single"/>'
    if size:
        props += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    rpr = f'<w:rPr>{props}</w:rPr>' if props else ''
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _paragraph(
    runs: str = '', style: str | None = None, center=False, indent=0, bullet=False
) -> str:
    props = ''
    if style:
        props += f'<w:pStyle w:val="{style}"/>'
    if bullet:
        props += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    if indent:
        props += f'<w:ind w:left="{indent}" w:firstLine="0"/>'
    if center:
        props += '<w:jc w:val="center"/>'
    ppr = f'<w:pPr>{props}</w:pPr>' if props else ''
    return f'<w:p>{ppr}{runs}</w:p>'


def _cell(text: str, width: int, header: bool) -> str:
    margins = ''.join(
        f'<w:{side} w:w="100" w:type="dxa"/>' for side in ('top', 'left', 'bottom', 'right')
    )
    paragraph = (
        '<w:p><w:pPr><w:spacing w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr>'
        f'{_run(text, bold=header, underline=header)}</w:p>'
    )
    return (
        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:tcMar>{margins}</w:tcMar></w:tcPr>'
        f'{paragraph}</w:tc>'
    )


def _standings_table(standings: list[dict]) -> str:
    borders = ''.join(
        f'<w:{edge} w:val="nil"/>'
        for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')
    )
    grid = ''.join(f'<w:gridCol w:w="{width}"/>' for _, width in STANDINGS_COLUMNS)
    rows = [
        '<w:tr><w:trPr><w:tblHeader/></w:trPr>'
        + ''.join(_cell(label, width, True) for label, width in STANDINGS_COLUMNS)
        + '</w:tr>'
    ]
    for team in standings:
        values = [
            f'{team.get("name", "")} - {team.get("abbrev", "")}',
            _number(team.get('rank_points')),
            _number(team.get('wins')),
            _number(team.get('top_half')),
            _number(team.get('points_for')),
            _number(team.get('points_against')),
        ]
        rows.append(
            '<w:tr><w:trPr><w:cantSplit/></w:trPr>'
            + ''.join(
                _cell(value, width, False)
                for value, (_, width) in zip(values, STANDINGS_COLUMNS, strict=True)
            )
            + '</w:tr>'
        )
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:jc w:val="center"/>'
        f'<w:tblBorders>{borders}</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>'
        f'<w:tblGrid>{grid}</w:tblGrid>{"".join(rows)}</w:tbl>'
    )


STYLES_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Cambria" w:hAnsi="Cambria" w:eastAsia="Cambria" w:cs="Cambria"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:bCs/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:u w:val="single"/></w:rPr></w:style>
</w:styles>"""

NUMBERING_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{W_NS}">
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="●"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""

CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOCUMENT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>"""


def _core_xml(title: str, generated_at: datetime) -> str:
    stamp = generated_at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{escape(title)}</dc:title><dc:creator>QPFL Commissioner Tools</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
        '</cp:coreProperties>'
    )


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


def newsletter_filename(sources: dict) -> str:
    return f'{sources["season"]} Standings Week {sources["upcoming_week"]}.docx'


def build_newsletter_document(sources: dict, generated_at: datetime | None = None) -> bytes:
    """Render the newsletter template from `load_newsletter_sources` output."""
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    local = generated_at.astimezone(EASTERN)

    season = sources['season']
    meta = sources['meta']
    names = _short_names(meta)
    results_week = sources['results_week']
    upcoming_week = sources['upcoming_week']
    volume = _roman(season - FIRST_SEASON + 1)

    body = [
        _paragraph(
            _run('QUARANTINE PERENNIAL FOOTBALL LEAGUE STANDINGS', size=32),
            style='Title',
        ),
        _paragraph(
            _run(
                f'Vol. {volume}, No. {max(results_week, 0)} - '
                f'{local.month}/{local.day}/{local.year}',
                bold=True,
                underline=True,
            ),
            center=True,
        ),
        _standings_table(sources['standings'].get('standings') or []),
        _paragraph(),
    ]

    # Results
    results_entry = _schedule_entry(meta, results_week)
    body.append(_paragraph(_run(f'Results, {_week_label(results_entry, results_week)}:')))
    result_lines = _result_lines(sources.get('results'), names)
    if not result_lines:
        body.append(_paragraph(_run('No final results yet.'), indent=720))
    for runs in result_lines:
        body.append(
            _paragraph(
                ''.join(_run(text, bold=bold, italic=italic) for text, bold, italic in runs),
                indent=720,
            )
        )
    body.append(_paragraph())

    # By the Numbers
    body.append(_paragraph(_run('By the Numbers'), style='Heading2'))
    fact_lines = _fact_lines(sources.get('facts'), names)
    if not fact_lines:
        body.append(_paragraph(_run('No notes generated this week.'), indent=720))
    for line in fact_lines:
        body.append(_paragraph(_run(line), bullet=True))
    body.append(_paragraph())

    # Next week's matchups
    body.append(_paragraph(_run('Schedule:')))
    upcoming_entry = _schedule_entry(meta, upcoming_week)
    if upcoming_entry:
        pairs = ', '.join(
            f'{_team_label(m.get("team1"), names)} vs {_team_label(m.get("team2"), names)}'
            for m in upcoming_entry.get('matchups') or []
        )
        body.append(_paragraph(_run(f'{_week_label(upcoming_entry, upcoming_week)}: {pairs}')))
    else:
        body.append(_paragraph(_run(f'Week {upcoming_week}: ')))
    body.append(_paragraph())

    # NFL
    for line in _nfl_lines(sources.get('upcoming')):
        body.append(_paragraph(_run(line)))
    body.append(_paragraph())

    # Handwritten sections
    body.append(_paragraph(_run('Reminders and Requests'), style='Heading2'))
    body.append(_paragraph(bullet=True))
    body.append(_paragraph())
    body.append(_paragraph(_run(f'Week {max(results_week, 0)} Recap'), style='Heading2'))
    body.extend(_paragraph() for _ in range(8))
    body.append(_paragraph(_run('Website Updates'), style='Heading2'))
    body.append(_paragraph(bullet=True))

    section = (
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>'
        f'{"".join(body)}{section}</w:body></w:document>'
    )

    title = f'{season} Standings Week {upcoming_week}'
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', CONTENT_TYPES_XML)
        archive.writestr('_rels/.rels', ROOT_RELS_XML)
        archive.writestr('docProps/core.xml', _core_xml(title, generated_at))
        archive.writestr('word/document.xml', document)
        archive.writestr('word/_rels/document.xml.rels', DOCUMENT_RELS_XML)
        archive.writestr('word/styles.xml', STYLES_XML)
        archive.writestr('word/numbering.xml', NUMBERING_XML)
    return buffer.getvalue()
