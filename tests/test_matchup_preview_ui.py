import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX, WEB_STYLES, _league, app_slice


def run_preview(body: str, league=None):
    sim = app_slice('const PLAYOFF_TRIALS', 'function renderPlayoffOdds')
    machine = app_slice('const PLAYOFF_MACHINE_TRIALS', 'function seedStripHtml')
    guide = app_slice('function computeRootingGuide', 'function rootingGuideHtml')
    renderer = app_slice('function factTemplateRenderer', '// "This Week in QPFL History"')
    preview = app_slice('const PREGAME_NOTE_KINDS', '// ---- Matchups → Preview ----')
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
{sim}
{machine}
{guide}
{renderer}
{preview}
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


def test_preview_slot_only_for_unfinished_live_weeks():
    result = run_preview("""
        const open = matchupPreviewSlot('AAA', 'BBB', false);
        const final = matchupPreviewSlot('AAA', 'BBB', true);
        currentWeek = 2;  // already completed
        const played = matchupPreviewSlot('AAA', 'BBB', false);
        return { open: open.includes('data-preview-teams="AAA|BBB"'), final, played };
    """)
    assert result == {'open': True, 'final': '', 'played': ''}


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
