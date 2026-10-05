import dataclasses
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


def test_verbs_agree_with_co_owned_names():
    template = '{team:S/T} {has:S/T} won 4 straight; {team:GSA} {is:GSA} 3-0.'
    names = {'S/T': 'Spencer/Tim', 'GSA': 'Griff'}

    assert wf.render(template, names) == 'Spencer/Tim have won 4 straight; Griff is 3-0.'
    assert wf.render('{team:J/J} {is:J/J} 0-4.', {'J/J': 'Joe & Joe'}) == 'Joe & Joe are 0-4.'
    # A team name, not an owner pair, stays singular.
    assert wf.render('{team:S/T} {has:S/T} won.', {'S/T': 'Drunk Darts'}) == 'Drunk Darts has won.'


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

    assert '{team:RPA} {has:RPA} lost 6 straight, the longest losing streak in league history.' in [
        f.template for f in streaks
    ]


def test_streaks_run_through_playoff_and_consolation_games():
    games = []
    for week in range(14, 16):
        games += _matchup(2025, week, 'CWR', 90, 'CGK', 80)
    # Lost a semifinal, then won the 3rd-place game.
    games += _matchup(2025, 16, 'CWR', 70, 'SLS', 95, bracket=wf.PLAYOFFS)
    games += _matchup(2025, 17, 'CWR', 90, 'AYP', 80, bracket=wf.CONSOLATION)
    for week in range(1, 4):
        games += _matchup(2026, week, 'CWR', 90, 'WJK', 80)

    ctx = wf.WeekContext(games, [], 2026, 3)
    texts = [f.template for f in wf._streak_facts(ctx)]

    # One number per team: the longer regular-season run, labeled as such.
    assert any(
        t.startswith('{team:CWR} {has:CWR} won 5 straight regular-season games') for t in texts
    )
    assert not any(t.startswith('{team:CWR} {has:CWR} won 4 straight') for t in texts)


def test_regular_season_streak_stands_alone_only_with_its_caveat():
    games = []
    for week in range(13, 16):
        games += _matchup(2025, week, 'CWR', 90, 'CGK', 80)
    games += _matchup(2025, 16, 'CWR', 70, 'SLS', 95, bracket=wf.PLAYOFFS)
    games += _matchup(2025, 17, 'CWR', 70, 'AYP', 80, bracket=wf.CONSOLATION)
    games += _matchup(2026, 1, 'CWR', 90, 'WJK', 80)

    ctx = wf.WeekContext(games, [], 2026, 1)
    texts = [f.template for f in wf._streak_facts(ctx)]

    assert any(
        t.startswith('{team:CWR} {has:CWR} won 4 straight regular-season games') for t in texts
    )
    assert not any(t.startswith('{team:CWR} {has:CWR} won 4 straight,') for t in texts)


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

    # GSA and SLS both start 4-0, so they share one note; CGK is alone at 0-4.
    assert 'Two teams are 4-0, the first 4-0 starts in league history: GSA and SLS.' in texts
    assert not any(text.startswith('GSA is 4-0') for text in texts)


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
    assert [(p.name, p.score, p.starter) for p in players] == [
        ('Josh Allen', 30.0, True),
        ('Bench Guy', 9.0, False),
    ]
    assert players[0].opp_franchises == ('RPA',)


def test_two_week_matchup_counts_once_by_combined_score():
    def leg(week, game, gsa, ayp):
        return {
            'week': week,
            'matchups': [
                {
                    'bracket': 'mid_bowl',
                    'game': game,
                    'two_week': True,
                    'team1': {'abbrev': 'GSA', 'total_score': gsa, 'roster': []},
                    'team2': {'abbrev': 'AYP', 'total_score': ayp, 'roster': []},
                }
            ],
        }

    # AYP wins week 2 but loses the Mid Bowl 181-205 on aggregate.
    season = {
        'season': 2025,
        'weeks': [leg(16, 'mid_bowl_week1', 102, 99), leg(17, 'mid_bowl_week2', 103, 82)],
    }
    teams, _ = export.flatten_season(season)
    rows = {(g.week, g.abbrev): g for g in teams}

    assert not rows[(16, 'AYP')].decided and not rows[(16, 'AYP')].lost
    assert rows[(17, 'AYP')].lost and rows[(17, 'GSA')].won
    assert (rows[(17, 'AYP')].result_score, rows[(17, 'AYP')].result_opp_score) == (181, 205)

    # The legs still never count as single-game margins or combined scores.
    ctx = wf.WeekContext(teams, [], 2025, 17)
    assert wf._matchup_facts(ctx) == []


def test_fastest_cycle_is_the_shortest_run_beating_every_rival():
    games = []
    games += _matchup(2025, 1, 'GSA', 90, 'CGK', 80)
    games += _matchup(2025, 2, 'GSA', 70, 'SLS', 80)  # loss: SLS still unbeaten
    games += _matchup(2025, 3, 'GSA', 90, 'SLS', 80)
    games += _matchup(2025, 4, 'GSA', 90, 'CGK', 80)
    # The playoff win completes the cycle.
    games += _matchup(2025, 16, 'GSA', 90, 'WJK', 80, bracket=wf.PLAYOFFS)

    cycles = {c.franchise: c for c in wf.fastest_cycles(games, ['GSA', 'CGK', 'SLS', 'WJK'])}

    gsa = cycles['GSA']
    assert gsa.games == 3  # weeks 3, 4 and 16, not the longer run from week 1
    assert (gsa.start.week, gsa.end.week) == (3, 16)
    assert 'CGK' not in cycles  # never beat anyone


def test_co_owned_teams_count_once_toward_a_cycle():
    games = []
    # One win over 2021's CGK/SRY must not also count as beating S/T.
    games += _matchup(2021, 1, 'GSA', 90, 'CGK/SRY', 80)
    games += _matchup(2021, 2, 'GSA', 90, 'WJK', 80)

    assert wf.fastest_cycles(games, ['GSA', 'CGK', 'S/T', 'WJK']) == []

    games += _matchup(2022, 1, 'GSA', 90, 'S/T', 80)
    (gsa,) = wf.fastest_cycles(games, ['GSA', 'CGK', 'S/T', 'WJK'])
    assert gsa.franchise == 'GSA' and gsa.games == 3


def _cycle_texts(games, season, week):
    ctx = wf.WeekContext(games, [], season, week)
    return [f.template for f in wf._cycle_facts(ctx)]


def _round_robin_week(season, week, winners):
    """Four teams; `winners` maps each matchup's winner to its loser."""
    games = []
    for winner, loser in winners.items():
        games += _matchup(season, week, winner, 90, loser, 80)
    return games


def test_cycle_notes_league_records_franchise_bests_and_firsts():
    games = []
    # GSA: beats CGK, SLS, WJK in weeks 1-3 -> first-ever cycle, league record (3).
    games += _round_robin_week(2025, 1, {'GSA': 'CGK', 'SLS': 'WJK'})
    games += _round_robin_week(2025, 2, {'GSA': 'SLS', 'CGK': 'WJK'})
    games += _round_robin_week(2025, 3, {'GSA': 'WJK', 'CGK': 'SLS'})

    texts = _cycle_texts(games, 2025, 3)
    assert texts == [
        '{team:GSA} {has:GSA} now beaten every other team in a span of 3 games '
        '(Week 1, 2025 to Week 3, 2025), the fastest in league history.'
    ]

    # CGK finishes a 3-game cycle (weeks 2-4): ties GSA's league record.
    games += _round_robin_week(2025, 4, {'CGK': 'GSA', 'SLS': 'WJK'})
    assert _cycle_texts(games, 2025, 4) == [
        '{team:CGK} {has:CGK} now beaten every other team in a span of 3 games '
        "(Week 2, 2025 to Week 4, 2025), tying {team:GSA}'s league record."
    ]


def test_cycle_record_wording_for_own_record_and_same_week_finishers():
    games = []
    # GSA's first cycle takes 4 games (a loss in week 2), then a 3-game one.
    games += _round_robin_week(2025, 1, {'GSA': 'CGK', 'SLS': 'WJK'})
    games += _round_robin_week(2025, 2, {'SLS': 'GSA', 'CGK': 'WJK'})
    games += _round_robin_week(2025, 3, {'GSA': 'SLS', 'WJK': 'CGK'})
    games += _round_robin_week(2025, 4, {'GSA': 'WJK', 'CGK': 'SLS'})
    games += _round_robin_week(2025, 5, {'GSA': 'CGK', 'SLS': 'WJK'})

    assert _cycle_texts(games, 2025, 5) == [
        '{team:GSA} {has:GSA} now beaten every other team in a span of 3 games '
        '(Week 3, 2025 to Week 5, 2025), the fastest in league history, '
        'breaking their own record of 4.'
    ]


def test_slower_cycle_finished_the_same_week_is_not_a_league_record():
    games = []
    games += _round_robin_week(2025, 1, {'SLS': 'GSA', 'CGK': 'WJK'})
    games += _round_robin_week(2025, 2, {'GSA': 'WJK', 'SLS': 'CGK'})
    games += _round_robin_week(2025, 3, {'GSA': 'SLS', 'WJK': 'CGK'})
    games += _round_robin_week(2025, 4, {'GSA': 'CGK', 'SLS': 'WJK'})

    texts = {t.split(' ')[0]: t for t in _cycle_texts(games, 2025, 4)}

    assert (
        '3 games' in texts['{team:GSA}'] and 'the fastest in league history.' in texts['{team:GSA}']
    )
    assert '4 games' in texts['{team:SLS}']
    assert texts['{team:SLS}'].endswith('the first time the franchise has done it.')


# --------------------------------------------------------------------------- #
# Lineups, luck, stakes, careers, drafts, trades and projections
# --------------------------------------------------------------------------- #


def _with(games, **changes):
    """Copies of team-game rows with fields changed, keyed by team code."""
    return [
        dataclasses.replace(g, **changes[g.abbrev]) if g.abbrev in changes else g for g in games
    ]


def _templates(detector, games, season, week, players=(), **context):
    ctx = wf.WeekContext(games, list(players), season, week, **context)
    return [f.template for f in detector(ctx)]


def test_best_lineup_fills_each_started_slot_with_the_top_scorers():
    team = {
        'roster': [
            {'name': 'QB1', 'position': 'QB', 'score': 10, 'starter': True},
            {'name': 'QB2', 'position': 'QB', 'score': 25, 'starter': False},
            {'name': 'RB1', 'position': 'RB', 'score': 8, 'starter': True},
            {'name': 'RB2', 'position': 'RB', 'score': 12, 'starter': True},
            {'name': 'RB3', 'position': 'RB', 'score': 9, 'starter': False},
        ]
    }

    assert export.best_lineup(team, 30) == 30 + 15 + 1  # QB2 for QB1, RB3 for RB1
    team['roster'][1]['score'] = None
    assert export.best_lineup(team, 30) is None


def test_lineup_notes_bench_points_and_losses_a_better_lineup_wins():
    games = []
    for week in range(1, 4):
        games += _with(
            _matchup(2025, week, 'GSA', 90, 'CGK', 80),
            GSA={'optimal': 95.0},
            CGK={'optimal': 85.0},
        )
    games += _with(
        _matchup(2025, 4, 'GSA', 100, 'CGK', 80),
        GSA={'optimal': 100.0},
        CGK={'optimal': 140.0},
    )

    texts = _templates(wf._lineup_facts, games, 2025, 4)

    assert (
        '{team:CGK} left 60 points on the bench (80 of a possible 140), the most in league history.'
    ) in texts
    assert (
        '{team:CGK} lost to {team:GSA} by 20 but would have won by starting the best '
        'lineup on the roster (140).'
    ) in texts


def test_benched_player_record():
    games = _league([(2025, 1), (2025, 2)], [(90, 80, 70, 60)] * 2)
    bench = [
        dataclasses.replace(_player(2025, 1, 'Backup', 12, position='WR'), starter=False),
        dataclasses.replace(_player(2025, 2, 'Sleeper', 41, position='WR'), starter=False),
    ]

    texts = _templates(wf._bench_player_facts, games, 2025, 2, bench)

    assert texts == [
        'Sleeper ({team:GSA}) scored 41 on the bench, the most by a benched player in league history.'
    ]


def test_all_play_flags_the_luckiest_start():
    games = []
    # GSA wins every week with the 3rd-best of four scores.
    for week in range(1, 4):
        games += _matchup(2025, week, 'GSA', 80, 'CGK', 70)
        games += _matchup(2025, week, 'SLS', 100, 'WJK', 90)

    texts = _templates(wf._all_play_facts, games, 2025, 3)

    assert (
        '{team:GSA} {is:GSA} 3-0 despite a 3-6 record against the whole league, '
        'the luckiest start through 3 games in league history.'
    ) in texts


def _season_with_playoffs(season, top, rest, regular_weeks=15, start=3):
    """`top` teams start `start`-0 and make the playoffs; `rest` start 0-`start`."""
    games = []
    for week in range(1, start + 1):
        for winner, loser in zip(top, rest, strict=True):
            games += _matchup(season, week, winner, 90, loser, 80)
    games += _matchup(season, regular_weeks + 1, top[0], 90, top[1], 80, bracket=wf.PLAYOFFS)
    return games


def test_playoff_odds_by_record():
    games = []
    for season in range(2019, 2025):
        games += _season_with_playoffs(season, ['GSA', 'CGK'], ['SLS', 'WJK'])
    for week in range(1, 4):
        games += _matchup(2025, week, 'GSA', 90, 'SLS', 80)
        games += _matchup(2025, week, 'CGK', 90, 'WJK', 80)

    texts = _templates(wf._playoff_odds_facts, games, 2025, 3)

    assert (
        '{team:GSA} and {team:CGK} are 3-0; every team that started 3-0 has made the playoffs '
        '(12 for 12).'
    ) in texts
    assert (
        '{team:SLS} and {team:WJK} are 0-3; no team that started 0-3 has made the playoffs '
        '(0 for 12).'
    ) in texts


def test_playoff_status_is_conservative():
    totals = {'GSA': 19.5, 'CGK': 10.0, 'SLS': 10.0, 'WJK': 10.0, 'AYP': 4.0, 'CWR': 16.0}

    status = wf._playoff_status(totals, remaining=2, bonus=0.5)

    # Only GSA can still reach CWR's 16, so both are in.
    assert status['GSA'] == status['CWR'] == 'clinched'
    # AYP's best case (7) still trails four teams' current totals.
    assert status['AYP'] == 'eliminated'
    # CGK can still reach 13 but could also finish behind four teams.
    assert 'CGK' not in status


def test_clinch_is_noted_once_the_week_it_happens():
    teams = ['GSA', 'CGK', 'SLS', 'WJK', 'AYP', 'CWR', 'RPA', 'AST', 'J/J', 'S/T']
    games = []
    for week in range(1, 16):
        games += _matchup(2025, week, 'GSA', 100, 'CGK', 50)
        # Everyone else trades wins week to week.
        for i in range(2, 10, 2):
            a, b = teams[i], teams[i + 1]
            if week % 2:
                a, b = b, a
            games += _matchup(2025, week, a, 70 + i, b, 60 + i)

    clinched = [
        week
        for week in range(1, 16)
        if any(
            t.startswith('{team:GSA} clinched')
            for t in _templates(wf._clinch_facts, games, 2025, week)
        )
    ]

    assert len(clinched) == 1 and clinched[0] < 15


def test_title_defense_start_against_earlier_defenses():
    games = []
    for season in range(2020, 2024):
        games += _matchup(season, 17, 'CGK', 90, 'SLS', 80, bracket=wf.PLAYOFFS)
        games = _with(games, **{}) + []
        games[-2] = dataclasses.replace(games[-2], title_game=True)
        games[-1] = dataclasses.replace(games[-1], title_game=True)
        for week in range(1, 4):
            games += _matchup(season + 1, week, 'CGK', 90 if week == 1 else 70, 'WJK', 80)
    games += _matchup(2024, 17, 'GSA', 90, 'SLS', 80, bracket=wf.PLAYOFFS)
    games[-2] = dataclasses.replace(games[-2], title_game=True)
    games[-1] = dataclasses.replace(games[-1], title_game=True)
    for week in range(1, 4):
        games += _matchup(2025, week, 'GSA', 60, 'WJK', 80)

    texts = _templates(wf._title_defense_facts, games, 2025, 3)

    assert texts == [
        'Defending champion {team:GSA} {is:GSA} 0-3, the worst start to a title defense in league history.'
    ]


def test_owner_milestones_follow_the_person():
    games = []
    for week in range(1, 26):
        games += _with(
            _matchup(2025, week, 'GSA', 90, 'CGK', 80),
            GSA={'owners': ('GSA',)},
            CGK={'owners': ('CGK',)},
        )

    texts = _templates(wf._owner_facts, games, 2025, 25, owner_names={'GSA': 'Griff'})

    assert texts == ['Griff reached 25 career wins, the first owner to get there.']


def test_player_loyalty_record_and_revenge_game():
    games = _league([(2025, w) for w in range(1, 12)], [(90, 80, 70, 60)] * 11)
    players = [_player(2025, w, 'Loyal Larry', 10) for w in range(1, 11)]
    players += [_player(2025, w, 'Other Guy', 10, abbrev='CGK') for w in range(1, 11)]
    players.append(_player(2025, 11, 'Loyal Larry', 10))

    assert _templates(wf._loyalty_facts, games, 2025, 11, players) == [
        'Loyal Larry made his 11th start for {team:GSA}, the most by any player for one franchise.'
    ]

    # Other Guy (tied with Larry until this week) moves to SLS and torches CGK.
    revenge = dataclasses.replace(
        _player(2025, 11, 'Other Guy', 31, abbrev='SLS'), opp_franchises=('CGK',)
    )
    texts = _templates(wf._revenge_facts, games, 2025, 11, players + [revenge])
    assert texts == [
        'Other Guy scored 31 for {team:SLS} against his old team, {team:CGK}, '
        'for whom he made 10 starts (2025).'
    ]


def test_position_group_league_record():
    games = _league([(2025, 1), (2025, 2)], [(90, 80, 70, 60)] * 2)
    players = [_player(2025, 1, f'RB {i}', 15, position='RB') for i in range(2)]
    players += [_player(2025, 2, f'RB {i}', 35, position='RB') for i in range(2)]

    texts = _templates(wf._position_group_facts, games, 2025, 2, players)

    assert texts == [
        "{team:GSA}'s RBs combined for 70, the most by any team's RBs in league history."
    ]


def test_late_pick_takes_over_the_draft_class():
    games = _league([(2025, w) for w in range(1, 5)], [(90, 80, 70, 60)] * 4)
    players = [_player(2025, w, 'First Rounder', 10, position='WR') for w in range(1, 5)]
    players += [_player(2025, w, 'Steal', 9, abbrev='CGK', position='WR') for w in range(1, 4)]
    players.append(_player(2025, 4, 'Steal', 20, abbrev='CGK', position='WR'))
    drafts = [
        wf.Draftee(2025, '2025 Offseason Draft', 'offseason', 1, 'first rounder', 'First Rounder'),
        wf.Draftee(2025, '2025 Offseason Draft', 'offseason', 6, 'steal', 'Steal'),
    ]

    texts = _templates(wf._draft_class_facts, games, 2025, 4, players, drafts=drafts)

    assert texts == [
        'Steal ({team:CGK}), a 6th-round pick, now leads the 2025 Offseason Draft class with 47 points.'
    ]


def test_rookie_season_record_fires_the_week_it_falls():
    weeks = [(2024, 1), (2025, 1), (2025, 2)]
    games = _league(weeks, [(90, 80, 70, 60)] * 3)
    players = [
        _player(2024, 1, 'Old Rookie', 30),
        _player(2025, 1, 'New Rookie', 20),
        _player(2025, 2, 'New Rookie', 15),
    ]
    rookies = {'old rookie': 2024, 'new rookie': 2025}

    texts = _templates(wf._rookie_facts, games, 2025, 2, players, rookie_seasons=rookies)
    assert (
        "New Rookie ({team:GSA}) has 35 points this season, passing Old Rookie's 30 (2024) "
        'for the most by a rookie in league history.'
    ) in texts
    assert not any(
        'passing' in t
        for t in _templates(wf._rookie_facts, games, 2025, 1, players, rookie_seasons=rookies)
    )


def test_trace_trade_reads_moves_off_the_rosters():
    timeline = {
        (2025, 11): {'george kittle': 'AST', 'dallas goedert': 'GSA', 'bench guy': 'GSA'},
        (2025, 12): {'george kittle': 'GSA', 'dallas goedert': 'AST', 'bench guy': 'GSA'},
    }
    names = {'george kittle': 'George Kittle', 'dallas goedert': 'Dallas Goedert'}
    trade = {
        'type': 'trade',
        'season': 2025,
        'week': 12,
        'message': 'To Griff: | TE George Kittle (SF) | To Anagh: | TE Dallas Goedert (PHI) | Bench Guy stays',
    }

    traced = export.trace_trade(trade, timeline, names)

    assert traced is not None and traced.label == 'Week 12, 2025'
    assert {(s.franchise, s.names) for s in traced.sides} == {
        ('GSA', ('George Kittle',)),
        ('AST', ('Dallas Goedert',)),
    }


def test_trade_lead_changing_hands():
    games = []
    for week in range(1, 4):
        games += _matchup(2025, week, 'GSA', 90, 'AST', 80)
    players = [
        _player(2025, 1, 'Kittle', 30, abbrev='GSA', position='TE'),
        _player(2025, 1, 'Goedert', 20, abbrev='AST', position='TE'),
        _player(2025, 2, 'Kittle', 0, abbrev='GSA', position='TE'),
        _player(2025, 2, 'Goedert', 5, abbrev='AST', position='TE'),
        _player(2025, 3, 'Kittle', 2, abbrev='GSA', position='TE'),
        _player(2025, 3, 'Goedert', 20, abbrev='AST', position='TE'),
    ]
    trade = wf.Trade(
        2025,
        1,
        'Week 1, 2025',
        (
            wf.TradeSide('AST', ('goedert',), ('Goedert',)),
            wf.TradeSide('GSA', ('kittle',), ('Kittle',)),
        ),
    )

    texts = _templates(wf._trade_facts, games, 2025, 3, players, trades=[trade])

    assert texts == [
        "{team:AST}'s side of the Week 1, 2025 trade with {team:GSA} (Goedert) took the lead "
        'this week, 45 to 32 in starter points since the deal (Kittle).'
    ]


def test_projection_upset_and_miss():
    games = []
    for week in range(1, 3):
        games += _with(
            _matchup(2026, week, 'GSA', 90, 'CGK', 80),
            GSA={'projected': 90.0, 'opp_projected': 85.0},
            CGK={'projected': 85.0, 'opp_projected': 90.0},
        )
    games += _with(
        _matchup(2026, 3, 'GSA', 95, 'CGK', 60),
        GSA={'projected': 80.0, 'opp_projected': 110.0},
        CGK={'projected': 110.0, 'opp_projected': 80.0},
    )

    texts = _templates(wf._projection_facts, games, 2026, 3)

    assert (
        '{team:GSA} beat {team:CGK} despite a projected 30-point deficit, '
        'the biggest upset by projection this season.'
    ) in texts
    assert (
        '{team:CGK} fell 50 short of a 110-point projection, '
        'the furthest any team has fallen short this season.'
    ) in texts


def test_series_tie_broken():
    games = []
    for week in range(1, 4):
        games += _matchup(2025, week, 'GSA', 90, 'CGK', 80)
        games += _matchup(2025, week + 3, 'GSA', 70, 'CGK', 80)
    games += _matchup(2025, 7, 'GSA', 90, 'CGK', 80)

    assert _templates(wf._head_to_head_facts, games, 2025, 7) == [
        '{team:GSA} beat {team:CGK} to break a tie in the all-time series and take a 4-3 lead.'
    ]


def test_snapped_streak_is_noted_only_the_week_it_ends():
    games = []
    for week in range(1, 6):
        games += _matchup(2025, week, 'GSA', 70, 'CGK', 80)
    games += _matchup(2025, 6, 'GSA', 90, 'CGK', 80)
    games += _matchup(2025, 7, 'GSA', 90, 'CGK', 80)

    assert any('snapped' in t for t in _templates(wf._streak_facts, games, 2025, 6))
    assert not any('snapped' in t for t in _templates(wf._streak_facts, games, 2025, 7))


def test_more_notes_cap_each_team_across_both_lists():
    facts = [wf.Fact(f'f{i}', wf.TEAM, ['AYP'], f'AYP fact {i}', 1 - i / 10) for i in range(6)]
    headline = facts[:2]

    more = wf.more_notes(facts, headline, per_team=4)

    assert [f.id for f in more] == ['f2', 'f3']
