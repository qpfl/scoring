"""Tests for the commissioner's weekly newsletter template (.docx)."""

import base64
import re
import zipfile
from datetime import datetime, timezone
from io import BytesIO

from api.newsletter_export import (
    build_newsletter_document,
    load_newsletter_sources,
    newsletter_filename,
)
from tests.test_api import FakeRepo, transaction

BASE = 'web/data/seasons/2026'


def _player(nfl_team, opponent=None, home=False, kickoff=None, on_bye=False):
    return {
        'name': f'{nfl_team} Guy',
        'nfl_team': nfl_team,
        'nfl_opponent': opponent,
        'nfl_is_home': home,
        'kickoff': kickoff,
        'on_bye': on_bye,
    }


def _team(abbrev, score, rank, roster=()):
    return {'abbrev': abbrev, 'total_score': score, 'score_rank': rank, 'roster': list(roster)}


def _files():
    meta = {
        'current_week': 4,
        'teams': [
            {'abbrev': 'GSA', 'owner': 'Griffin Ansel'},
            {'abbrev': 'CGK', 'owner': 'Connor Kaminska'},
            {'abbrev': 'S/T', 'owner': 'Spencer Yoder & Tim Grazier'},
            {'abbrev': 'NEW', 'owner': 'Pat Doe & Sam Roe'},
        ],
        'schedule': [
            {
                'week': 3,
                'matchups': [{'team1': 'GSA', 'team2': 'S/T'}, {'team1': 'CGK', 'team2': 'NEW'}],
            },
            {
                'week': 4,
                'is_rivalry': True,
                'matchups': [{'team1': 'GSA', 'team2': 'CGK'}, {'team1': 'S/T', 'team2': 'NEW'}],
            },
        ],
    }
    standings = {
        'standings': [
            {
                'name': 'Drunk Darts & Co',
                'abbrev': 'S/T',
                'rank_points': 4.5,
                'wins': 3,
                'top_half': 3.0,
                'points_for': 353.0,
                'points_against': 271.0,
            },
            {
                'name': 'Extra CroMahomes',
                'abbrev': 'GSA',
                'rank_points': 3.0,
                'wins': 2,
                'top_half': 2.0,
                'points_for': 340.0,
                'points_against': 278.0,
            },
        ]
    }
    week_3 = {
        'week': 3,
        'has_scores': True,
        'games_final': True,
        'teams': [],
        'matchups': [
            {'team1': _team('GSA', 112, 2), 'team2': _team('S/T', 122, 1)},
            {'team1': _team('CGK', 60, 4), 'team2': _team('NEW', 68, 3)},
        ],
    }
    week_3['teams'] = [side for m in week_3['matchups'] for side in (m['team1'], m['team2'])]
    week_4 = {
        'week': 4,
        'has_scores': False,
        'games_final': False,
        'teams': [
            _team(
                'GSA',
                0,
                0,
                [
                    # Thursday 8:15 PM ET
                    _player('PIT', 'CLE', False, '2026-10-02T00:15:00+00:00'),
                    _player('CLE', 'PIT', True, '2026-10-02T00:15:00+00:00'),
                    # Sunday 9:30 AM ET abroad
                    _player('IND', 'WAS', False, '2026-10-04T13:30:00+00:00'),
                    # Sunday 1 PM ET - not called out
                    _player('KC', 'LV', False, '2026-10-04T17:00:00+00:00'),
                    # Sunday night, Monday night
                    _player('DET', 'CAR', False, '2026-10-05T00:20:00+00:00'),
                    _player('NO', 'ATL', True, '2026-10-06T00:15:00+00:00'),
                    _player('JAX', on_bye=True),
                ],
            )
        ],
    }
    return {
        f'{BASE}/meta.json': meta,
        f'{BASE}/standings.json': standings,
        f'{BASE}/weeks/week_3.json': week_3,
        f'{BASE}/weeks/week_4.json': week_4,
    }


def _text(content: bytes) -> tuple[str, str]:
    xml = zipfile.ZipFile(BytesIO(content)).read('word/document.xml').decode('utf-8')
    text = re.sub(r'<[^>]+>', '', re.sub(r'</w:p>', '\n', xml))
    return xml, text


def _sources(files=None):
    files = _files() if files is None else files
    return load_newsletter_sources(files.get, 2026)


def test_results_week_is_the_latest_final_week_and_preview_is_the_next():
    sources = _sources()
    assert sources['results_week'] == 3
    assert sources['upcoming_week'] == 4
    assert newsletter_filename(sources) == '2026 Standings Week 4.docx'

    files = _files()
    files[f'{BASE}/weeks/week_4.json'].update(has_scores=True, games_final=True)
    sources = _sources(files)
    assert sources['results_week'] == 4
    assert sources['upcoming'] is None  # week 5 not published yet


def test_newsletter_lays_out_standings_results_schedule_and_nfl():
    content = build_newsletter_document(
        _sources(), generated_at=datetime(2026, 9, 29, 14, tzinfo=timezone.utc)
    )
    xml, text = _text(content)

    assert 'QUARANTINE PERENNIAL FOOTBALL LEAGUE STANDINGS' in text
    assert 'Vol. VII, No. 3 - 9/29/2026' in text
    assert 'Drunk Darts &amp; Co - S/T\n4.5\n3\n3\n353\n271' in text  # still XML-escaped
    assert 'Extra CroMahomes - GSA\n3\n2\n2\n340\n278' in text

    # Winner first; nickname overrides, with owner first names as the fallback.
    assert 'Results, Week 3:\nSpencer/Tim 122, Griff 112\nPat/Sam 68, Kaminska 60\n' in text
    assert 'Rivalry Week 4: Griff vs Kaminska, Spencer/Tim vs Pat/Sam' in text

    assert 'Thursday Night Football: Pittsburgh Steelers at Cleveland Browns' in text
    assert 'International: Indianapolis Colts at Washington Commanders' in text
    assert 'Sunday Night Football: Detroit Lions at Carolina Panthers' in text
    assert 'Monday Night Football: Atlanta Falcons at New Orleans Saints' in text
    assert 'Kansas City' not in text
    assert 'Bye Weeks: Jacksonville Jaguars' in text

    for heading in ('Reminders and Requests', 'Week 3 Recap', 'Website Updates'):
        assert heading in text


def test_results_bold_the_winner_and_italicize_top_half_scores():
    xml, _ = _text(build_newsletter_document(_sources()))

    def run_props(name):
        runs = [run for run in xml.split('<w:r>') if f'>{name}</w:t>' in run]
        assert len(runs) == 1, name
        return runs[0].split('<w:t ')[0]

    assert '<w:b/>' in run_props('Spencer/Tim') and '<w:i/>' in run_props('Spencer/Tim')
    assert '<w:b/>' not in run_props('Griff') and '<w:i/>' in run_props('Griff')
    assert '<w:b/>' in run_props('Pat/Sam') and '<w:i/>' not in run_props('Pat/Sam')
    assert run_props('Kaminska') == ''


def test_missing_preview_week_leaves_nfl_placeholders():
    files = _files()
    del files[f'{BASE}/weeks/week_4.json']
    _, text = _text(build_newsletter_document(_sources(files)))

    assert 'Thursday Night Football: \nMonday Night Football: \nBye Weeks: \n' in text


def test_by_the_numbers_lists_headline_facts_with_newsletter_names():
    files = _files()
    files[f'{BASE}/facts/week_3.json'] = {
        'season': 2026,
        'week': 3,
        'headline': [
            {'template': "{team:S/T}'s 122 was the most points since Week 9, 2024."},
            {'template': '{team:GSA} has lost 4 straight to {team:CGK}.'},
        ],
        'all': [],
    }
    sources = _sources(files)
    assert sources['facts']['week'] == 3
    xml, text = _text(build_newsletter_document(sources))

    assert (
        "By the Numbers\nSpencer/Tim's 122 was the most points since Week 9, 2024.\n"
        'Griff has lost 4 straight to Kaminska.\n'
    ) in text
    assert text.index('By the Numbers') < text.index('Schedule:')
    assert xml.count('<w:numId w:val="1"/>') == 4  # two facts + two template bullets


def test_missing_facts_file_leaves_a_placeholder():
    sources = _sources()
    assert sources['facts'] is None
    _, text = _text(build_newsletter_document(sources))

    assert 'By the Numbers\nNo notes generated this week.\n' in text


def test_newsletter_is_a_valid_word_package():
    archive = zipfile.ZipFile(BytesIO(build_newsletter_document(_sources())))
    names = set(archive.namelist())
    assert {'[Content_Types].xml', '_rels/.rels', 'word/document.xml', 'word/styles.xml'} <= names
    assert 'wordprocessingml.document.main+xml' in archive.read('[Content_Types].xml').decode()


def test_admin_newsletter_download_is_commissioner_only_and_read_only(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = FakeRepo(_files())
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {'team': 'CGK', 'password': 'pw', 'admin_action': 'download_newsletter'}
    )
    assert status in (401, 403)
    assert 'content_base64' not in body

    status, body = transaction.handle_admin_adjust(
        {'team': 'GSA', 'password': 'pw', 'admin_action': 'download_newsletter'}
    )
    assert status == 200, body
    assert body['filename'] == '2026 Standings Week 4.docx'
    assert body['mime_type'].endswith('wordprocessingml.document')
    _, text = _text(base64.b64decode(body['content_base64']))
    assert 'Results, Week 3:' in text
    assert repo.put_log == []
