from scripts import hof_records


def _player(name, position, score, starter=True):
    return {'name': name, 'position': position, 'score': score, 'starter': starter}


def _team(abbrev, score, roster=None, name=None):
    return {
        'abbrev': abbrev,
        'name': name or f'{abbrev} Team',
        'total_score': score,
        'roster': roster or [],
    }


def _week(number, *matchups):
    return {
        'week': number,
        'has_scores': True,
        'matchups': [{'team1': a, 'team2': b} for a, b in matchups],
    }


def _season(season, *weeks, complete=True):
    return {'season': season, 'weeks': list(weeks), 'regular_season_complete': complete}


def _owner(abbrev, season):
    return f'Owner {abbrev}'


def _groups(all_seasons, profiles=None):
    book = hof_records.build_record_book(all_seasons, _owner, profiles)
    return {group['id']: group for group in book['groups']}


def test_team_game_records_rank_ties_and_name_the_game():
    groups = _groups(
        [
            _season(
                2024,
                _week(1, (_team('GSA', 120, name='Beermeister'), _team('RPA', 80))),
                _week(2, (_team('GSA', 90), _team('RPA', 120))),
            )
        ]
    )

    top = groups['team-game-most-points']['entries']
    assert [(e['rank'], e['team'], e['value']) for e in top[:2]] == [
        (1, 'GSA', 120),
        (1, 'RPA', 120),
    ]
    first = top[0]
    assert first['team_name'] == 'Beermeister'
    assert first['owner'] == 'Owner GSA'
    assert (first['season'], first['week'], first['week_label']) == (2024, 1, 'Week 1')
    assert first['opponent'] == 'RPA'

    assert groups['team-game-most-points-loss']['entries'][0]['value'] == 90
    assert groups['team-game-fewest-points-win']['entries'][0]['value'] == 120
    assert groups['team-game-biggest-win']['entries'][0]['value'] == 40


def test_win_streaks_carry_across_seasons_and_credit_the_owner_identity():
    groups = _groups(
        [
            _season(
                2021,
                _week(13, (_team('CGK/SRY', 100), _team('RPA', 80))),
                _week(14, (_team('CGK/SRY', 100), _team('RPA', 80))),
            ),
            _season(2022, _week(1, (_team('CGK', 100), _team('RPA', 80)))),
        ]
    )

    streak = groups['team-longest-win-streak']['entries'][0]
    assert streak['value'] == 3
    assert streak['owner_code'] == 'CGK'
    assert streak['start'] == {
        'season': 2021,
        'week': 13,
        'week_label': 'Week 13',
        'team': 'CGK/SRY',
    }
    assert groups['team-longest-losing-streak']['entries'][0]['team'] == 'RPA'


def test_bench_points_need_every_player_scored():
    full = [
        _player('Josh Allen', 'QB', 30),
        _player('Jalen Hurts', 'QB', 40, starter=False),
    ]
    missing = [
        _player('Joe Burrow', 'QB', 10),
        {'name': 'Dak Prescott', 'position': 'QB', 'starter': False},
    ]
    groups = _groups([_season(2024, _week(1, (_team('GSA', 30, full), _team('RPA', 10, missing))))])

    entries = groups['team-game-bench-points']['entries']
    assert [(e['team'], e['value'], e['optimal']) for e in entries] == [('GSA', 10, 40)]
    bench = groups['player-game-bench-points']['entries'][0]
    assert (bench['player'], bench['value']) == ('Jalen Hurts', 40)


def test_season_records_skip_unfinished_regular_seasons():
    groups = _groups(
        [
            _season(2024, _week(1, (_team('GSA', 100), _team('RPA', 90)))),
            _season(2026, _week(1, (_team('GSA', 150), _team('RPA', 90))), complete=False),
        ]
    )

    assert {e['season'] for e in groups['team-season-most-points']['entries']} == {2024}
    # Game records still count the live season.
    assert groups['team-game-most-points']['entries'][0]['season'] == 2026


def test_player_totals_follow_career_profile_aliases():
    roster_2023 = [_player('Patrick Mahomes II', 'QB', 30)]
    roster_2024 = [_player('Patrick Mahomes', 'QB', 25)]
    profiles = {
        'Patrick Mahomes': {
            'profile_key': 'patrick mahomes',
            'position': 'QB',
            'aliases': ['Patrick Mahomes', 'Patrick Mahomes II'],
        }
    }
    groups = _groups(
        [
            _season(2023, _week(1, (_team('GSA', 30, roster_2023), _team('RPA', 10)))),
            _season(2024, _week(1, (_team('GSA', 25, roster_2024), _team('RPA', 10)))),
        ],
        profiles,
    )

    career = groups['player-career-most-points']['entries'][0]
    assert (career['profile_key'], career['value'], career['starts']) == ('patrick mahomes', 55, 2)
    assert groups['player-career-most-points-qb']['position'] == 'QB'
    season = groups['player-season-most-points']['entries'][0]
    assert (season['season'], season['value']) == (2023, 30)


def test_league_records_count_each_game_once():
    groups = _groups(
        [
            _season(
                2024,
                _week(
                    1, (_team('GSA', 100), _team('RPA', 100)), (_team('CGK', 90), _team('AYP', 70))
                ),
            )
        ]
    )

    closest = groups['league-closest-game']['entries']
    assert [(e['value'], e['team'], e['opponent']) for e in closest] == [
        (0, 'GSA', 'RPA'),
        (20, 'CGK', 'AYP'),
    ]
    assert groups['league-highest-week']['entries'][0]['value'] == 360
    assert groups['league-highest-combined']['entries'][0]['value'] == 200
