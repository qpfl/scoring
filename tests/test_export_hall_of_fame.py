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
        hof.add_season_coowner('Redacted Reardon', 'CWR', 2026)
        == 'Redacted Reardon & Jack Reardon'
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
