import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX, WEB_STYLES, _league, app_slice


def run_preview(body: str, league=None):
    sim = app_slice('const PLAYOFF_TRIALS', 'function renderPlayoffOdds')
    machine = app_slice('const PLAYOFF_MACHINE_TRIALS', 'function seedStripHtml')
    guide = app_slice('function computeRootingGuide', 'function rootingGuideHtml')
    renderer = app_slice('function factTemplateRenderer', '// "This Week in QPFL History"')
    preview = app_slice('const PREGAME_NOTE_KINDS', '// ---- Matchups → Preview ----')
    h2h = app_slice('function getH2HRecord', 'function renderScoreDifferential')
    script = f"""
const data = {json.dumps(league or _league())};
const currentSeason = 2026;
const LIVE_SEASON = 2026;
let currentWeek = 4;
const BRACKET_LABELS = {{ mid_bowl: 'Mid Bowl', sewer_series: 'Sewer Series', toilet_bowl: 'Toilet Bowl' }};
function sumStarterScores() {{ return 0; }}
function buildCompletedStandingsSnapshot() {{ return data.completed_standings; }}
function escapeHtml(value) {{ return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }}
function normalizeCoOwnerLabel(value) {{ return value; }}
function myTeamAbbrev() {{ return null; }}
function ordinalPlace(n) {{ return `${{n}}${{{{ 1: 'st', 2: 'nd', 3: 'rd' }}[n % 10] || 'th'}}`; }}
{sim}
{machine}
{guide}
{renderer}
{preview}
{h2h}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    # Over stdin, like run_machine: `node -e` caps the script at 128 KB on Linux.
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def test_fact_renderer_names_owners_and_agrees_verbs():
    result = run_preview("""
        const render = factTemplateRenderer({ 'S/T': 'Spencer/Tim', GSA: 'Griff' }, { GSA: { name: 'Pitts' } });
        return [render('{team:S/T} {has:S/T} won; {team:GSA} {is:GSA} up.'), render('<b>')];
    """)
    assert result == [
        'Spencer/Tim have won; <span title="Pitts">Griff</span> is up.',
        '&lt;b>',
    ]


def test_drawer_previews_unfinished_games_and_recaps_finished_ones():
    result = run_preview("""
        const mode = html => (html.match(/data-preview-mode="(\\w+)"/) || [])[1] || '';
        const open = matchupPreviewSlot('AAA', 'BBB', false);
        const final = matchupPreviewSlot('AAA', 'BBB', true);
        currentWeek = 2;  // already completed
        const played = matchupPreviewSlot('AAA', 'BBB', false);
        data.season = 2025;  // before pregame and weekly notes
        const old = matchupPreviewSlot('AAA', 'BBB', true);
        return {
            open: mode(open),
            label: open.includes('>Preview<'),
            final: mode(final),
            recapLabel: final.includes('>Recap<'),
            played: mode(played),
            old,
        };
    """)
    assert result == {
        'open': 'preview',
        'label': True,
        'final': 'recap',
        'recapLabel': True,
        'played': 'recap',
        'old': '',
    }


def _week(scores, rosters=None):
    """A finished week from (team1, score1, team2, score2) rows."""
    rosters = rosters or {}
    return {
        'week': 3,
        'has_scores': True,
        'matchups': [
            {
                'team1': {'abbrev': a, 'total_score': sa, 'roster': rosters.get(a, [])},
                'team2': {'abbrev': b, 'total_score': sb, 'roster': rosters.get(b, [])},
            }
            for a, sa, b, sb in scores
        ],
    }


def test_recap_settles_each_kind_of_check():
    week = _week(
        [('AAA', 104, 'BBB', 98), ('CCC', 120, 'DDD', 60), ('EEE', 80, 'FFF', 70)],
        {
            'AAA': [
                {'name': "Ja'Marr Chase", 'position': 'WR', 'score': 21, 'starter': True},
                {'name': 'Bench Guy', 'position': 'RB', 'score': 30, 'starter': False},
            ],
        },
    )
    result = run_preview(
        f"""
        const week = {json.dumps(week)};
        const settle = check => pregameOutcome(check, week, 3);
        return [
            settle({{ type: 'win', team: 'AAA' }}),
            settle({{ type: 'win', team: 'BBB', expect: false }}),
            settle({{ type: 'team_points', team: 'AAA', min: 100 }}),
            settle({{ type: 'top_half', team: 'AAA', expect: true }}),
            settle({{ type: 'top_half', team: 'BBB', expect: false }}),
            settle({{ type: 'player_points', team: 'AAA', player: 'JaMarr Chase', position: 'WR', min: 20 }}),
            settle({{ type: 'player_points', team: 'AAA', player: "Ja'Marr Chase", position: 'WR', min: 21, over: true }}),
            settle({{ type: 'player_points', team: 'AAA', player: 'Bench Guy', position: 'RB', min: 5 }}),
            settle({{ type: 'player_start', team: 'AAA', player: "Ja'Marr Chase", position: 'WR' }}),
            settle({{ type: 'win', team: 'ZZZ' }}),
        ];
        """
    )
    assert result == [
        {'ok': True, 'detail': 'Won 104-98.'},
        {'ok': True, 'detail': 'Lost 98-104.'},
        {'ok': True, 'detail': 'Scored 104.'},
        {'ok': True, 'detail': 'Finished 2nd of 6.'},
        {'ok': False, 'detail': 'Finished 3rd of 6.'},
        {'ok': True, 'detail': 'Scored 21.'},
        {'ok': False, 'detail': 'Scored 21.'},
        {'ok': False, 'detail': "Didn't start."},
        {'ok': True, 'detail': 'Started.'},
        None,
    ]


def test_top_half_waits_for_the_whole_week():
    week = _week([('AAA', 104, 'BBB', 98)])
    result = run_preview(
        f"""
        const week = {json.dumps(week)};
        return pregameOutcome({{ type: 'top_half', team: 'AAA' }}, {{ ...week, week: 9 }}, 9);
        """
    )
    assert result is None


def test_recap_marks_outcomes_and_keeps_unchecked_notes_plain():
    result = run_preview("""
        const render = factTemplateRenderer({}, {});
        const notes = { storylines: [
            { template: 'Kept.', check: { type: 'win', team: 'AAA' } },
            { template: 'Plain.' },
        ] };
        const outcome = note => note.check ? { ok: false, detail: 'Lost 1-2.' } : null;
        return pregameNotesHtml(notes, render, PREGAME_NOTE_KINDS, outcome);
    """)
    assert 'class="pregame-outcome is-false"' in result
    assert 'aria-label="Didn\'t happen"' in result
    assert '<span class="outcome-detail">Lost 1-2.</span>' in result
    assert '<li>Plain.</li>' in result


def test_matchup_facts_take_notes_naming_only_its_teams():
    result = run_preview("""
        const facts = { all: [
            { template: 'both', subjects: ['AAA', 'BBB'], notability: 0.4 },
            { template: 'one', subjects: ['BBB'], notability: 0.6 },
            { template: 'other game', subjects: ['AAA', 'CCC'], notability: 0.9 },
            { template: 'league', subjects: [], notability: 0.9 },
        ] };
        return matchupFacts(facts, 'AAA', 'BBB').map(f => f.template);
    """)
    assert result == ['one', 'both']


def test_recap_tape_is_as_the_teams_came_in():
    league = _league()
    league['all_weeks_loaded'] = True
    result = run_preview(
        """
        currentWeek = 3;
        // AAA's Week 2 opponent; AAA (140) beat them.
        const game = data.weeks[1].matchups.find(m => m.team1.abbrev === 'AAA' || m.team2.abbrev === 'AAA');
        const [me, them] = game.team1.abbrev === 'AAA' ? [game.team1, game.team2] : [game.team2, game.team1];
        data.hall_of_fame = {
            completed_through: { 2026: 3 },
            rivalry_records: { records: [{
                team1: 'AAA', team2: them.abbrev, team1_wins: 5, team2_wins: 2, ties: 0,
                team1_pf: 700, team2_pf: 500, games: 7,
            }] },
        };
        const rows = headToHeadTapeRows('AAA', them.abbrev, 2);
        const later = headToHeadTapeRows('AAA', them.abbrev, 4);
        return {
            mine: me.total_score,
            theirs: them.total_score,
            rows: rows.map(r => [r[0], r[1], r[2]]),
            later: later.map(r => [r[0], r[1], r[2]]),
            lines: seasonScoreLines(2).AAA.length,
        };
        """,
        league,
    )
    # The Week 2 meeting comes off the Hall of Fame series and this season's
    # record, and the season lines stop at Week 1.
    assert result['rows'][0] == ['All-time wins', 4, 2]
    assert result['rows'][-1] == [
        'Avg score in series',
        (700 - result['mine']) / 6,
        (500 - result['theirs']) / 6,
    ]
    assert not any(label == '2026 wins' for label, *_ in result['rows'])
    assert result['lines'] == 1
    # Coming into Week 4 the meeting counts.
    assert result['later'][0] == ['All-time wins', 5, 2]
    assert result['later'][1] == ['2026 wins', 1, 0]


def test_tale_of_the_tape_compares_season_lines():
    result = run_preview("""
        const lines = seasonScoreLines();
        return {
            weeks: lines.AAA.length,
            topHalf: lines.AAA.filter(g => g.topHalf).length,
            jjTopHalf: lines['J/J'].filter(g => g.topHalf).length,
            allPlay: [lines.AAA.reduce((s, g) => s + g.beat, 0), lines.AAA.reduce((s, g) => s + g.lost, 0)],
            html: taleOfTheTapeHtml('AAA', 'J/J'),
        };
    """)
    assert result['weeks'] == 3
    assert result['topHalf'] == 3
    assert result['jjTopHalf'] == 0
    assert result['allPlay'] == [27, 0]
    assert 'All-play record (every team, every week): AAA 27-0, J/J 0-27.' in result['html']
    assert '<span class="tape-value better">140.0</span>' in result['html']


def test_tale_of_the_tape_leads_with_head_to_head():
    league = _league()
    league['all_weeks_loaded'] = True
    league['hall_of_fame'] = {
        'rivalry_records': {
            'records': [
                {
                    'team1': 'J/J',
                    'team2': 'AAA',
                    'team1_wins': 2,
                    'team2_wins': 5,
                    'ties': 1,
                    'team1_pf': 640.0,
                    'team2_pf': 880.0,
                    'games': 8,
                }
            ]
        }
    }
    result = run_preview(
        """
        const html = taleOfTheTapeHtml('AAA', 'J/J');
        // No season lines yet (a week 1 preview) still shows the series.
        data.weeks = [];
        return { html, early: taleOfTheTapeHtml('AAA', 'J/J'), none: taleOfTheTapeHtml('AAA', 'BBB') };
        """,
        league,
    )
    html = result['html']
    assert '<span class="tape-label">All-time wins (1 tie)</span>' in html
    assert '<span class="tape-value better">5</span>' in html
    assert '<span class="tape-label">Avg score in series</span>' in html
    assert '<span class="tape-value better">110.0</span>' in html
    assert '<span class="tape-value ">80.0</span>' in html
    assert html.index('tape-h2h') < html.index('Average score')
    assert 'All-time wins' in result['early'] and 'Average score' not in result['early']
    assert result['none'] == ''


def test_h2h_badge_leaves_cards_that_have_a_preview():
    app = WEB_APP.read_text(encoding='utf-8')
    assert app.count("matchupHasPreview(false) ? '' : renderH2HBadge(") == 1
    assert app.count("matchupHasPreview(matchupFinal) ? '' : renderH2HBadge(") == 1


def test_stakes_show_both_teams_odds_with_a_win_and_a_loss():
    result = run_preview("""
        const ctx = preparePlayoffSim();
        const game = ctx.weeksRemaining[4].find(m => m.team1Abbrev === 'EEE' || m.team2Abbrev === 'EEE');
        const stakes = matchupStakes(ctx, 4, game.team1Abbrev, game.team2Abbrev);
        return {
            teams: stakes.stakes.map(s => s.abbrev),
            ordered: stakes.stakes.every(s => s.win.odds >= s.lose.odds),
            later: matchupStakes(ctx, 99, game.team1Abbrev, game.team2Abbrev),
        };
    """)
    assert result['ordered'] is True
    assert 'EEE' in result['teams']
    assert result['later'] is None


def test_notes_render_by_kind_and_skip_empty_kinds():
    result = run_preview("""
        const render = factTemplateRenderer({}, {});
        return pregameNotesHtml({
            storylines: [{ template: '{team:AAA} won the last meeting.' }],
            revenge: [],
            records: [{ template: 'A record note.' }],
            milestones: [],
        }, render);
    """)
    assert '<h4>Storylines</h4>' in result
    assert '<h4>Record watch</h4>' in result
    assert 'Revenge' not in result
    assert 'Milestones' not in result


def test_preview_tab_and_card_hooks_are_wired():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')
    assert 'data-parent="matchups" data-subview="preview"' in html
    assert 'id="matchups-preview-container"' in html
    # Both the scheduled-week and scored-week card builders get a drawer, and
    # both render paths fill them.
    assert app.count('${matchupPreviewSlot(') == 2
    assert app.count('hydrateMatchupPreviews(container, currentSeason, currentWeek)') == 2
    assert "if (subview === 'preview') renderMatchupsPreviewTab()" in app
    assert "(view === 'matchups' && sub === 'preview')" in app
    assert 'data/seasons/${season}/pregame/week_${week}.json' in app
    assert '.matchup-preview {' in styles


def test_stakes_lines_cap_odds_and_only_claim_certainty_when_clinched():
    result = run_preview("""
        const open = (odds, extra = {}) => ({ odds, clinched: false, eliminated: false, ...extra });
        return [
            // 998 of 1,000 simulations is not a clinch.
            stakesLine({ abbrev: 'CGK', win: open(0.998), lose: open(0.98) }),
            stakesLine({ abbrev: 'GSA', win: open(1, { clinched: true }), lose: open(0.7) }),
            stakesLine({ abbrev: 'AYP', win: open(0.03), lose: open(0, { eliminated: true }) }),
            stakesLine({ abbrev: 'S/T', win: open(1, { clinched: true }), lose: open(1, { clinched: true }) }),
        ];
    """)
    assert result == [
        '<strong>CGK</strong>: 99% playoff odds with a win, 98% with a loss.',
        'A win clinches a playoff spot for <strong>GSA</strong>; a loss leaves them at 70%.',
        'A loss eliminates <strong>AYP</strong>; a win keeps them alive at 3%.',
        '<strong>S/T</strong> is in either way.',
    ]


def test_long_note_lists_fold_past_the_first_four():
    result = run_preview("""
        const render = factTemplateRenderer({}, {});
        const notes = { storylines: [1, 2, 3, 4, 5, 6].map(n => ({ template: `Note ${n}.` })) };
        return pregameNotesHtml(notes, render);
    """)
    shown, folded = result.split('<details')
    assert 'Note 4.' in shown and 'Note 5.' not in shown
    assert '<summary>2 more</summary>' in folded and 'Note 6.' in folded


def test_weekly_section_leaves_matchup_notes_to_the_recaps():
    section = app_slice('async function renderMatchupWeeklyFacts', 'const HOF_WEEKLY_FACTS_TEASER')
    assert "if (matchupDrawerMode(true) === 'recap')" in section
    assert 'matchupFacts(facts, m.team1?.abbrev, m.team2?.abbrev)' in section
    # The Hall of Fame teaser still shows the week's headline notes.
    teaser = app_slice(
        'async function renderWeeklyFactsCard', '// null until the view first renders'
    )
    assert 'matchupFacts' not in teaser
