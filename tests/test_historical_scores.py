import json
import re
from pathlib import Path

import openpyxl
import pytest

from qpfl.historical import historical_taxi_squad, load_historical_workbook

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPLETED_SEASONS = range(2020, 2026)
CHAMPIONSHIP_SCORE_ANCHORS = {
    2020: {'GSA': 75.0, 'CWR': 78.0},
    2021: {'RPA': 105.0, 'GSA': 106.0},
    2022: {'GSA': 86.0, 'CGK': 79.0},
    2023: {'CGK': 84.0, 'S/T': 100.0},
    2024: {'GSA': 110.0, 'CGK': 74.0},
    2025: {'CGK': 102.0, 'S/T': 92.0},
}
TEAM_CODE_ALIASES = {'SPY': 'AYP', 'T/S': 'S/T'}
SCORE_ROWS = {
    2020: (40, 41),
    2021: (40, 41),
    2022: (40,),
    2023: (40,),
    2024: (44,),
    2025: (45,),
}
ABBREV_ROWS = {2020: 5, 2021: 5, 2022: 4, 2023: 4, 2024: 4, 2025: 4}
STARTER_ROWS_2025 = [
    7,
    8,
    9,
    12,
    13,
    14,
    15,
    18,
    19,
    20,
    21,
    22,
    25,
    26,
    27,
    30,
    31,
    34,
    35,
    38,
    39,
    42,
    43,
]
PLAYER_SUFFIXES = {'ii', 'iii', 'iv', 'jr', 'sr'}


def load_json(path: Path) -> dict:
    with open(path) as file:
        return json.load(file)


def historical_player_key(week: int, team: str, group: str, player: dict) -> tuple:
    tokens = re.sub(r'[^a-z0-9]+', ' ', player['name'].lower()).split()
    while tokens and tokens[-1] in PLAYER_SUFFIXES:
        tokens.pop()
    position = 'D/ST' if player['position'] == 'DEF' else player['position']
    return week, team, group, position, tuple(tokens)


def official_sheet_names(season: int) -> dict[int, str]:
    if season <= 2021:
        playoff = 'Playoffs, Week 1' if season == 2020 else 'Playoffs, Round 1'
        return {
            **{week: f'Week {week}' for week in range(1, 15)},
            15: playoff,
            16: 'Super Bowl Week',
        }
    if season == 2022:
        written_weeks = {
            1: 'Week One',
            2: 'Week Two',
            3: 'Week Three',
            4: 'Week Four',
            5: 'Rivalry Week 5',
        }
        return {
            **written_weeks,
            **{week: f'Week {week}' for week in range(6, 16)},
            16: 'Semi-Finals',
            17: 'Championship Week 2.0',
        }
    if season <= 2024:
        return {
            **{week: f'Week {week}' for week in range(1, 16)},
            16: 'Semi-Finals',
            17: 'Championship',
        }
    return {week: f'Week {week}' for week in range(1, 18)}


def read_official_scores(season: int) -> dict[int, dict[str, float]]:
    workbook = openpyxl.load_workbook(
        PROJECT_ROOT / 'previous_seasons' / f'{season} Scores.xlsx', data_only=True
    )
    official = {}

    for week, sheet_name in official_sheet_names(season).items():
        worksheet = workbook[sheet_name]
        scores = {}
        team_count = 8 if season <= 2021 else 10
        for column in range(1, team_count * 2, 2):
            abbrev = str(worksheet.cell(ABBREV_ROWS[season], column).value or '').strip()
            abbrev = TEAM_CODE_ALIASES.get(abbrev, abbrev)
            if not abbrev:
                continue
            score = None
            for row in SCORE_ROWS[season]:
                value = worksheet.cell(row, column + 1).value
                if isinstance(value, (int, float)):
                    score = value
                    break
            if score is None:
                score = sum(
                    float(worksheet.cell(row, column + 1).value or 0)
                    for row in STARTER_ROWS_2025
                    if worksheet.cell(row, column).value and worksheet.cell(row, column).font.bold
                )
            scores[abbrev] = float(score)
        official[week] = scores

    workbook.close()
    return official


@pytest.fixture(scope='module')
def official_seasons():
    return {season: read_official_scores(season) for season in COMPLETED_SEASONS}


@pytest.mark.parametrize('season', COMPLETED_SEASONS)
def test_displayed_scores_match_official_workbooks(official_seasons, season):
    official = official_seasons[season]
    weeks_dir = PROJECT_ROOT / 'web' / 'data' / 'seasons' / str(season) / 'weeks'
    displayed = {
        int(path.stem.split('_')[1]): load_json(path) for path in weeks_dir.glob('week_*.json')
    }

    assert set(displayed) == set(official)
    for week, official_scores in official.items():
        displayed_teams = {team['abbrev']: team for team in displayed[week]['teams']}
        assert set(displayed_teams) == set(official_scores)
        ranks = {
            abbrev: 1 + sum(other > score for other in official_scores.values())
            for abbrev, score in official_scores.items()
        }

        for abbrev, official_score in official_scores.items():
            team = displayed_teams[abbrev]
            assert team['total_score'] == official_score, (
                f'{season} Week {week} {abbrev} does not match the official workbook'
            )
            assert team['score_rank'] == ranks[abbrev]
            assert (
                sum(
                    float(player.get('score') or 0.0)
                    for player in team.get('roster', [])
                    if player.get('starter')
                )
                == official_score
            )

        for matchup in displayed[week]['matchups']:
            for key in ('team1', 'team2'):
                team = matchup[key]
                assert team['total_score'] == displayed_teams[team['abbrev']]['total_score']
                assert team['score_rank'] == displayed_teams[team['abbrev']]['score_rank']


@pytest.mark.parametrize('season', COMPLETED_SEASONS)
def test_legacy_and_displayed_historical_scores_cannot_diverge(season):
    legacy = load_json(PROJECT_ROOT / 'web' / f'data_{season}.json')
    legacy_scores = {
        (week['week'], team['abbrev']): (team['total_score'], team['score_rank'])
        for week in legacy['weeks']
        for team in week['teams']
    }
    split_scores = {}
    weeks_dir = PROJECT_ROOT / 'web' / 'data' / 'seasons' / str(season) / 'weeks'
    for path in weeks_dir.glob('week_*.json'):
        week = load_json(path)
        split_scores.update(
            {
                (week['week'], team['abbrev']): (team['total_score'], team['score_rank'])
                for team in week['teams']
            }
        )

    assert split_scores == legacy_scores


@pytest.mark.parametrize('season', COMPLETED_SEASONS)
def test_exported_team_names_do_not_include_playoff_seeds(season):
    seed_prefix = re.compile(r'^\(\d+\)\s*')
    legacy = load_json(PROJECT_ROOT / 'web' / f'data_{season}.json')
    names = [team['name'] for team in legacy.get('teams', [])]

    for week in legacy['weeks']:
        names.extend(team['name'] for team in week['teams'])

    season_dir = PROJECT_ROOT / 'web' / 'data' / 'seasons' / str(season)
    meta = load_json(season_dir / 'meta.json')
    names.extend(team['name'] for team in meta.get('teams', []))
    for path in (season_dir / 'weeks').glob('week_*.json'):
        week = load_json(path)
        names.extend(team['name'] for team in week['teams'])

    assert not [name for name in names if seed_prefix.match(name)]


@pytest.mark.parametrize('season', COMPLETED_SEASONS)
def test_backup_scores_match_the_historical_archive(season):
    legacy = load_json(PROJECT_ROOT / 'web' / f'data_{season}.json')
    legacy_players = {
        historical_player_key(week['week'], team['abbrev'], group, player): player.get('score')
        for week in legacy['weeks']
        for team in week['teams']
        for group in ('roster', 'taxi_squad')
        for player in team.get(group, [])
    }
    displayed_players = {}
    weeks_dir = PROJECT_ROOT / 'web' / 'data' / 'seasons' / str(season) / 'weeks'
    for path in weeks_dir.glob('week_*.json'):
        week = load_json(path)
        displayed_players.update(
            {
                historical_player_key(week['week'], team['abbrev'], group, player): player.get(
                    'score'
                )
                for team in week['teams']
                for group in ('roster', 'taxi_squad')
                for player in team.get(group, [])
            }
        )

    assert displayed_players == legacy_players


def test_2021_backup_season_totals_are_preserved():
    weeks_dir = PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2021' / 'weeks'
    totals = {'Russell Wilson': 0.0, 'Joe Burrow': 0.0}
    for path in weeks_dir.glob('week_*.json'):
        week = load_json(path)
        gsa = next(team for team in week['teams'] if team['abbrev'] == 'GSA')
        for player in gsa['roster']:
            if player['name'] in totals:
                totals[player['name']] += float(player.get('score') or 0.0)

    assert totals == {'Russell Wilson': 218.0, 'Joe Burrow': 320.0}


def test_2024_displayed_rosters_match_the_workbook_layout():
    official = load_historical_workbook(
        PROJECT_ROOT / 'previous_seasons' / '2024 Scores.xlsx', 2024
    )
    for week, source_week in official.items():
        displayed = load_json(
            PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2024' / 'weeks' / f'week_{week}.json'
        )
        displayed_teams = {team['abbrev']: team for team in displayed['teams']}

        for abbrev, source_team in source_week['teams'].items():
            source_positions = [player['position'] for player in source_team['roster']]
            displayed_positions = [
                player['position'] for player in displayed_teams[abbrev]['roster']
            ]
            assert displayed_positions == source_positions


def test_historical_taxi_squad_follows_labels_when_rows_drift():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    # 2022 roster ends at row 38; this week's taxi block starts a row lower than usual.
    cells = {
        44: 'QB',
        45: 'Joe Flacco (IND)',
        46: 'RB',
        47: 'Jaylen Wright (MIA)',
        48: 'D/ST',
        49: 'Philadelphia Eagles (PHI) D/ST',
    }
    for row, value in cells.items():
        sheet.cell(row=row, column=1, value=value)

    assert historical_taxi_squad(sheet, 1, 2022) == [
        {'name': 'Joe Flacco', 'nfl_team': 'IND', 'position': 'QB'},
        {'name': 'Jaylen Wright', 'nfl_team': 'MIA', 'position': 'RB'},
        {'name': 'Philadelphia Eagles', 'nfl_team': 'PHI', 'position': 'D/ST'},
    ]


@pytest.mark.parametrize('season', [2022, 2024])
def test_displayed_taxi_squads_are_well_formed(season):
    labels = {'QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'DEF', 'HC', 'OL'}
    for path in (PROJECT_ROOT / 'web' / 'data' / 'seasons' / str(season) / 'weeks').glob(
        'week_*.json'
    ):
        for team in load_json(path)['teams']:
            active = {(player['name'], player['position']) for player in team['roster']}
            for player in team.get('taxi_squad', []):
                assert player['name'] not in labels, (path.name, team['abbrev'], player)
                assert player['position'] in labels, (path.name, team['abbrev'], player)
                assert (player['name'], player['position']) not in active, (
                    path.name,
                    team['abbrev'],
                    player,
                )


def test_2024_stafford_is_off_taxi_after_his_week_12_activation():
    week = load_json(PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2024' / 'weeks' / 'week_12.json')
    teams = {team['abbrev']: team for team in week['teams']}
    assert 'Matthew Stafford' not in {player['name'] for player in teams['RPA']['taxi_squad']}
    assert 'Joe Flacco' in {player['name'] for player in teams['GSA']['taxi_squad']}


def test_official_workbooks_are_anchored_to_known_championship_scores(official_seasons):
    for season, expected in CHAMPIONSHIP_SCORE_ANCHORS.items():
        championship_week = max(official_seasons[season])
        scores = official_seasons[season][championship_week]
        assert {abbrev: scores[abbrev] for abbrev in expected} == expected


def test_shortened_names_only_match_a_player_whose_first_name_and_team_fit():
    """A shortened workbook name must not take over a different player's entry."""
    from scripts.fix_historical_scores import find_player

    roster = [
        {'name': 'Antonio Brown', 'position': 'WR', 'nfl_team': 'TB'},
        {'name': 'Damien Williams', 'position': 'RB', 'nfl_team': 'CHI'},
        {'name': 'Todd Gurley', 'position': 'RB', 'nfl_team': 'ATL'},
        {'name': 'Matt Gay', 'position': 'K', 'nfl_team': 'LA'},
    ]

    def match(name, position, nfl_team=''):
        player = find_player(roster, name, position, nfl_team)
        return player and player['name']

    # 2021: CWR/SLS's "A.J. Brown" and WJK's "Da. Williams (KC)" were stored
    # as Antonio Brown and Damien Williams.
    assert match('A.J. Brown', 'WR', 'TEN') is None
    assert match('Da. Williams', 'RB', 'KC') is None
    assert match('Jav. Williams', 'RB', 'DEN') is None
    # Genuine shortenings still resolve, suffixes and the Rams' two codes included.
    assert match('A. Brown', 'WR', 'TB') == 'Antonio Brown'
    assert match('T. Gurley III', 'RB', 'ATL') == 'Todd Gurley'
    assert match('M. Gay', 'K', 'LAR') == 'Matt Gay'
    assert match('D. Williams', 'RB') == 'Damien Williams'


def test_2021_mislabeled_receivers_and_backs_keep_their_own_names():
    weeks = {
        week: json.loads(
            (
                PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2021' / 'weeks' / f'week_{week}.json'
            ).read_text(encoding='utf-8')
        )
        for week in (5, 11, 14)
    }

    def names(week, abbrev, group='roster'):
        team = next(team for team in weeks[week]['teams'] if team['abbrev'] == abbrev)
        return {player['name'] for player in team.get(group, [])}

    assert 'A.J. Brown' in names(5, 'CWR/SLS')
    assert 'Antonio Brown' not in names(14, 'CWR/SLS')
    assert 'Darrel Williams' in names(11, 'WJK')
    assert 'Javonte Williams' in names(14, 'JRW')
    assert 'Damien Williams' not in names(14, 'JRW') | names(14, 'WJK')


@pytest.mark.parametrize(
    ('season', 'week', 'abbrev', 'group', 'right', 'wrong'),
    [
        (2020, 1, 'JRW', 'roster', 'Jonnu Smith', 'Lee Smith'),
        (2020, 1, 'WJK', 'roster', 'David Johnson', 'Malcolm Johnson'),
        (2020, 1, 'WJK', 'roster', 'DJ Moore', 'Chris Moore'),
        (2021, 1, 'AYP', 'roster', 'DeVonta Smith', 'Devin Smith'),
        (2021, 8, 'CGK/SRY', 'roster', 'Deebo Samuel', 'Curtis Samuel'),
        (2021, 1, 'CGK/SRY', 'taxi_squad', 'Diontae Johnson', 'Marcus Johnson'),
        (2020, 1, 'MPA', 'taxi_squad', 'Doug Marrone', 'D. Marrone'),
    ],
)
def test_audited_historical_rows_name_the_workbook_player(
    season, week, abbrev, group, right, wrong
):
    """Rows the old last-name fallback had given another player's name."""
    path = PROJECT_ROOT / 'web' / 'data' / 'seasons' / str(season) / 'weeks' / f'week_{week}.json'
    team = next(
        team
        for team in json.loads(path.read_text(encoding='utf-8'))['teams']
        if team['abbrev'] == abbrev
    )
    names = {player['name'] for player in team.get(group, [])}
    assert right in names
    assert wrong not in names


def test_2020_taxi_squads_hold_no_sheet_labels():
    path = PROJECT_ROOT / 'web' / 'data' / 'seasons' / '2020' / 'weeks' / 'week_16.json'
    taxi = [
        player
        for team in json.loads(path.read_text(encoding='utf-8'))['teams']
        for player in team.get('taxi_squad', [])
    ]
    assert not {player['name'] for player in taxi} & {'Joe', 'Bocki', '2', '4'}
