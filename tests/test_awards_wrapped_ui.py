import json
import subprocess

from tests.test_playoff_machine import WEB_APP, WEB_INDEX, app_slice


def run_js(body: str):
    awards = app_slice(
        '// Weekly Awards (scripts/weekly_awards.py)', 'const HOF_WEEKLY_FACTS_TEASER'
    )
    wrapped = app_slice(
        '// ====== SEASON WRAPPED ======',
        "// A team's Hall of Fame (Teams page), built from the same pieces as the",
    )
    script = f"""
const LIVE_SEASON = 2026;
function escapeHtml(value) {{ return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }}
function hofNumber(value) {{ return String(value); }}
function myTeamClass(team) {{ return team === 'GSA' ? 'is-my-team' : ''; }}
let me = 'GSA';
function myTeamAbbrev() {{ return me; }}
function franchiseCodesForStintTeam(team) {{ return team === 'CGK/SRY' ? ['CGK', 'S/T'] : [team]; }}
function hofFranchiseFor(team) {{ return franchiseCodesForStintTeam(team)[0]; }}
function seasonAwareRoute(route, season) {{ return `${{route}}?year=${{season}}`; }}
const files = {{}};
async function fetchJsonResource(path) {{ return files[path] || null; }}
const slots = {{}};
const document = {{ getElementById: id => slots[id] }};
{awards}
{wrapped}
(async () => {{
    const result = await (async () => {{ {body} }})();
    process.stdout.write(JSON.stringify(result));
}})();
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def test_weekly_awards_card_renders_each_award():
    html = run_js("""
        const facts = { week_label: 'Week 9', awards: [
            { key: 'top_score', title: 'Top Score', team: 'GSA', value: 121, unit: 'pts', subject: '{team:GSA}', detail: 'beat {team:AST} 121-89' },
            { key: 'blowout', title: 'Biggest Blowout', team: 'GSA', value: 32, unit: 'margin', subject: '{team:GSA}', detail: 'beat {team:AST} 121-89' },
        ] };
        const render = t => t.replace(/\\{team:([^}]+)\\}/g, '$1');
        return [weeklyAwardsHtml(facts, render, 2026, 9), weeklyAwardsHtml({ awards: [] }, render, 2026, 9)];
    """)
    assert 'Week 9 · 2026' in html[0]
    assert '<span class="weekly-award-figure">121 pts</span>' in html[0]
    assert '<span class="weekly-award-figure">by 32</span>' in html[0]
    assert 'weekly-award is-my-team' in html[0]
    assert html[1] == ''


def test_wrapped_finds_a_shared_season_team_for_either_franchise():
    result = run_js("""
        const wrapped = { teams: { 'CGK/SRY': { team: 'CGK/SRY' }, GSA: { team: 'GSA' } } };
        return [wrappedTeamFor(wrapped, 'S/T')?.team, wrappedTeamFor(wrapped, 'CGK')?.team, wrappedTeamFor(wrapped, 'AST')];
    """)
    assert result == ['CGK/SRY', 'CGK/SRY', None]


def test_wrapped_banner_runs_for_two_weeks():
    result = run_js("""
        const out = [];
        for (const daysAgo of [3, 20]) {
            wrappedCache.clear();
            files['data/seasons/2026/wrapped.json'] = {
                created_at: new Date(Date.now() - daysAgo * 86400000).toISOString(), champion: 'CGK',
            };
            slots['home-wrapped-banner'] = { innerHTML: 'stale' };
            await renderWrappedBanner();
            out.push(slots['home-wrapped-banner'].innerHTML);
        }
        return out;
    """)
    assert '2026 Wrapped is here' in result[0]
    assert '#teams/history/GSA?year=2026' in result[0]
    assert result[1] == ''


def test_awards_and_wrapped_are_wired():
    app = WEB_APP.read_text(encoding='utf-8')
    html = WEB_INDEX.read_text(encoding='utf-8')
    assert '<div id="home-wrapped-banner"></div>' in html
    assert '<div id="matchup-weekly-awards" class="matchup-weekly-awards-slot"></div>' in app
    assert (
        'awardsSlot.innerHTML = weeklyAwardsHtml(notes.facts, notes.renderFact, season, week);'
        in app
    )
    assert '<div id="team-wrapped" class="team-wrapped-slot"></div>' in app
    assert 'renderTeamWrapped(Number(data.season ?? currentSeason), currentTeam)' in app
    assert '    renderWrappedBanner().catch(() => {});' in app
