from scripts import export_hall_of_fame as hof
from scripts import hof_franchises, hof_records


def _team(abbrev, score, name=None):
    return {'abbrev': abbrev, 'name': name or f'{abbrev} Team', 'total_score': score, 'roster': []}


def _week(number, *matchups):
    return {
        'week': number,
        'has_scores': True,
        'matchups': [{'team1': a, 'team2': b} for a, b in matchups],
    }


def _season(season, *weeks, complete=True):
    weeks = list(weeks)
    standings = hof.calculate_completed_standings(weeks, season)
    # The official standings files the export reads are in rank order.
    standings['standings'].sort(key=lambda row: -row['wins'])
    return {
        'season': season,
        'weeks': weeks,
        'standings': standings,
        'award_standings': standings,
        'regular_season_complete': complete,
    }


def _index(all_seasons, franchises, team_hall_of_fame=None):
    book = hof_records.build_record_book(all_seasons, lambda abbrev, season: abbrev)
    names = {
        'RCP': 'Ryan P.',
        'JDK': 'Joe K.',
        'JRW': 'Joe W.',
        'GSA': 'Griff',
        'CWR': 'Reardon',
        'SLS': 'Stephen',
    }
    index = hof_franchises.build_franchise_index(
        all_seasons, franchises, team_hall_of_fame or {}, book, names
    )
    return {franchise['abbrev']: franchise for franchise in index}


def test_franchise_follows_its_seat_through_new_owners_and_names():
    index = _index(
        [
            _season(2021, _week(1, (_team('RCP', 90, 'Bocki Balboa'), _team('GSA', 80)))),
            _season(2022, _week(1, (_team('JDK', 70, 'Elite'), _team('GSA', 100)))),
            _season(2024, _week(1, (_team('J/J', 95, 'Jean(ty)s'), _team('GSA', 85)))),
        ],
        ['J/J', 'GSA'],
    )

    jj = index['J/J']
    assert jj['lineage'] == ['J/J', 'JDK', 'RCP']
    assert jj['first_season'] == 2021
    assert jj['name'] == 'Jean(ty)s'
    assert [(e['team'], e['names'], e['first_season']) for e in jj['eras']] == [
        ('RCP', ['Ryan P.'], 2021),
        ('JDK', ['Joe K.'], 2022),
        ('J/J', ['Joe W.', 'Joe K.'], 2024),
    ]
    assert [n['name'] for n in jj['team_names']] == ['Bocki Balboa', 'Elite', 'Jean(ty)s']
    assert [(s['season'], s['record'], s['rank']) for s in jj['seasons']] == [
        (2024, '1-0', 1),
        (2022, '0-1', 2),
        (2021, '1-0', 1),
    ]
    assert any(r['group'] == 'team-game-fewest-points' and r['shame'] for r in jj['records_held'])


def test_shared_seasons_name_both_owners_and_best_finish_reads_as_a_place():
    team_hof = {
        'SLS': {
            'seasons': [
                {'season': 2021, 'seasonFinishes': [{'type': 'playoff', 'label': '3rd Place'}]},
                {'season': 2022, 'seasonFinishes': []},
            ]
        }
    }
    index = _index(
        [
            _season(2021, _week(1, (_team('CWR/SLS', 90), _team('GSA', 80)))),
            _season(2022, _week(1, (_team('SLS', 70), _team('GSA', 100)))),
        ],
        ['SLS'],
        team_hof,
    )

    sls = index['SLS']
    # A shared season belongs to both of its owners.
    assert (sls['eras'][0]['owners'], sls['eras'][0]['names']) == (
        ['CWR', 'SLS'],
        ['Reardon', 'Stephen'],
    )
    assert sls['best_finish'] == {'season': 2021, 'label': '3rd Place'}
    assert hof_franchises._ordinal(3) == '3rd'
    assert hof_franchises._ordinal(12) == '12th'


def test_finishes_match_whoever_ran_the_seat_that_season():
    finishes = [{'year': '2023', 'results': ['GSA owner', 'Somebody', 'Censored Ward']}]
    standings_2023 = [{'abbrev': 'GSA'}, {'abbrev': 'CGK'}, {'abbrev': 'JRW'}, {'abbrev': 'JDK'}]

    # Joe Ward ran JRW (now AST) in 2023, so its 3rd place belongs to AST...
    assert hof._season_finish_badges(finishes, 2023, 'AST', standings_2023, True) == [
        {'type': 'playoff', 'label': '3rd Place'}
    ]
    # ...not to J/J, which Joe Ward only joined in 2024.
    jj = hof._season_finish_badges(finishes, 2023, 'J/J', standings_2023, True)
    assert {'type': 'playoff', 'label': '3rd Place'} not in jj


def test_franchises_carry_elo_and_player_nemeses():
    from qpfl import weekly_facts as wf
    from scripts.export_weekly_facts import franchises_for

    gsa, cgk = franchises_for('GSA'), franchises_for('CGK')
    team_games = [
        wf.TeamGame(2025, 1, 'Week 1', wf.REGULAR, 'GSA', gsa, 120, 'CGK', cgk, 100),
        wf.TeamGame(2025, 1, 'Week 1', wf.REGULAR, 'CGK', cgk, 100, 'GSA', gsa, 120),
    ]

    def player(name, score, abbrev, opp, bracket=wf.REGULAR, starter=True):
        return wf.PlayerGame(
            2025, 1, 'Week 1', bracket, name.lower(), name, 'QB', abbrev,
            franchises_for(abbrev), score, starter, franchises_for(opp),
        )  # fmt: skip

    player_games = [
        player('Allen', 40, 'CGK', 'GSA'),
        player('Bench', 50, 'CGK', 'GSA', starter=False),
        player('Toilet', 60, 'CGK', 'GSA', bracket=wf.CONSOLATION),
    ]
    seasons = [_season(2025, _week(1, (_team('GSA', 120), _team('CGK', 100))))]
    book = hof_records.build_record_book(seasons, lambda abbrev, season: abbrev)
    index = {
        f['abbrev']: f
        for f in hof_franchises.build_franchise_index(
            seasons, ['GSA', 'CGK'], {}, book, {}, team_games, player_games
        )
    }
    assert index['GSA']['elo'] > 1500 > index['CGK']['elo']
    assert (index['GSA']['elo_rank'], index['CGK']['elo_rank']) == (1, 2)
    assert index['GSA']['elo_series'][0][:2] == [2025, 1]
    # Starters only, consolation games out.
    assert [(r['player'], r['points']) for r in index['GSA']['player_nemeses']] == [('Allen', 40)]
    assert index['CGK']['player_nemeses'] == []
