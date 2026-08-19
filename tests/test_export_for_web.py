from scripts.export_for_web import parse_player_name


def test_historical_initials_resolve_by_season_and_fantasy_team():
    assert parse_player_name('A. Brown', season=2020, team_abbrev='AYP') == (
        'A.J. Brown',
        'TEN',
    )
    assert parse_player_name('A. Brown', season=2020, team_abbrev='GSA') == (
        'A.J. Brown',
        'TEN',
    )
    assert parse_player_name('A. Brown', season=2020, team_abbrev='CWR') == (
        'Antonio Brown',
        'TB',
    )
    assert parse_player_name('J. Jones', season=2020, team_abbrev='CGK') == (
        'Julio Jones',
        'ATL',
    )
    assert parse_player_name('J. Jones', season=2020, team_abbrev='CWR') == (
        'Julio Jones',
        'ATL',
    )


def test_2021_historical_initials_follow_confirmed_players():
    assert parse_player_name('A. Brown', season=2021, team_abbrev='GSA') == (
        'A.J. Brown',
        'TEN',
    )
    assert parse_player_name('A. Brown', season=2021, team_abbrev='CWR/SLS') == (
        'Antonio Brown',
        'TB',
    )
    assert parse_player_name('J. Jones', season=2021, team_abbrev='CWR/SLS') == (
        'Julio Jones',
        'TEN',
    )
