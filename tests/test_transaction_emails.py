from scripts.transaction_emails import resolve_trade_player, trade_html

LIONS_DST = {'name': 'Detroit Lions', 'nfl_team': 'DET', 'position': 'D/ST'}
LIONS_OL = {'name': 'Detroit Lions', 'nfl_team': 'DET', 'position': 'OL'}
RAMS_DST = {'name': 'Los Angeles Rams', 'nfl_team': 'LAR', 'position': 'D/ST'}
RAMS_OL = {'name': 'Los Angeles Rams', 'nfl_team': 'LAR', 'position': 'OL'}

BEFORE = {'WJK': [LIONS_DST], 'J/J': [RAMS_DST], 'SLS': [LIONS_OL], 'S/T': [RAMS_OL]}
AFTER = {'WJK': [RAMS_DST], 'J/J': [LIONS_DST], 'SLS': [LIONS_OL], 'S/T': [RAMS_OL]}


def test_resolves_ambiguous_team_unit_from_givers_roster_before_trade():
    assert resolve_trade_player('Detroit Lions', 'WJK', 'J/J', BEFORE, AFTER) == LIONS_DST
    assert resolve_trade_player('Los Angeles Rams', 'J/J', 'WJK', BEFORE, AFTER) == RAMS_DST


def test_falls_back_to_receivers_roster_after_trade():
    assert resolve_trade_player('Detroit Lions', 'WJK', 'J/J', {}, AFTER) == LIONS_DST


def test_unresolvable_or_structured_players_pass_through():
    assert resolve_trade_player('Nobody', 'WJK', 'J/J', BEFORE, AFTER) == 'Nobody'
    assert resolve_trade_player(LIONS_OL, 'WJK', 'J/J', None, None) == LIONS_OL


def test_trade_html_renders_position_labels():
    body = trade_html('accepted', 'now', 'Bill (WJK)', 'Joe/Joe (J/J)',
                      ['D/ST Detroit Lions (DET)'], ['D/ST Los Angeles Rams (LAR)'])
    assert 'D/ST Detroit Lions (DET)' in body
    assert 'D/ST Los Angeles Rams (LAR)' in body
