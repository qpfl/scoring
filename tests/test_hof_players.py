from qpfl.weekly_facts import PLAYOFFS, REGULAR, PlayerGame, TeamGame
from scripts import hof_players, hof_records


def _player(season, week, abbrev, name, position, score, starter=True, bracket=REGULAR):
    return PlayerGame(
        season=season,
        week=week,
        week_label=f'Week {week}',
        bracket=bracket,
        player_key=name.lower(),
        name=name,
        position=position,
        abbrev=abbrev,
        franchises=(abbrev,),
        score=score,
        starter=starter,
    )


def _title_game(season, week, abbrev, opp):
    return TeamGame(
        season=season,
        week=week,
        week_label='Championship Week',
        bracket=PLAYOFFS,
        abbrev=abbrev,
        franchises=(abbrev,),
        score=100,
        opp_abbrev=opp,
        opp_franchises=(opp,),
        opp_score=90,
        title_game=True,
    )


def _honors(players, team_games=(), champions=None, manual=None, names=None):
    return hof_players.build_player_honors(
        list(team_games),
        players,
        champions or {},
        manual or {},
        lambda key: key,
        lambda name, position: name.lower(),
        (names or {}).get,
    )


def test_season_honors_fill_each_lineup_spot_and_crown_position_leaders():
    players = [
        _player(2024, 1, 'GSA', 'Allen', 'QB', 30),
        _player(2024, 1, 'GSA', 'Henry', 'RB', 20),
        _player(2024, 1, 'GSA', 'Cook', 'RB', 15),
        _player(2024, 1, 'RPA', 'Burrow', 'QB', 25),
        _player(2024, 1, 'RPA', 'Bijan', 'RB', 25),
        _player(2024, 1, 'RPA', 'Hall', 'RB', 5),
        # Bench points don't count toward honors.
        _player(2024, 1, 'RPA', 'Benched', 'RB', 40, starter=False),
        # No champion yet: leaderboards only, no awards.
        _player(2025, 1, 'GSA', 'Allen', 'QB', 50),
    ]
    honors, awards = _honors(players, champions={2024: 'GSA'})

    team = honors['all_qpfl']['2024']
    assert [(r['slot'], r['player']) for r in team['first_team']] == [
        ('QB', 'Allen'),
        ('RB', 'Bijan'),
        ('RB', 'Henry'),
    ]
    assert [(r['slot'], r['player']) for r in team['second_team']] == [
        ('QB', 'Burrow'),
        ('RB', 'Cook'),
        ('RB', 'Hall'),
    ]
    assert [(r['position'], r['player']) for r in honors['position_leaders']['2024']] == [
        ('QB', 'Allen'),
        ('RB', 'Bijan'),
    ]
    assert '2025' not in honors['all_qpfl']
    assert honors['leaderboards']['seasons']['2025']['ALL'][0]['player'] == 'Allen'
    assert awards['allen'] == [
        {'year': 2024, 'title': 'Top QB'},
        {'year': 2024, 'title': 'First-Team All-QPFL'},
    ]
    assert awards['henry'] == [{'year': 2024, 'title': 'First-Team All-QPFL'}]
    assert awards['burrow'] == [{'year': 2024, 'title': 'Second-Team All-QPFL'}]
    assert 'benched' not in awards

    career = honors['leaderboards']['career']['ALL'][0]
    assert (career['player'], career['points'], career['starts'], career['team']) == (
        'Allen',
        80,
        2,
        'GSA',
    )


def test_rings_go_to_the_champions_whole_title_game_roster():
    players = [
        _player(2024, 17, 'GSA', 'Allen', 'QB', 30, bracket=PLAYOFFS),
        _player(2024, 17, 'GSA', 'Benched', 'QB', 10, starter=False, bracket=PLAYOFFS),
        _player(2024, 17, 'RPA', 'Burrow', 'QB', 25, bracket=PLAYOFFS),
    ]
    games = [_title_game(2024, 17, 'GSA', 'RPA'), _title_game(2024, 17, 'RPA', 'GSA')]
    honors, awards = _honors(players, games, champions={2024: 'GSA'}, names={'allen': 'Josh Allen'})

    assert [(r['player'], r['rings'], r['seasons']) for r in honors['rings']] == [
        ('Benched', 1, [2024]),
        ('Josh Allen', 1, [2024]),
    ]
    # A bench player on the champion's roster gets a ring too.
    assert {'year': 2024, 'title': 'QPFL Champion'} in awards['benched']
    assert {'year': 2024, 'title': 'QPFL Champion'} in awards['allen']
    assert 'burrow' not in {r['profile_key'] for r in honors['rings']}


def test_manual_mvps_and_awards_reach_the_players_profile():
    manual = {
        'mvps': [{'year': 2023, 'player': 'Kelce', 'position': 'TE', 'team': 'CGK'}],
        'player_awards': [
            {'year': 2024, 'player': 'Allen', 'position': 'QB', 'title': 'Comeback Player'}
        ],
    }
    honors, awards = _honors([], manual=manual)

    assert honors['mvps'][0]['profile_key'] == 'kelce'
    assert awards['kelce'] == [{'year': 2023, 'title': 'QPFL MVP'}]
    assert awards['allen'] == [{'year': 2024, 'title': 'Comeback Player'}]


def test_all_qpfl_selections_tally_first_and_second_teams_across_seasons():
    players = [
        _player(2023, 1, 'GSA', 'Allen', 'QB', 30),
        _player(2023, 1, 'RPA', 'Burrow', 'QB', 25),
        _player(2024, 1, 'GSA', 'Allen', 'QB', 20),
        _player(2024, 1, 'RPA', 'Burrow', 'QB', 28),
        _player(2024, 1, 'CGK', 'Mahomes', 'QB', 10),
    ]
    honors, _ = _honors(players, champions={2023: 'GSA', 2024: 'RPA'})

    tally = {
        r['player']: (r['first_team'], r['second_team'], r['team'])
        for r in honors['all_qpfl_selections']
    }
    assert tally == {
        'Allen': ([2023], [2024], 'GSA'),
        'Burrow': ([2024], [2023], 'RPA'),
    }

    groups = {
        g['id']: g
        for g in hof_records.all_qpfl_record_groups(
            honors['all_qpfl_selections'], lambda team, season: f'{team} owner'
        )
    }
    first = groups['player-career-all-qpfl-first-team']
    assert [(e['player'], e['value'], e['years']) for e in first['entries']] == [
        ('Allen', 1, [2023]),
        ('Burrow', 1, [2024]),
    ]
    total = groups['player-career-all-qpfl']['entries']
    assert [(e['player'], e['value'], e['years']) for e in total] == [
        ('Allen', 2, [2023, 2024]),
        ('Burrow', 2, [2023, 2024]),
    ]
    assert total[0]['owner'] == 'GSA owner'


def test_franchise_lineup_takes_each_players_best_qualifying_season():
    def games(season, abbrev, name, position, scores):
        return [_player(season, w, abbrev, name, position, s) for w, s in enumerate(scores, 1)]

    players = [
        # GSA plays four weeks a season.
        *games(2023, 'GSA', 'Mahomes', 'QB', [20, 20, 20, 20]),
        *games(2024, 'GSA', 'Mahomes', 'QB', [30, 30, 30, 30]),
        *games(2024, 'CGK', 'Allen', 'QB', [25, 25, 25, 25]),
        # Two huge starts out of four isn't most of a season.
        *games(2023, 'GSA', 'Rental', 'RB', [60, 60]),
        *games(2023, 'GSA', 'Henry', 'RB', [10, 10, 10]),
        *games(2024, 'GSA', 'Cook', 'RB', [5, 5, 5, 5]),
        *games(2024, 'GSA', 'Bijan', 'RB', [15, 15, 15, 15]),
        # A season still in progress doesn't count.
        *games(2025, 'GSA', 'Allen', 'QB', [50, 50, 50, 50]),
        # Another franchise keeps its own lineup.
        *games(2024, 'RPA', 'Burrow', 'QB', [10, 10, 10, 10]),
    ]
    honors, _ = _honors(players, champions={2023: 'GSA', 2024: 'RPA'})
    lineups = honors['franchise_lineups']

    assert [(r['slot'], r['player'], r['season'], r['points']) for r in lineups['GSA']] == [
        ('QB', 'Mahomes', 2024, 120),
        ('RB', 'Bijan', 2024, 60),
        ('RB', 'Henry', 2023, 30),
    ]
    assert lineups['GSA'][2]['team_games'] == 4
    assert [r['player'] for r in lineups['RPA']] == ['Burrow']


def test_lineup_standings_rank_lineups_by_summed_ppg():
    def row(points, starts):
        return {'points': points, 'starts': starts}

    standings = hof_players.lineup_standings(
        {
            'GSA': [row(300, 15), row(100, 10)],  # 20 + 10
            'RPA': [row(150, 10), row(150, 10)],  # 15 + 15, tied
            'CGK': [row(400, 10)],  # 40
            'AYP': [],
        }
    )
    assert standings == {
        'CGK': {'ppg': 40.0, 'rank': 1, 'of': 3},
        'GSA': {'ppg': 30.0, 'rank': 2, 'of': 3},
        'RPA': {'ppg': 30.0, 'rank': 2, 'of': 3},
    }
