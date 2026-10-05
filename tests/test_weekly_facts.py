import json

from qpfl import weekly_facts as wf
from scripts import export_weekly_facts as export


def _matchup(season, week, a, sa, b, sb, bracket=wf.REGULAR, two_week=False):
    label = f'Week {week}'
    return [
        wf.TeamGame(
            season, week, label, bracket, a, export.franchises_for(a), sa, b,
            export.franchises_for(b), sb, two_week,
        ),
        wf.TeamGame(
            season, week, label, bracket, b, export.franchises_for(b), sb, a,
            export.franchises_for(a), sa, two_week,
        ),
    ]  # fmt: skip


def _player(season, week, name, score, abbrev='GSA', position='QB'):
    return wf.PlayerGame(
        season, week, f'Week {week}', wf.REGULAR, name.lower(), name, position, abbrev,
        export.franchises_for(abbrev), score,
    )  # fmt: skip


def _league(weeks, scores):
    """`weeks` of (season, week) where GSA plays CGK and SLS plays WJK with the given
    four scores; returns team-game rows."""
    games = []
    for (season, week), (gsa, cgk, sls, wjk) in zip(weeks, scores, strict=True):
        games += _matchup(season, week, 'GSA', gsa, 'CGK', cgk)
        games += _matchup(season, week, 'SLS', sls, 'WJK', wjk)
    return games


def _texts(result, key='all'):
    return [wf.render(f['template'], {}) for f in result[key]]


def test_rank_and_phrasing_helpers():
    assert wf.rank_of(100, [100, 90, 80]) == (1, 3, 0)
    assert wf.rank_of(90, [100, 90, 90, 80]) == (2, 4, 1)
    assert wf.rank_of(80, [100, 90, 80], higher=False) == (1, 3, 0)
    assert wf.rank_phrase(1, 0, 'highest') == 'the highest'
    assert wf.rank_phrase(3, 1, 'highest') == 'tied for the 3rd-highest'
    assert [wf.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == [
        '1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd',
    ]  # fmt: skip
    assert wf.nth(1) == 'first'
    assert wf.article(8) == 'an' and wf.article(11) == 'an' and wf.article(5) == 'a'
    assert wf.render('{team:GSA} beat {team:S/T}', {'GSA': 'Griff'}) == 'Griff beat S/T'


def test_league_record_score_and_margin():
    weeks = [(2025, w) for w in range(1, 6)]
    games = _league(weeks, [(90, 80, 70, 60)] * 4 + [(160, 40, 70, 60)])

    result = wf.generate_week_facts(games, [], 2025, 5)
    texts = _texts(result)

    assert "GSA's 160 was the highest score in league history." in texts
    assert 'GSA beat CGK by 120, the largest margin of victory in league history.' in texts
    assert "CGK's 40 was the lowest score in league history." in texts


def test_point_in_time_ignores_later_weeks():
    weeks = [(2025, w) for w in range(1, 4)]
    games = _league(weeks, [(90, 80, 70, 60), (120, 80, 70, 60), (150, 80, 70, 60)])

    week_2 = _texts(wf.generate_week_facts(games, [], 2025, 2))

    assert "GSA's 120 was the highest score in league history." in week_2
    assert not any('150' in text for text in week_2)


def test_most_since_needs_a_season_of_gap():
    weeks = [(season, w) for season in (2023, 2024, 2025) for w in range(1, 16)]
    # WJK's 120s keep GSA off the league list; five 110s keep it off the franchise list.
    scores = [(110, 80, 70, 120)] * 5 + [(90, 80, 70, 120)] * 40
    scores[-1] = (105, 80, 70, 120)
    scores[5] = (105, 80, 70, 120)  # 2023 Week 6
    games = _league(weeks, scores)

    texts = _texts(wf.generate_week_facts(games, [], 2025, 15))
    assert "GSA's 105 was the most points since Week 6, 2023." in texts

    # Week 6's 105 came a week after the 110s: too soon for a callback.
    texts = _texts(wf.generate_week_facts(games, [], 2023, 6))
    assert not any(text.startswith("GSA's") for text in texts)


def test_franchise_lineage_counts_old_codes():
    assert export.franchises_for('MPA') == ('RPA',)
    assert export.franchises_for('JRW') == ('AST',)
    assert export.franchises_for('CGK/SRY') == ('CGK', 'S/T')

    games = []
    for week in range(1, 6):
        games += _matchup(2020, week, 'MPA', 50, 'GSA', 90)
    games += _matchup(2025, 1, 'RPA', 60, 'GSA', 90)

    ctx = wf.WeekContext(games, [], 2025, 1)
    streaks = wf._streak_facts(ctx)

    assert '{team:RPA} has lost 6 straight, the longest losing streak in league history.' in [
        f.template for f in streaks
    ]


def test_streaks_count_regular_season_only():
    games = []
    for week in range(1, 5):
        games += _matchup(2025, week, 'GSA', 90, 'CGK', 80)
    games += _matchup(2025, 16, 'GSA', 90, 'CGK', 80, bracket=wf.PLAYOFFS)
    games += _matchup(2026, 1, 'GSA', 90, 'CGK', 80)

    ctx = wf.WeekContext(games, [], 2026, 1)
    texts = [f.template for f in wf._streak_facts(ctx)]

    assert '{team:GSA} has won 5 straight, the longest win streak in league history.' in texts


def test_two_week_legs_never_count_as_results():
    games = _matchup(2025, 16, 'GSA', 10, 'CGK', 150, bracket=wf.CONSOLATION, two_week=True)
    games += _matchup(2025, 15, 'GSA', 90, 'CGK', 80)

    ctx = wf.WeekContext(games, [], 2025, 16)

    assert wf._matchup_facts(ctx) == []
    assert any('150' in f.template for f in wf._team_score_facts(ctx))


def test_player_club_counts_distinct_players():
    games = _league([(2025, 1), (2025, 2), (2025, 3)], [(90, 80, 70, 60)] * 3)
    players = [_player(2025, 1, 'Josh Allen', 56), _player(2025, 2, 'Josh Allen', 55)]
    players += [_player(2025, w, f'Filler {w}', 10) for w in (1, 2, 3)]
    players.append(_player(2025, 3, 'Tom Brady', 57, abbrev='CGK'))

    texts = _texts(wf.generate_week_facts(games, players, 2025, 3))

    assert any(
        text.startswith('Tom Brady (CGK) scored 57, the highest single-game score')
        and 'just the 2nd player ever to score 55+' in text
        for text in texts
    )


def test_season_start_and_first_ever_phrasing():
    weeks = [(2025, w) for w in range(1, 5)]
    games = _league(weeks, [(90, 80, 70, 60)] * 4)

    texts = _texts(wf.generate_week_facts(games, [], 2025, 4))

    assert 'GSA is 4-0, the first 4-0 start in league history.' in texts
    assert 'CGK is 0-4, the first 0-4 start in league history.' in texts


def test_curation_caps_teams_and_covers_categories():
    facts = [wf.Fact(f'team_{i}', wf.TEAM, ['GSA'], f'GSA fact {i}', 0.9) for i in range(6)]
    facts.append(wf.Fact('player_a', wf.PLAYER, ['CGK'], 'player fact', 0.2))
    facts.append(wf.Fact('league_a', wf.LEAGUE, [], 'league fact', 0.1))

    picked = wf.curate(facts, limit=10, per_team=3)

    assert sum(1 for f in picked if f.subjects == ['GSA']) == 3
    assert {f.category for f in picked} == {wf.TEAM, wf.PLAYER, wf.LEAGUE}
    assert picked[0].notability == 0.9  # still ordered by notability


def test_export_skips_rewrite_when_only_timestamp_changes(tmp_path):
    path = tmp_path / 'facts' / 'week_1.json'
    facts = {'season': 2026, 'week': 1, 'headline': [], 'all': []}

    assert export.write_facts(facts, path) is True
    first = json.loads(path.read_text())['generated_at']
    assert export.write_facts(facts, path) is False
    assert json.loads(path.read_text())['generated_at'] == first
    assert export.write_facts({**facts, 'week': 2}, path) is True


def test_flatten_season_tags_brackets_and_starters():
    season = {
        'season': 2025,
        'weeks': [
            {
                'week': 16,
                'matchups': [
                    {
                        'bracket': 'playoffs',
                        'team1': {
                            'abbrev': 'GSA',
                            'total_score': 100,
                            'roster': [
                                {
                                    'name': 'Josh Allen',
                                    'position': 'QB',
                                    'score': 30,
                                    'starter': True,
                                },
                                {
                                    'name': 'Bench Guy',
                                    'position': 'RB',
                                    'score': 9,
                                    'starter': False,
                                },
                            ],
                        },
                        'team2': {'abbrev': 'MPA', 'total_score': 90, 'roster': []},
                    },
                    {
                        'bracket': 'mid_bowl',
                        'two_week': True,
                        'team1': {'abbrev': 'SLS', 'total_score': 80, 'roster': []},
                        'team2': {'abbrev': 'WJK', 'total_score': 70, 'roster': []},
                    },
                ],
            }
        ],
    }

    teams, players = export.flatten_season(season)

    assert {(g.abbrev, g.bracket, g.two_week) for g in teams} == {
        ('GSA', wf.PLAYOFFS, False),
        ('MPA', wf.PLAYOFFS, False),
        ('SLS', wf.CONSOLATION, True),
        ('WJK', wf.CONSOLATION, True),
    }
    assert next(g for g in teams if g.abbrev == 'MPA').franchises == ('RPA',)
    assert [(p.name, p.score) for p in players] == [('Josh Allen', 30.0)]
