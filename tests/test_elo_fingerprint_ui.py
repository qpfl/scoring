import json
import subprocess

from tests.test_playoff_machine import WEB_APP, app_slice


def run_js(body: str, league: dict | None = None):
    section = app_slice(
        '// ====== ELO, FINGERPRINTS AND NEMESES ======',
        "// A team's Hall of Fame (Teams page), built from the same pieces as the",
    )
    tape = app_slice("// Both sides' Elo coming into the week", 'function tapeRowsHtml(rows)')
    script = f"""
const data = {json.dumps(league or {})};
function escapeHtml(value) {{ return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }}
function myTeamClass() {{ return ''; }}
function myTeamAbbrev() {{ return 'GSA'; }}
function normalizeCoOwnerLabel(value) {{ return value; }}
function teamProfileButton(abbrev, name) {{ return name; }}
function hofFranchiseIndex() {{ return data.hall_of_fame_records?.franchises || []; }}
{section}
{tape}
const result = (() => {{ {body} }})();
process.stdout.write(JSON.stringify(result));
"""
    output = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def test_nemesis_and_victim_need_four_meetings():
    result = run_js("""
        const pair = nemesisAndVictim([
            { name: 'A', wins: 1, losses: 3, ties: 0 },
            { name: 'B', wins: 0, losses: 3, ties: 0 },  // only three games
            { name: 'C', wins: 5, losses: 1, ties: 0 },
            { name: 'D', wins: 2, losses: 2, ties: 0 },
        ]);
        return [pair.nemesis.name, pair.victim.name, nemesisAndVictim([{ name: 'A', wins: 4, losses: 0 }])];
    """)
    assert result == ['A', 'C', None]


def test_team_page_series_sum_across_the_franchise_owners():
    result = run_js("""
        return franchiseOpponentRecords([
            { ownerId: 'RCP', opponentId: 'GSA', opponent: 'Griff', wins: 1, losses: 2, ties: 0 },
            { ownerId: 'JDK', opponentId: 'GSA', opponent: 'Griff', wins: 2, losses: 1, ties: 1 },
        ]);
    """)
    assert result == [
        {'opponent': 'GSA', 'name': 'Griff', 'wins': 3, 'losses': 3, 'ties': 1},
    ]


def test_elo_tape_rows_follow_the_card_order():
    notes = {
        'team1': 'GSA',
        'team2': 'CGK',
        'elo': {'team1': 1600, 'team2': 1500, 'team1_win_prob': 0.64},
    }
    result = run_js(f"""
        const notes = {json.dumps(notes)};
        const fmt = rows => rows.map(([label, a, b, , f]) => [label, f(a), f(b)]);
        return [fmt(eloTapeRows('GSA', 'CGK', notes)), fmt(eloTapeRows('CGK', 'GSA', notes)), eloTapeRows('GSA', 'CGK', {{}})];
    """)
    assert result[0] == [['Elo rating', '1,600', '1,500'], ['Elo win chance', '64%', '36%']]
    assert result[1] == [['Elo rating', '1,500', '1,600'], ['Elo win chance', '36%', '64%']]
    assert result[2] == []


def test_elo_highlights_mine_and_the_leader_and_keeps_colours():
    league = {
        'hall_of_fame_records': {
            'franchises': [
                {'abbrev': 'CGK', 'elo': 1700, 'elo_series': [[2025, 1, 1700]]},
                {'abbrev': 'GSA', 'elo': 1500, 'elo_series': [[2025, 1, 1500]]},
                {'abbrev': 'RPA', 'elo': 1400, 'elo_series': [[2025, 1, 1400]]},
                {'abbrev': 'AST', 'elo': 1300, 'elo_series': [[2025, 1, 1300]]},
            ]
        }
    }
    result = run_js(
        """
        const franchises = hofFranchiseIndex();
        const start = [...eloSlots(franchises)];
        toggleEloFranchise('RPA');
        toggleEloFranchise('AST');  // over the limit: ignored
        toggleEloFranchise('GSA');  // frees slot 0 without repainting the rest
        toggleEloFranchise('AST');
        return { start, after: [...eloChartState.slots] };
        """,
        league,
    )
    assert result['start'] == [['GSA', 0], ['CGK', 1]]
    assert result['after'] == [['CGK', 1], ['RPA', 2], ['AST', 0]]


def test_fingerprint_overlays_a_compared_owner():
    def trait(key, pct, detail):
        return {'key': key, 'label': key.title(), 'percentile': pct, 'detail': detail}

    league = {
        'hall_of_fame_records': {
            'owner_profiles': {
                'GSA': {
                    'code': 'GSA',
                    'name': 'Griff',
                    'fingerprint': [
                        trait('scoring', 96, '95.0 PPG'),
                        trait('playoffs', None, None),
                    ],
                },
                'CGK': {
                    'code': 'CGK',
                    'name': 'Connor',
                    'fingerprint': [
                        trait('scoring', 88, '93.2 PPG'),
                        trait('playoffs', 62, '5-4 in the playoffs'),
                    ],
                },
            }
        }
    }
    html = run_js(
        """
        hofFingerprintCompare = 'CGK';
        return hofFingerprintHtml(data.hall_of_fame_records.owner_profiles.GSA);
        """,
        league,
    )
    assert 'style="width:96%"' in html and 'style="width:88%"' in html
    assert '<option value="CGK" selected>Connor</option>' in html
    assert '88th · 93.2 PPG' in html
    assert 'No games yet' in html


def test_phase7_is_wired_into_the_views():
    app = WEB_APP.read_text(encoding='utf-8')
    assert "['hof-elo', 'Elo Ratings', hofEloHtml(hofFranchiseIndex())]," in app
    assert '    bindEloChart(container);\n    bindFingerprintCompare(container);' in app
    assert '${hofFingerprintHtml(profile)}' in app
    assert 'nemesesHtml(nemesisAndVictim(rows), row => hofOwnerLink(row.opponent, row.name))' in app
    assert 'nemesesHtml(nemesisAndVictim(franchiseOpponentRecords(ownerHeadToHead))' in app
    assert '        playerNemesesCard(franchise),' in app
    assert '...eloTapeRows(team1, team2, matchupNotes),' in app
