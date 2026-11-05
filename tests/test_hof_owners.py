from scripts import export_hall_of_fame as hof
from scripts import hof_owners, hof_records


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
    weeks = list(weeks)
    standings = hof.calculate_completed_standings(weeks, season)
    return {
        'season': season,
        'weeks': weeks,
        'standings': standings,
        'award_standings': standings,
        'regular_season_complete': complete,
    }


def _profiles(all_seasons):
    owner_stats = hof.calculate_owner_stats(all_seasons, [])
    book = hof_records.build_record_book(all_seasons, lambda abbrev, season: abbrev)
    return hof_owners.build_owner_profiles(all_seasons, owner_stats, {}, book, [])


def test_co_owned_teams_credit_every_owner():
    profiles = _profiles(
        [
            _season(
                2024,
                _week(1, (_team('J/J', 100), _team('S/T', 80))),
                _week(2, (_team('S/T', 90), _team('J/J', 70))),
            )
        ]
    )

    assert {'JRW', 'JDK', 'SRY', 'TJG'} <= set(profiles)
    assert 'S/T' not in profiles
    for code in ('JRW', 'JDK'):
        assert profiles[code]['summary']['record'] == '1-1'
        assert profiles[code]['teams'] == [
            {
                'team': 'J/J',
                'first_season': 2024,
                'last_season': 2024,
                'co_owners': ['JDK' if code == 'JRW' else 'JRW'],
            }
        ]
    vs_spencer = next(row for row in profiles['JDK']['head_to_head'] if row['opponent'] == 'SRY')
    assert vs_spencer['record'] == '1-1'
    vs_st = vs_spencer
    assert vs_st['last'] == {
        'season': 2024,
        'week': 2,
        'week_label': 'Week 2',
        'team': 'J/J',
        'score': 70,
        'opponent_score': 90,
        'result': 'L',
    }


def test_owner_seasons_follow_a_team_through_new_co_owners():
    profiles = _profiles(
        [
            _season(2025, _week(1, (_team('CWR', 100, name='Ladds'), _team('GSA', 80)))),
            _season(2026, _week(1, (_team('CWR', 90), _team('GSA', 95))), complete=False),
        ]
    )

    reardon = profiles['CWR']
    assert [t['co_owners'] for t in reardon['teams']] == [[], ['JTR']]
    assert [(s['season'], s['record'], s['rank']) for s in reardon['seasons']] == [
        (2026, '0-1', None),
        (2025, '1-0', 1),
    ]
    assert reardon['seasons'][1]['team_name'] == 'Ladds'
    # Only completed regular seasons can be the best or worst.
    assert reardon['best_season']['season'] == reardon['worst_season']['season'] == 2025
    assert profiles['JTR']['summary']['seasons'] == 1


def test_records_held_skip_player_totals_and_top_players_sum_starts():
    roster = [_player('Josh Allen', 'QB', 40), _player('Jalen Hurts', 'QB', 10, starter=False)]
    profiles = _profiles(
        [
            _season(
                2024,
                _week(1, (_team('CGK', 120, roster), _team('GSA', 80))),
                _week(2, (_team('CGK', 110, roster), _team('GSA', 90))),
            )
        ]
    )

    held = profiles['CGK']['records_held']
    assert held
    assert {row['category'] for row in held}.isdisjoint({'player-season', 'player-career'})
    assert any(row['group'] == 'team-game-most-points' and row['rank'] == 1 for row in held)

    top = profiles['CGK']['top_players']
    assert [(p['player'], p['points'], p['starts'], p['seasons']) for p in top] == [
        ('Josh Allen', 80, 2, [2024])
    ]
