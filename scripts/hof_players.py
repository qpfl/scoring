"""Hall of Fame player honors: leaderboards, awards and championship rings.

Points are what a player scored in QPFL starting lineups (playoffs included),
the same measure the record book uses, so a leaderboard and a record always
agree. Season awards only go to seasons that have crowned a champion.

Manual honors (MVPs and any other hand-picked awards) come from
`web/data/shared/manual_honors.json`:

    "mvps": [{"year": 2024, "player": "Saquon Barkley", "position": "RB", "team": "GSA"}],
    "player_awards": [{"year": 2024, "player": "...", "position": "WR", "title": "..."}]
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable

from qpfl.weekly_facts import PlayerGame, TeamGame

POSITIONS = ('QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL')
CAREER_TOP = 25
SEASON_TOP = 10
SEASON_POSITION_TOP = 5
PPG_MIN_STARTS = 16
RINGS_TOP = 25
FIRST_TEAM = 'First-Team All-QPFL'
SECOND_TEAM = 'Second-Team All-QPFL'


def _totals(
    games: list[PlayerGame],
    profile_key_for: Callable[[str], str],
    name_for: Callable[[str], str | None] = lambda key: None,
) -> list[dict]:
    rows: dict[str, dict] = {}
    for p in sorted(games, key=lambda p: p.order):
        key = profile_key_for(p.player_key)
        row = rows.setdefault(
            key,
            {
                'player': p.name,
                'profile_key': key,
                'position': p.position,
                'points': 0.0,
                'starts': 0,
                'team_starts': Counter(),
            },
        )
        row['player'] = p.name
        row['points'] += p.score
        row['starts'] += 1
        row['team_starts'][p.abbrev] += 1
    result = []
    for row in rows.values():
        team_starts = row.pop('team_starts')
        row['player'] = name_for(row['profile_key']) or row['player']
        row['points'] = round(row['points'], 1)
        row['ppg'] = round(row['points'] / row['starts'], 1)
        # The team he started for most, for a leaderboard's context.
        row['team'] = team_starts.most_common(1)[0][0]
        result.append(row)
    return result


def _top(rows: list[dict], key: str, limit: int) -> list[dict]:
    ordered = sorted(rows, key=lambda r: (-r[key], r['player']))[:limit]
    return [{'rank': i + 1, **row} for i, row in enumerate(ordered)]


def _by_position(rows: list[dict], key: str, limit: int, overall: int) -> dict[str, list[dict]]:
    boards = {'ALL': _top(rows, key, overall)}
    for position in POSITIONS:
        picked = [r for r in rows if r['position'] == position]
        if picked:
            boards[position] = _top(picked, key, limit)
    return boards


def _season_slots(games: list[PlayerGame]) -> dict[str, int]:
    """How many of each position a lineup started that season: the most
    common count across every team-week."""
    per_lineup: dict[tuple, Counter] = defaultdict(Counter)
    for p in games:
        per_lineup[(p.week, p.abbrev)][p.position] += 1
    slots: dict[str, int] = {}
    for position in POSITIONS:
        counts = Counter(lineup[position] for lineup in per_lineup.values() if lineup[position])
        if counts:
            slots[position] = counts.most_common(1)[0][0]
    return slots


def franchise_lineups(
    started: list[PlayerGame],
    seasons: set[int],
    profile_key_for: Callable[[str], str],
    name_for: Callable[[str], str | None] = lambda key: None,
) -> dict[str, list[dict]]:
    """Each franchise's all-time starting lineup: the best single seasons a
    player had for it, one season per player. A season only counts if he
    started most of the franchise's games that year (more than half), so a
    hot month doesn't make the team."""
    games = [p for p in started if p.season in seasons]
    slots: dict[str, int] = {}
    for season in seasons:
        for position, count in _season_slots([p for p in games if p.season == season]).items():
            slots[position] = max(slots.get(position, 0), count)

    team_weeks: dict[tuple[str, int], set[int]] = defaultdict(set)
    rows: dict[tuple[str, int, str], dict] = {}
    for p in sorted(games, key=lambda p: p.order):
        key = profile_key_for(p.player_key)
        for franchise in p.franchises:
            team_weeks[(franchise, p.season)].add(p.week)
            row = rows.setdefault(
                (franchise, p.season, key),
                {
                    'player': p.name,
                    'profile_key': key,
                    'position': p.position,
                    'season': p.season,
                    'team': p.abbrev,
                    'points': 0.0,
                    'starts': 0,
                },
            )
            row['points'] += p.score
            row['starts'] += 1

    by_franchise: dict[str, list[dict]] = defaultdict(list)
    for (franchise, season, key), row in rows.items():
        team_games = len(team_weeks[(franchise, season)])
        if row['starts'] * 2 <= team_games:
            continue
        by_franchise[franchise].append(
            {
                **row,
                'player': name_for(key) or row['player'],
                'points': round(row['points'], 1),
                'ppg': round(row['points'] / row['starts'], 1),
                'team_games': team_games,
            }
        )

    lineups: dict[str, list[dict]] = {}
    for franchise, candidates in sorted(by_franchise.items()):
        candidates.sort(key=lambda r: (-r['points'], r['season'], r['player']))
        lineup = []
        for position in POSITIONS:
            picked: list[str] = []
            for row in candidates:
                if len(picked) == slots.get(position, 0):
                    break
                if row['position'] != position or row['profile_key'] in picked:
                    continue
                picked.append(row['profile_key'])
                lineup.append({'slot': position, **row})
        lineups[franchise] = lineup
    return lineups


def lineup_standings(lineups: dict[str, list[dict]]) -> dict[str, dict]:
    """Each all-time lineup's points per game (the sum of its players' PPG in
    their chosen seasons) and where it ranks among the franchises' lineups."""
    ppg = {
        franchise: round(sum(r['points'] / r['starts'] for r in lineup), 1)
        for franchise, lineup in lineups.items()
        if lineup
    }
    ordered = sorted(ppg.values(), reverse=True)
    return {
        franchise: {'ppg': value, 'rank': ordered.index(value) + 1, 'of': len(ordered)}
        for franchise, value in ppg.items()
    }


def build_player_honors(
    team_games: list[TeamGame],
    player_games: list[PlayerGame],
    champions: dict[int, str],
    manual_honors: dict,
    profile_key_for: Callable[[str], str],
    resolve_name: Callable[[str, str | None], str],
    name_for: Callable[[str], str | None] = lambda key: None,
) -> tuple[dict, dict[str, list[dict]]]:
    """The Players tab's data, plus each profile key's awards to show on the
    player's profile. `name_for` gives a profile's display name, so a player
    reads the same everywhere however a week's roster spelled him."""
    started = [p for p in player_games if p.starter]
    awards: dict[str, list[dict]] = defaultdict(list)

    # Championship rings: on the champion's roster for the title game,
    # starter or bench, like the NFL (the taxi squad isn't the roster).
    title_weeks = {
        (g.season, g.week, g.abbrev)
        for g in team_games
        if g.title_game and champions.get(g.season) == g.abbrev
    }
    rings: dict[str, dict] = {}
    for p in sorted(player_games, key=lambda p: p.order):
        if (p.season, p.week, p.abbrev) not in title_weeks:
            continue
        key = profile_key_for(p.player_key)
        row = rings.setdefault(
            key,
            {
                'player': name_for(key) or p.name,
                'profile_key': key,
                'position': p.position,
                'rings': 0,
                'seasons': [],
                'teams': [],
            },
        )
        if p.season in row['seasons']:
            continue
        row['rings'] += 1
        row['seasons'].append(p.season)
        if p.abbrev not in row['teams']:
            row['teams'].append(p.abbrev)
        awards[key].append({'year': p.season, 'title': 'QPFL Champion'})

    # Season honors for every season with a champion.
    position_leaders: dict[str, list[dict]] = {}
    all_qpfl: dict[str, dict[str, list[dict]]] = {}
    selections: dict[str, dict] = {}
    season_boards: dict[str, dict] = {}
    for season in sorted({p.season for p in started}):
        games = [p for p in started if p.season == season]
        totals = _totals(games, profile_key_for, name_for)
        season_boards[str(season)] = _by_position(totals, 'points', SEASON_POSITION_TOP, SEASON_TOP)
        if season not in champions:
            continue
        leaders, first_team, second_team = [], [], []
        for position, count in _season_slots(games).items():
            # Like the AP All-Pro teams: the best starting lineup is the
            # first team, the next best lineup the second.
            ranked = _top([r for r in totals if r['position'] == position], 'points', 2 * count)
            if not ranked:
                continue
            leaders.append({**ranked[0], 'rank': 1})
            awards[ranked[0]['profile_key']].append({'year': season, 'title': f'Top {position}'})
            for i, row in enumerate(ranked):
                first = i < count
                (first_team if first else second_team).append({**row, 'slot': position})
                title = FIRST_TEAM if first else SECOND_TEAM
                awards[row['profile_key']].append({'year': season, 'title': title})
                selection = selections.setdefault(
                    row['profile_key'],
                    {
                        'player': row['player'],
                        'profile_key': row['profile_key'],
                        'position': row['position'],
                        'first_team': [],
                        'second_team': [],
                    },
                )
                selection['first_team' if first else 'second_team'].append(season)
                selection.update(player=row['player'], season=season, team=row['team'])
        position_leaders[str(season)] = leaders
        all_qpfl[str(season)] = {'first_team': first_team, 'second_team': second_team}

    career = _totals(started, profile_key_for, name_for)
    qualified = [r for r in career if r['starts'] >= PPG_MIN_STARTS]

    # Manual honors: MVPs, then any other hand-picked awards.
    mvps = []
    for entry in sorted(manual_honors.get('mvps', []), key=lambda e: -int(e['year'])):
        key = resolve_name(entry['player'], entry.get('position'))
        mvps.append({**entry, 'profile_key': key})
        awards[key].append({'year': int(entry['year']), 'title': 'QPFL MVP'})
    manual_awards = []
    for entry in manual_honors.get('player_awards', []):
        key = resolve_name(entry['player'], entry.get('position'))
        manual_awards.append({**entry, 'profile_key': key})
        awards[key].append({'year': int(entry['year']), 'title': entry['title']})

    honors = {
        'mvps': mvps,
        'awards': manual_awards,
        'position_leaders': position_leaders,
        'all_qpfl': all_qpfl,
        'all_qpfl_selections': sorted(
            selections.values(),
            key=lambda r: (-len(r['first_team']), -len(r['second_team']), r['player']),
        ),
        'rings': sorted(rings.values(), key=lambda r: (-r['rings'], r['player']))[:RINGS_TOP],
        'leaderboards': {
            'career': _by_position(career, 'points', CAREER_TOP, CAREER_TOP),
            'ppg': _by_position(qualified, 'ppg', CAREER_TOP, CAREER_TOP),
            'seasons': season_boards,
        },
        'ppg_min_starts': PPG_MIN_STARTS,
        'franchise_lineups': franchise_lineups(started, set(champions), profile_key_for, name_for),
    }
    return honors, awards
