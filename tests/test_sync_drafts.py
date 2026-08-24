import json
from pathlib import Path

import pandas as pd

from scripts.sync_drafts_from_excel import parse_draft_sheet

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_2021_expansion_draft_is_parsed_from_its_one_off_layout():
    sheet = pd.read_excel(
        PROJECT_ROOT / 'Drafts.xlsx',
        sheet_name='2021 Expansion Draft',
        header=None,
    )

    drafts = parse_draft_sheet(sheet, '2021 Expansion Draft')

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft['type'] == 'expansion'
    assert [round_data['round'] for round_data in draft['rounds']] == [
        'Expansion Picks',
        'Free Agent Additions',
    ]
    assert len(draft['rounds'][0]['picks']) == 32
    assert len(draft['rounds'][1]['picks']) == 4
    assert draft['rounds'][0]['picks'][0] == {
        'pick': '1',
        'team': 'Tim/Spencer',
        'player': 'Leonard Fournette (TB)',
        'first_add_rights': 'Bill',
    }
    assert draft['rounds'][0]['picks'][30]['position'] == 'D/ST'


def test_2021_expansion_draft_is_in_canonical_and_published_data():
    for path in (
        PROJECT_ROOT / 'data' / 'drafts.json',
        PROJECT_ROOT / 'web' / 'data' / 'shared' / 'drafts.json',
    ):
        payload = json.loads(path.read_text(encoding='utf-8'))
        draft = next(item for item in payload['drafts'] if item['name'] == '2021 Expansion Draft')
        picks = [pick for round_data in draft['rounds'] for pick in round_data['picks']]

        assert draft['type'] == 'expansion'
        assert len(picks) == 36
        assert {pick['team'] for pick in picks} == {'Stephen', 'Tim/Spencer'}


def test_2025_midseason_seattle_pick_is_identified_as_offensive_line():
    sheet = pd.read_excel(
        PROJECT_ROOT / 'Drafts.xlsx',
        sheet_name='2025 Midseason Draft',
        header=None,
    )

    draft = parse_draft_sheet(sheet, '2025 Midseason Draft')[0]
    round_three = next(item for item in draft['rounds'] if item['round'] == '3')
    seattle = next(item for item in round_three['picks'] if item['pick'] == '7')

    assert seattle['player'] == 'Seattle Seahawks (SEA)'
    assert seattle['position'] == 'OL'

    round_one = next(item for item in draft['rounds'] if item['round'] == '1')
    patriots = next(item for item in round_one['picks'] if item['pick'] == '9')
    assert patriots['position'] == 'D/ST'

    for path in (
        PROJECT_ROOT / 'data' / 'drafts.json',
        PROJECT_ROOT / 'web' / 'data' / 'shared' / 'drafts.json',
    ):
        payload = json.loads(path.read_text(encoding='utf-8'))
        published = next(
            item for item in payload['drafts'] if item['name'] == '2025 Midseason Draft'
        )
        published_round = next(item for item in published['rounds'] if item['round'] == '3')
        published_seattle = next(
            item for item in published_round['picks'] if item['pick'] == '7'
        )
        assert published_seattle['position'] == 'OL'


def test_2025_offseason_atlanta_pick_is_identified_as_defense():
    sheet = pd.read_excel(
        PROJECT_ROOT / 'Drafts.xlsx',
        sheet_name='2025 Offseason Draft',
        header=None,
    )

    draft = parse_draft_sheet(sheet, '2025 Offseason Draft')[0]
    taxi_round_four = next(
        item for item in draft['rounds'] if item['round'] == 'TAXI Round 4'
    )
    atlanta = next(item for item in taxi_round_four['picks'] if item['pick'] == '1')

    assert atlanta['player'] == 'Atlanta Falcons (ATL)'
    assert atlanta['position'] == 'D/ST'

    for path in (
        PROJECT_ROOT / 'data' / 'drafts.json',
        PROJECT_ROOT / 'web' / 'data' / 'shared' / 'drafts.json',
    ):
        payload = json.loads(path.read_text(encoding='utf-8'))
        published = next(
            item for item in payload['drafts'] if item['name'] == '2025 Offseason Draft'
        )
        published_round = next(
            item for item in published['rounds'] if item['round'] == 'TAXI Round 4'
        )
        published_atlanta = next(
            item for item in published_round['picks'] if item['pick'] == '1'
        )
        assert published_atlanta['position'] == 'D/ST'
