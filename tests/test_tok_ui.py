"""QPFLTok (web/tok.js): feed order, NEW state, the week cards and the page wiring."""

import json
import re
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX, WEB_STYLES

WEB_CHARTS = WEB_APP.parent / 'charts.js'
WEB_TOK = WEB_APP.parent / 'tok.js'


def run_tok(body: str):
    script = f"""
{WEB_CHARTS.read_text(encoding='utf-8')}
{WEB_TOK.read_text(encoding='utf-8')}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


CARDS = """[
    { id: 'evergreen', version: 'a', interest: 0.95 },
    { id: 'timely', version: 'a', interest: 0.1, timely: true },
    { id: 'mine', version: 'a', interest: 0.5, involves: ['GSA'] },
    { id: 'seen-timely', version: 'v2', interest: 1, timely: true },
]"""


def test_feed_puts_unseen_timely_cards_first_and_seen_cards_last():
    order = run_tok(f"""
        return buildTokFeed({CARDS}, {{ dateKey: '2026-11-18', seen: {{ 'seen-timely': 'v2' }} }})
            .map(c => c.id + (c.isNew ? '*' : ''));
    """)
    assert order[0] == 'timely*'
    assert order[-1] == 'seen-timely'
    assert set(order[1:3]) == {'evergreen*', 'mine*'}


def test_spotlight_lifts_the_cards_about_that_team():
    result = run_tok(f"""
        const plain = buildTokFeed({CARDS}, {{ dateKey: '2026-11-18' }}).map(c => c.id);
        const spot = buildTokFeed({CARDS}, {{ dateKey: '2026-11-18', spotlight: 'GSA' }}).map(c => c.id);
        return {{ plain, spot }};
    """)
    assert result['spot'].index('mine') < result['spot'].index('evergreen')
    assert result['plain'].index('evergreen') < result['plain'].index('mine')


def test_feed_order_is_stable_within_a_day():
    result = run_tok(f"""
        const order = key => buildTokFeed({CARDS}, {{ dateKey: key }}).map(c => c.id).join();
        return [order('2026-11-18'), order('2026-11-18')];
    """)
    assert result[0] == result[1]


def test_a_card_is_new_again_when_its_data_changes():
    assert run_tok("""
        return [
            tokIsNew({ id: 'x', version: '2026-recap-10' }, { x: '2026-recap-10' }),
            tokIsNew({ id: 'x', version: '2026-recap-11' }, { x: '2026-recap-10' }),
            tokIsNew({ id: 'x', version: 'a' }, null),
        ];
    """) == [False, True, True]


def test_thanksgiving_and_holiday_slates():
    result = run_tok("""
        const times = {
            '12': { DET: '2026-11-26T18:00:00+00:00', CHI: '2026-11-26T18:00:00+00:00',
                    // 8:20 PM Eastern on Thanksgiving is the 27th in UTC.
                    DAL: '2026-11-27T01:20:00+00:00', NYG: '2026-11-29T18:00:00+00:00' },
            '16': { KC: '2026-12-25T18:00:00+00:00' },
        };
        return {
            dates: [tokThanksgiving(2026), tokThanksgiving(2027)],
            soon: tokUpcomingHoliday(times, new Date('2026-11-18T12:00:00Z')),
            early: tokUpcomingHoliday(times, new Date('2026-11-01T12:00:00Z')),
            xmas: tokUpcomingHoliday(times, new Date('2026-12-20T12:00:00Z'))?.key,
        };
    """)
    assert result['dates'] == ['2026-11-26', '2027-11-25']
    assert result['soon']['key'] == 'thanksgiving' and result['soon']['week'] == 12
    assert sorted(result['soon']['teams']) == ['CHI', 'DAL', 'DET']
    assert result['early'] is None
    assert result['xmas'] == 'christmas'


def test_milestone_progress_parses_the_pregame_template():
    assert run_tok("""
        return [
            tokParseMilestone('Evan McPherson needs 1 point for 250 career points as a QPFL starter.'),
            tokParseMilestone('Jakob needs 10 points for 5,000 career points.'),
            tokParseMilestone('Something else entirely.'),
        ];
    """) == [
        {'need': 1, 'target': 250, 'pct': 249 / 250},
        {'need': 10, 'target': 5000, 'pct': 4990 / 5000},
        None,
    ]


CTX = """{
    live: true, season: 2026, completedWeek: 10, upcomingWeek: 11,
    names: { GSA: 'Griff', SLS: 'Stephen', CGK: 'Kaminska', AST: 'Anagh' },
    teams: {},
    recapWeek: { matchups: [
        { team1: { abbrev: 'SLS', total_score: 100 }, team2: { abbrev: 'GSA', total_score: 95 } },
        { team1: { abbrev: 'CGK', total_score: 121 }, team2: { abbrev: 'AST', total_score: 88 } },
    ] },
    facts: { facts: { recaps: [{ team1: 'SLS', team2: 'GSA', notes: [{ template: 'Close <one>.' }] }] },
             headline: [{ template: 'A note', subjects: ['CGK'] }], rest: [] },
    pregame: { notes: { matchups: [
        { team1: 'GSA', team2: 'AST', storylines: [{ template: 'Story', notability: 0.5 }],
          records: [{ template: 'Record', notability: 0.7, subjects: ['GSA'] }],
          milestones: [{ template: 'X needs 1 point for 250 career points.', notability: 0.4, subjects: ['GSA'] }] },
    ] } },
    gameTimes: {}, gameOpponents: {}, rosters: {}, now: new Date('2026-11-18T12:00:00Z'),
    rooting: team => `<p>root ${team}</p>`,
}"""


def test_week_cards_build_from_existing_data():
    result = run_tok(f"""
        const cards = collectTokCards({CTX}, 'GSA');
        const byId = Object.fromEntries(cards.map(c => [c.id, c]));
        return {{
            ids: cards.map(c => c.id).sort(),
            recapCaption: byId['week-recap'].caption,
            recapBody: byId['week-recap'].body(),
            rooting: byId['week-rooting'].body(),
            records: byId['week-records'].involves,
            milestone: byId['week-milestones'].body(),
        }};
    """)
    assert result['ids'] == [
        'week-milestones',
        'week-numbers',
        'week-recap',
        'week-records',
        'week-rooting',
        'week-storylines',
    ]
    assert result['recapCaption'] == '💥 Kaminska won by 33'
    # The spotlight team's game comes first and is highlighted; note text is escaped.
    body = result['recapBody']
    assert body.index('Stephen') < body.index('Kaminska')
    assert 'tok-game is-highlight' in body and 'Close &lt;one&gt;.' in body
    assert result['rooting'] == '<p>root GSA</p>'
    assert result['records'] == ['GSA']
    assert '>99%</text>' in result['milestone']


def test_week_cards_stay_out_of_historical_seasons_and_without_a_spotlight():
    result = run_tok(f"""
        const ctx = {CTX};
        return {{
            historical: collectTokCards({{ ...ctx, live: false }}, 'GSA').map(c => c.id),
            noSpotlight: collectTokCards(ctx, null).map(c => c.id).includes('week-rooting'),
        }};
    """)
    assert result['historical'] == []
    assert result['noSpotlight'] is False


def test_holiday_card_counts_rostered_players_in_holiday_games():
    result = run_tok(f"""
        const ctx = {{ ...{CTX},
            gameTimes: {{ '12': {{ DET: '2026-11-26T18:00:00+00:00', CHI: '2026-11-26T18:00:00+00:00' }} }},
            gameOpponents: {{ '12': {{ DET: {{ opponent: 'CHI', is_home: true }}, CHI: {{ opponent: 'DET', is_home: false }} }} }},
            rosters: {{
                GSA: [{{ name: 'Jahmyr Gibbs', nfl_team: 'DET' }}, {{ name: 'Taxi Guy', nfl_team: 'CHI', taxi: true }}],
                CGK: [{{ name: 'Chicago Bears', nfl_team: 'CHI' }}, {{ name: 'DJ Moore', nfl_team: 'CHI' }}],
                AST: [{{ name: 'Josh Allen', nfl_team: 'BUF' }}],
            }},
        }};
        const card = collectTokCards(ctx, 'GSA').find(c => c.id === 'week-holiday');
        return {{ caption: card.caption, title: card.title, involves: card.involves, pill: card.pill }};
    """)
    assert result['title'] == 'Who plays on Thanksgiving'
    assert result['pill'] == 'HOLIDAY'
    assert result['caption'] == '🦃 THANKSGIVING, 11/26: CHI @ DET'
    assert result['involves'] == ['CGK', 'GSA']


def test_card_markup_has_pills_share_and_full_chart_links():
    html = run_tok("""
        return tokCardHtml({ id: 'week-records', family: 'week', title: 'Record watch', meta: '2026 · WK 11',
            caption: '👀 3 records', isNew: true, involves: ['GSA'],
            home: { view: 'matchups', subview: 'preview', anchor: 'chart-x' } }, 0,
            { spotlight: 'GSA', names: { GSA: 'Griff' } });
    """)
    assert 'data-tok-id="week-records"' in html
    assert 'tok-pill-new' in html and '📍 Griff' in html
    assert 'href="#matchups/preview?section=chart-x"' in html
    assert 'data-tok-action="share"' in html
    assert 'Swipe up for more' in html


def test_qpfltok_is_wired_into_the_page():
    index = WEB_INDEX.read_text(encoding='utf-8')
    assert (
        index.index('src="charts.js"') < index.index('src="tok.js"') < index.index('src="app.js"')
    )
    assert '<div id="tok-view" class="view-container"' in index
    assert '<a href="#tok" class="nav-btn" data-view="tok">QPFLTok</a>' in index
    assert 'id="home-tok-teaser"' in index
    app = WEB_APP.read_text(encoding='utf-8')
    assert 'tok: subview => renderTok(subview),' in app
    assert "const LIVE_SEASON_VIEWS = new Set(['manage', 'tok']);" in app
    assert "document.body.classList.toggle('tok-mode', view === 'tok');" in app
    styles = WEB_STYLES.read_text(encoding='utf-8')
    assert 'scroll-snap-type: y mandatory' in styles
    assert 'scroll-snap-stop: always' in styles


def test_tok_js_names_do_not_clash_with_other_scripts():
    tok = WEB_TOK.read_text(encoding='utf-8')
    others = WEB_APP.read_text(encoding='utf-8') + WEB_CHARTS.read_text(encoding='utf-8')
    names = re.findall(r'^(?:async )?(?:function|const|let) ([A-Za-z_]+)', tok, re.M)
    clashes = [
        n
        for n in names
        if re.search(rf'^(?:async )?(?:function|const|let|var) {n}\b', others, re.M)
    ]
    assert names and clashes == []
