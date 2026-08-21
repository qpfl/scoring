import json

from scripts import export_hall_of_fame as hof


def _team(abbrev, score):
    return {'abbrev': abbrev, 'total_score': score, 'name': abbrev, 'roster': []}


def _week(number, score_a, score_b):
    team_a = _team('CWR', score_a)
    team_b = _team('CGK', score_b)
    return {
        'week': number,
        'has_scores': True,
        'matchups': [{'team1': team_a, 'team2': team_b}],
    }


def test_live_season_loader_excludes_unfinished_weeks(tmp_path, monkeypatch):
    seasons_dir = tmp_path / 'seasons'
    weeks_dir = seasons_dir / '2026' / 'weeks'
    weeks_dir.mkdir(parents=True)
    (weeks_dir / 'week_1.json').write_text(json.dumps(_week(1, 80, 70)))
    (weeks_dir / 'week_2.json').write_text(json.dumps(_week(2, 12, 0)))
    (seasons_dir / '2026' / 'standings.json').write_text('[]')
    monkeypatch.setattr(hof, 'SEASONS_DIR', seasons_dir)

    season = hof.load_season_data(2026, current_season=2026, completed_through=1)

    assert [week['week'] for week in season['weeks']] == [1]
    rows = {row['abbrev']: row for row in season['standings']['standings']}
    assert rows['CWR']['wins'] == 1
    assert rows['CWR']['points_for'] == 80
    assert rows['CGK']['losses'] == 1
    assert season['regular_season_complete'] is False

    rivalry_records = hof.calculate_rivalry_records([season])
    team_hof = hof.calculate_team_hall_of_fame(
        [season], [], rivalry_records, franchise_abbrevs=['CWR']
    )['CWR']
    assert team_hof['allTime']['gamesPlayed'] == 1
    assert team_hof['allTime']['totalPoints'] == 80
    assert team_hof['seasons'][0]['highestScore']['week'] == 1


def test_completed_zero_score_is_valid_for_owner_standings():
    standings = hof.calculate_completed_standings([_week(1, 0, 7)], 2026)['standings']
    rows = {row['abbrev']: row for row in standings}
    assert rows['CWR']['losses'] == 1
    assert rows['CWR']['points_for'] == 0
    assert rows['CGK']['wins'] == 1


def test_jack_receives_cwr_owner_stats_only_from_2026():
    assert hof.get_owner_codes('CWR', 2025) == ['CWR']
    assert hof.get_owner_codes('CWR', 2026) == ['CWR', 'JTR']
    assert hof.get_owner_codes('CGK', 2026) == ['CGK']


def test_2026_cwr_results_are_credited_to_reardon_and_jack():
    season = {
        'season': 2026,
        'weeks': [],
        'standings': {
            'standings': [
                {
                    'abbrev': 'CWR',
                    'wins': 1,
                    'losses': 0,
                    'ties': 0,
                    'points_for': 80,
                    'points_against': 70,
                }
            ]
        },
        'regular_season_complete': False,
    }

    rows = {row['Code']: row for row in hof.calculate_owner_stats([season], [])}

    assert rows['CWR']['Record'] == '1-0'
    assert rows['JTR']['Record'] == '1-0'
    assert rows['JTR']['Seasons'] == '1'


def test_cwr_hof_labels_include_jack_only_from_2026():
    assert hof.add_season_coowner('Redacted Reardon', 'CWR', 2025) == 'Redacted Reardon'
    assert (
        hof.add_season_coowner('Redacted Reardon', 'CWR', 2026) == 'Redacted Reardon & Jack Reardon'
    )
    assert (
        hof.add_season_coowner('Redacted Reardon & Jack Reardon', 'CWR', 2026)
        == 'Redacted Reardon & Jack Reardon'
    )


def test_coowner_labels_use_full_names_and_ampersands(monkeypatch):
    monkeypatch.setattr(hof, '_SEASON_COOWNER_NAMES', {})
    season = {
        'season': 2025,
        'weeks': [
            {
                'week': 5,
                'has_scores': True,
                'matchups': [
                    {
                        'team1': _team('WJK', 100),
                        'team2': _team('J/J', 70),
                    }
                ],
            }
        ],
    }

    hof.update_season_coowner_names([season])

    assert hof.add_season_coowner('', 'S/T', 2025) == 'Spencer Yoder & Tim Grazier'
    assert hof.add_season_coowner('', 'J/J', 2025) == 'Joe Censored & Censored Ward'
    assert (
        hof.normalize_coowners_in_text('Spencer/Tim over Joe/Joe', 2025)
        == 'Spencer Yoder & Tim Grazier over Joe Censored & Censored Ward'
    )


def test_discover_seasons_includes_configured_current_year(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    seasons_dir = data_dir / 'seasons'
    seasons_dir.mkdir(parents=True)
    (data_dir / 'index.json').write_text(json.dumps({'seasons': [2025, 2024]}))
    (seasons_dir / '2023').mkdir()
    monkeypatch.setattr(hof, 'DATA_DIR', data_dir)
    monkeypatch.setattr(hof, 'SEASONS_DIR', seasons_dir)

    assert hof.discover_seasons(2026) == [2026, 2025, 2024, 2023]


def test_completed_week_defaults_to_last_safe_marker():
    existing = {'completed_through': {'2026': 8}}

    assert hof.resolve_completed_through(existing, 2026, None) == 8
    assert hof.resolve_completed_through(existing, 2026, 9) == 9
    assert hof.resolve_completed_through({}, 2026, None) == 0


def test_team_hof_combines_shared_franchise_seasons():
    team = _team('CWR/SLS', 91)
    team['roster'] = [
        {
            'name': 'A.J. Brown',
            'position': 'WR',
            'nfl_team': 'PHI',
            'score': 18,
            'starter': True,
        }
    ]
    opponent = _team('GSA', 80)
    season = {
        'season': 2021,
        'weeks': [
            {
                'week': 1,
                'has_scores': True,
                'matchups': [{'team1': team, 'team2': opponent}],
            }
        ],
        'standings': {'standings': [team, opponent]},
        'regular_season_complete': True,
    }
    rivalries = hof.calculate_rivalry_records([season])

    histories = hof.calculate_team_hall_of_fame(
        [season], [], rivalries, franchise_abbrevs=['CWR', 'SLS']
    )

    assert histories['CWR']['allTime']['wins'] == 1
    assert histories['SLS']['allTime']['wins'] == 1
    assert histories['CWR']['topPlayersByTotalPoints'][0]['name'] == 'A.J. Brown'


def test_team_hof_follows_franchise_seat_and_summarizes_previous_owners(monkeypatch):
    monkeypatch.setattr(hof, '_SEASON_COOWNER_NAMES', {})
    miles = _team('MPA', 90)
    ryan = _team('RPA', 70)
    opponent_2020 = _team('GSA', 80)
    opponent_2021 = _team('GSA', 75)
    seasons = [
        {
            'season': 2020,
            'weeks': [
                {
                    'week': 1,
                    'has_scores': True,
                    'matchups': [{'team1': miles, 'team2': opponent_2020}],
                }
            ],
            'standings': {'standings': [miles, opponent_2020]},
            'regular_season_complete': True,
        },
        {
            'season': 2021,
            'weeks': [
                {
                    'week': 1,
                    'has_scores': True,
                    'matchups': [{'team1': ryan, 'team2': opponent_2021}],
                }
            ],
            'standings': {'standings': [ryan, opponent_2021]},
            'regular_season_complete': True,
        },
    ]
    finishes = [{'year': '2020', 'results': ['Miles']}]
    rivalries = hof.calculate_rivalry_records(seasons)

    history = hof.calculate_team_hall_of_fame(
        seasons, finishes, rivalries, franchise_abbrevs=['RPA']
    )['RPA']

    assert [season['season'] for season in history['seasons']] == [2021, 2020]
    assert history['allTime']['gamesPlayed'] == 2
    owners = {owner['owner']: owner for owner in history['ownerStats']}
    assert owners['Miles']['wins'] == 1
    assert owners['Miles']['rings'] == 1
    assert owners['Ryan A.']['losses'] == 1


def test_player_career_profiles_join_seasons_draft_aliases_and_awards():
    patrick_2020 = _team('GSA', 80)
    patrick_2020['roster'] = [
        {
            'name': 'Patrick Mahomes',
            'position': 'QB',
            'nfl_team': 'KC',
            'score': 30,
            'starter': True,
        },
        {
            'name': 'Josh Allen',
            'position': 'QB',
            'nfl_team': 'BUF',
            'score': 35,
            'starter': True,
        },
    ]
    patrick_2021 = _team('GSA', 90)
    patrick_2021['roster'] = [
        {
            'name': 'Patrick Mahomes II',
            'position': 'QB',
            'nfl_team': 'KC',
            'score': 40,
            'starter': False,
        }
    ]
    seasons = [
        {
            'season': 2020,
            'weeks': [
                {
                    'week': 1,
                    'has_scores': True,
                    'matchups': [{'team1': patrick_2020, 'team2': _team('CGK', 70)}],
                }
            ],
        },
        {
            'season': 2021,
            'weeks': [
                {
                    'week': 1,
                    'has_scores': True,
                    'matchups': [{'team1': patrick_2021, 'team2': _team('CGK', 70)}],
                }
            ],
        },
    ]
    drafts = [
        {
            'name': 'Founding Draft',
            'rounds': [
                {'round': '1', 'picks': [{'pick': '5', 'team': 'Griff', 'player': 'P. Mahomes'}]}
            ],
        }
    ]
    rosters = {
        'GSA': [
            {
                'name': 'Patrick Mahomes II',
                'position': 'QB',
                'nfl_team': 'KC',
            }
        ]
    }

    profiles = hof.calculate_player_career_stats(
        seasons,
        drafts=drafts,
        current_rosters=rosters,
        award_entries=['2020 - Patrick Mahomes (GSA)'],
        player_birth_dates={'patrick mahomes': '1995-09-17'},
    )
    profile = profiles['Patrick Mahomes II']

    assert profile['aliases'] == ['P. Mahomes', 'Patrick Mahomes', 'Patrick Mahomes II']
    assert profile['total_points'] == 70
    assert profile['games'] == 2
    assert profile['starts'] == 1
    assert profile['seasons']['2020']['position_rank'] == 2
    assert profile['seasons']['2020']['owners'] == ['GSA']
    assert profile['awards'] == [{'year': 2020, 'title': 'QPFL MVP'}]
    assert profile['birth_date'] == '1995-09-17'


def test_player_identity_resolves_multi_initial_draft_aliases_without_conflating_names():
    profiles = {'a j brown': {}, 'antonio brown': {}}

    assert hof._resolve_player_key('AJ Brown', profiles) == 'a j brown'
    assert hof._resolve_player_key('A. Brown', profiles) == 'a brown'


def test_defense_and_offensive_line_with_same_team_name_have_separate_profiles():
    defense = {
        'name': 'Buffalo Bills',
        'position': 'D/ST',
        'nfl_team': 'BUF',
        'score': 8,
        'starter': True,
    }
    offensive_line = {
        'name': 'Buffalo Bills',
        'position': 'OL',
        'nfl_team': 'BUF',
        'score': 3,
        'starter': True,
    }
    team_a = _team('CGK', 8)
    team_a['roster'] = [defense]
    team_b = _team('SLS', 3)
    team_b['roster'] = [offensive_line]
    seasons = [
        {
            'season': 2025,
            'weeks': [
                {
                    'week': 1,
                    'has_scores': True,
                    'matchups': [{'team1': team_a, 'team2': team_b}],
                }
            ],
        }
    ]
    rosters = {'CGK': [defense], 'SLS': [offensive_line]}

    profiles = hof.calculate_player_career_stats(seasons, current_rosters=rosters)

    assert profiles['Buffalo Bills (D/ST)']['position'] == 'D/ST'
    assert profiles['Buffalo Bills (D/ST)']['total_points'] == 8
    assert profiles['Buffalo Bills (OL)']['position'] == 'OL'
    assert profiles['Buffalo Bills (OL)']['total_points'] == 3
