from qpfl.weekly_facts import PLAYOFFS, REGULAR, PlayerGame, TeamGame
from scripts import hof_players


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

    assert [(r['slot'], r['player']) for r in honors['all_qpfl']['2024']] == [
        ('QB', 'Allen'),
        ('RB', 'Bijan'),
        ('RB', 'Henry'),
    ]
    assert [(r['position'], r['player']) for r in honors['position_leaders']['2024']] == [
        ('QB', 'Allen'),
        ('RB', 'Bijan'),
    ]
    assert '2025' not in honors['all_qpfl']
    assert honors['leaderboards']['seasons']['2025']['ALL'][0]['player'] == 'Allen'
    assert awards['allen'] == [{'year': 2024, 'title': 'Top QB'}]
    assert {'year': 2024, 'title': 'All-QPFL'} in awards['henry']
    assert 'benched' not in awards

    career = honors['leaderboards']['career']['ALL'][0]
    assert (career['player'], career['points'], career['starts'], career['team']) == (
        'Allen',
        80,
        2,
        'GSA',
    )


def test_rings_go_to_the_champions_title_game_starters():
    players = [
        _player(2024, 17, 'GSA', 'Allen', 'QB', 30, bracket=PLAYOFFS),
        _player(2024, 17, 'GSA', 'Benched', 'QB', 10, starter=False, bracket=PLAYOFFS),
        _player(2024, 17, 'RPA', 'Burrow', 'QB', 25, bracket=PLAYOFFS),
    ]
    games = [_title_game(2024, 17, 'GSA', 'RPA'), _title_game(2024, 17, 'RPA', 'GSA')]
    honors, awards = _honors(players, games, champions={2024: 'GSA'}, names={'allen': 'Josh Allen'})

    assert [(r['player'], r['rings'], r['seasons']) for r in honors['rings']] == [
        ('Josh Allen', 1, [2024])
    ]
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
