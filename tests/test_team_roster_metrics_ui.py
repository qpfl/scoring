import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def evaluate_player_season_metrics(data_obj: dict, game_opponents: dict | None = None) -> dict:
    app = WEB_APP.read_text(encoding='utf-8')
    constant = app[
        app.index('const PPG_EXCLUDED_REASONS') : app.index('function playerUnavailableBadge')
    ]
    helper = app[
        app.index('function weekCountsTowardPpg') : app.index('function getStatsLeaders()')
    ]
    script = f"""
let data = {json.dumps(data_obj)};

// Minimal stand-in for getPlayerStatus() - only the bye branch matters here.
function getPlayerStatus(player, weekNum) {{
    const gameOpponents = {json.dumps(game_opponents or {})};
    const weekLookup = gameOpponents[String(weekNum)];
    if (weekLookup) {{
        const opponent = weekLookup[player.nfl_team];
        if (opponent && opponent.bye) return {{ status: 'bye', label: 'BYE' }};
        if (opponent) return {{ status: 'played', label: '' }};
    }}
    return {{ status: 'unknown', label: '' }};
}}

{constant}
{helper}

const metrics = getPlayerSeasonMetrics();
process.stdout.write(JSON.stringify([...metrics.entries()]));
"""
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(json.loads(result.stdout))


def make_week(week_num, teams, has_scores=True):
    matchups = []
    for i in range(0, len(teams), 2):
        matchups.append({'team1': teams[i], 'team2': teams[i + 1]})
    return {'week': week_num, 'has_scores': has_scores, 'matchups': matchups}


def team(abbrev, roster=None, taxi_squad=None):
    return {'abbrev': abbrev, 'roster': roster or [], 'taxi_squad': taxi_squad or []}


def player(name, position, score, nfl_team='BUF', **extra):
    return {'name': name, 'position': position, 'score': score, 'nfl_team': nfl_team, **extra}


def test_bye_week_excluded_from_ppg_denominator_but_total_still_includes_it():
    weeks = [
        make_week(
            1,
            [
                team('A', roster=[player('Josh Allen', 'QB', 20, nfl_team='BUF')]),
                team('B', roster=[player('Other QB', 'QB', 10, nfl_team='KC')]),
            ],
        ),
        make_week(
            2,
            [
                team('A', roster=[player('Josh Allen', 'QB', 0, nfl_team='BUF')]),
                team('B', roster=[player('Other QB', 'QB', 15, nfl_team='KC')]),
            ],
        ),
    ]
    game_opponents = {
        '1': {'BUF': {'opponent': 'MIA'}, 'KC': {'opponent': 'DEN'}},
        '2': {'BUF': {'bye': True}, 'KC': {'opponent': 'LAC'}},
    }
    metrics = evaluate_player_season_metrics({'weeks': weeks}, game_opponents)
    allen = metrics['QB|josh allen']
    assert allen['total_points'] == 20
    assert allen['weeks_rostered'] == 2
    assert allen['ppg_games'] == 1
    assert allen['ppg'] == 20


def test_flagged_unavailable_weeks_are_excluded_out_ir_pup():
    for reason in ('out', 'ir', 'pup'):
        weeks = [
            make_week(
                1,
                [
                    team('A', roster=[player('P1', 'RB', 10)]),
                    team('B', roster=[player('P2', 'RB', 5)]),
                ],
            ),
            make_week(
                2,
                [
                    team('A', roster=[player('P1', 'RB', 0, unavailable_reason=reason)]),
                    team('B', roster=[player('P2', 'RB', 8)]),
                ],
            ),
        ]
        metrics = evaluate_player_season_metrics({'weeks': weeks})
        p1 = metrics['RB|p1']
        assert p1['ppg_games'] == 1, f'reason={reason}'
        assert p1['ppg'] == 10, f'reason={reason}'


def test_backup_reason_is_kept_in_denominator():
    weeks = [
        make_week(
            1,
            [
                team('A', roster=[player('P1', 'WR', 0, unavailable_reason='backup')]),
                team('B', roster=[player('P2', 'WR', 5)]),
            ],
        ),
        make_week(
            2,
            [
                team('A', roster=[player('P1', 'WR', 10)]),
                team('B', roster=[player('P2', 'WR', 5)]),
            ],
        ),
    ]
    metrics = evaluate_player_season_metrics({'weeks': weeks})
    p1 = metrics['WR|p1']
    assert p1['ppg_games'] == 2
    assert p1['ppg'] == 5


def test_genuine_zero_with_no_flag_still_counts_as_a_played_week():
    weeks = [
        make_week(
            1,
            [
                team('A', roster=[player('P1', 'TE', 0)]),
                team('B', roster=[player('P2', 'TE', 5)]),
            ],
        ),
    ]
    metrics = evaluate_player_season_metrics({'weeks': weeks})
    p1 = metrics['TE|p1']
    assert p1['ppg_games'] == 1
    assert p1['ppg'] == 0


def test_ranks_are_one_based_points_descending_and_span_roster_and_taxi():
    weeks = [
        make_week(
            1,
            [
                team(
                    'A',
                    roster=[player('Star RB', 'RB', 30)],
                    taxi_squad=[player('Taxi RB', 'RB', 5)],
                ),
                team('B', roster=[player('Mid RB', 'RB', 15)]),
            ],
        ),
    ]
    metrics = evaluate_player_season_metrics({'weeks': weeks})
    assert metrics['RB|star rb']['position_rank'] == 1
    assert metrics['RB|mid rb']['position_rank'] == 2
    assert metrics['RB|taxi rb']['position_rank'] == 3
    assert metrics['RB|star rb']['pool_size'] == 3


def test_ranks_tiebreak_by_name_when_points_are_equal():
    weeks = [
        make_week(
            1,
            [
                team('A', roster=[player('Zed Back', 'RB', 10)]),
                team('B', roster=[player('Amy Back', 'RB', 10)]),
            ],
        ),
    ]
    metrics = evaluate_player_season_metrics({'weeks': weeks})
    assert metrics['RB|amy back']['position_rank'] == 1
    assert metrics['RB|zed back']['position_rank'] == 2


def test_ppg_is_null_not_nan_when_every_week_is_excluded():
    weeks = [
        make_week(
            1,
            [
                team('A', roster=[player('P1', 'QB', 0, unavailable_reason='out')]),
                team('B', roster=[player('P2', 'QB', 5)]),
            ],
        ),
    ]
    metrics = evaluate_player_season_metrics({'weeks': weeks})
    p1 = metrics['QB|p1']
    assert p1['ppg_games'] == 0
    assert p1['ppg'] is None


def test_seeds_from_rosters_so_unplayed_player_still_gets_a_rank():
    data_obj = {
        'weeks': [],
        'rosters': {
            'A': [player('Bench QB', 'QB', 0)],
        },
    }
    metrics = evaluate_player_season_metrics(data_obj)
    bench = metrics['QB|bench qb']
    assert bench['position_rank'] == 1
    assert bench['ppg'] is None


def test_weeks_without_scores_are_ignored():
    weeks = [
        make_week(
            1,
            [
                team('A', roster=[player('P1', 'K', 10)]),
                team('B', roster=[player('P2', 'K', 5)]),
            ],
        ),
        make_week(
            2,
            [
                team('A', roster=[player('P1', 'K', 999)]),
                team('B', roster=[player('P2', 'K', 999)]),
            ],
            has_scores=False,
        ),
    ]
    metrics = evaluate_player_season_metrics({'weeks': weeks})
    assert metrics['K|p1']['total_points'] == 10
    assert metrics['K|p1']['weeks_rostered'] == 1


def test_cache_invalidation_hooked_into_ensure_season_week():
    app = WEB_APP.read_text(encoding='utf-8')
    assert '_playerSeasonMetricsCache = { dataRef: null, value: null };' in app
    assert '_playerSeasonMetricsCache.dataRef = null;' in app
    ensure_start = app.index('async function ensureSeasonWeek')
    ensure_end = app.index('\n}\n', ensure_start)
    ensure_body = app[ensure_start:ensure_end]
    assert '_statsLeadersCache.dataRef = null;' in ensure_body
    assert '_playerSeasonMetricsCache.dataRef = null;' in ensure_body


def test_roster_table_header_and_rows_include_rank_and_ppg_columns():
    app = WEB_APP.read_text(encoding='utf-8')

    assert '<th class="pos-rank-col">Rank</th>' in app
    assert '<th class="ppg-col">PPG</th>' in app
    assert '${rosterMetricCells(player)}' in app
    assert '${rosterMetricCells(playerData)}' in app
    assert 'colspan="${weeksWithScores.length + 4}"' in app
    assert '<td><strong>TOTAL</strong></td>' in app


def test_roster_metric_cells_helper_escapes_position():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function rosterMetricCells')
    end = app.index('\n}\n', start)
    body = app[start:end]
    assert 'escapeHtml(player.position' in body
    assert 'class="pos-rank"' in body
    assert 'class="ppg"' in body


def test_roster_table_styles_cover_new_columns_desktop_and_mobile():
    styles = WEB_STYLES.read_text(encoding='utf-8')
    assert '.roster-table th.pos-rank-col,' in styles
    assert '.roster-table td.pos-rank,' in styles
    assert '.roster-table td.ppg {' in styles
    assert '.team-roster-scroll .roster-table th.pos-rank-col,' in styles
    assert '.team-roster-scroll .roster-table td.ppg {' in styles


def two_team_weeks(*p1_weeks):
    """One week per entry, with P1 on team A and a filler player on team B."""
    return [
        make_week(
            number,
            [team('A', roster=[entry]), team('B', roster=[player('Filler', entry['position'], 5)])],
        )
        for number, entry in enumerate(p1_weeks, start=1)
    ]


def test_games_played_follow_the_stats_not_a_stale_injury_flag():
    # Travis Etienne Jr., 2026: played weeks 1-3 (hurt in week 3, so flagged
    # "out" afterwards), then on IR.
    weeks = two_team_weeks(
        player('P1', 'RB', 7, found=True),
        player('P1', 'RB', 4, found=True),
        player('P1', 'RB', 6, found=True, unavailable_reason='out'),
        player('P1', 'RB', 0, found=False, unavailable_reason='reserve'),
        player('P1', 'RB', 0, found=False, unavailable_reason='ir'),
    )
    p1 = evaluate_player_season_metrics({'weeks': weeks})['RB|p1']
    assert p1['ppg_games'] == 3
    assert round(p1['ppg'], 2) == 5.67


def test_a_week_missing_from_the_stats_without_a_flag_is_not_a_game():
    # Baker Mayfield, 2026 week 6: sat out, but no designation was recorded.
    weeks = two_team_weeks(
        player('P1', 'QB', 20, found=True),
        player('P1', 'QB', 0, found=False),
    )
    p1 = evaluate_player_season_metrics({'weeks': weeks})['QB|p1']
    assert p1['ppg_games'] == 1
    assert p1['ppg'] == 20


def test_a_healthy_backups_finished_zero_still_counts_but_an_unplayed_game_does_not():
    weeks = two_team_weeks(
        player('P1', 'WR', 10, found=True),
        player('P1', 'WR', 0, found=False, unavailable_reason='backup', game_final=True),
        player('P1', 'WR', 0, found=False, unavailable_reason='backup', game_final=False),
    )
    p1 = evaluate_player_season_metrics({'weeks': weeks})['WR|p1']
    assert p1['ppg_games'] == 2
    assert p1['ppg'] == 5


def evaluate_stats_leaders(data_obj: dict) -> dict:
    app = WEB_APP.read_text(encoding='utf-8')
    constant = app[
        app.index('const PPG_EXCLUDED_REASONS') : app.index('function playerUnavailableBadge')
    ]
    off_roster = app[
        app.index('function offRosterScore') : app.index('function buildTeamTaxiHistory')
    ]
    helpers = app[
        app.index('function weekCountsTowardPpg') : app.index('function renderStatsLeaders()')
    ]
    script = f"""
let data = {json.dumps(data_obj)};
function getPlayerStatus() {{ return {{ status: 'unknown', label: '' }}; }}

{constant}
{off_roster}
{helpers}

process.stdout.write(JSON.stringify(getStatsLeaders()));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_stats_leaders_count_a_current_players_off_roster_weeks():
    # Week 1: the pickup is a free agent who scores 30 off every roster.
    # Week 2: he is drafted and scores 5; the incumbent scores 20 both weeks.
    weeks = [
        make_week(
            1,
            [
                team('A', roster=[player('Incumbent', 'RB', 20)]),
                team('B', roster=[]),
            ],
        ),
        make_week(
            2,
            [
                team('A', roster=[player('Incumbent', 'RB', 20)]),
                team('B', roster=[player('Pickup', 'RB', 5)]),
            ],
        ),
    ]
    leaders = evaluate_stats_leaders(
        {
            'weeks': weeks,
            'rosters': {
                'A': [player('Incumbent', 'RB', None)],
                'B': [player('Pickup', 'RB', None)],
            },
            'off_roster_scores': {'1': {'pickup|RB': {'score': 30, 'found': True}}},
        }
    )

    assert [(p['name'], p['total_points']) for p in leaders['RB']] == [
        ('Incumbent', 40),
        ('Pickup', 35),
    ]


def test_stats_view_loads_current_rosters_for_full_season_totals():
    # The leaders' full-season totals only count off-roster weeks for players
    # on the current rosters, which the split data tree loads on demand.
    app = WEB_APP.read_text(encoding='utf-8')
    stats_branch = app[
        app.index("} else if (view === 'stats') {") : app.index("} else if (view === 'history') {")
    ]
    assert 'ensureCurrentSeasonFiles({ rosters: true })' in stats_branch

    loader = app[
        app.index('async function ensureCurrentSeasonFiles') : app.index(
            'async function ensureSeasonWeek'
        )
    ]
    assert '_statsLeadersCache.dataRef = null;' in loader
    assert '_playerSeasonMetricsCache.dataRef = null;' in loader


def test_stats_leaders_keep_a_player_who_changed_nfl_teams_as_one_row():
    weeks = [
        make_week(
            1,
            [team('A', roster=[player('Traded WR', 'WR', 10, nfl_team='ARI')]), team('B')],
        ),
        make_week(
            2,
            [team('A', roster=[player('Traded WR', 'WR', 13, nfl_team='HOU')]), team('B')],
        ),
    ]
    leaders = evaluate_stats_leaders(
        {
            'weeks': weeks,
            'rosters': {'A': [player('Traded WR', 'WR', None, nfl_team='HOU')], 'B': []},
        }
    )

    assert [(p['name'], p['nfl_team'], p['total_points']) for p in leaders['WR']] == [
        ('Traded WR', 'HOU', 23),
    ]
