"""Generate the weekly "By the Numbers" facts file for the newsletter and site.

Flattens every season the Hall of Fame reads into team and player game rows,
then asks `qpfl.weekly_facts` what was notable about one week compared with
everything before it. Output: web/data/seasons/{season}/facts/week_{week}.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.newsletter_export import short_names
from qpfl.constants import SEASONS_DIR, SHARED_DIR
from qpfl.weekly_facts import (
    CONSOLATION,
    PLAYOFFS,
    REGULAR,
    Draftee,
    PlayerGame,
    TeamGame,
    Trade,
    TradeSide,
    generate_week_facts,
    regular_season_weeks,
    when,
)
from scripts import export_hall_of_fame as hof

PLAYOFF_BRACKETS = {'playoffs', 'championship'}

# Owner codes to the names owner milestones use (the base names, not the
# Connor Bowl swap the Hall of Fame applies).
OWNER_NAMES = hof._BASE_OWNER_NAMES

# Earlier ownership eras that belong to a current franchise seat.
LINEAGE = {old: current for current, olds in hof.FRANCHISE_LINEAGE.items() for old in olds}


def franchises_for(abbrev: str) -> tuple[str, ...]:
    """Every current franchise a historical team code counts toward."""
    return tuple(dict.fromkeys(LINEAGE.get(code, code) for code in hof.franchise_codes(abbrev)))


def bracket_for(matchup: dict, week: int, season: int) -> str:
    bracket = matchup.get('bracket')
    if bracket in PLAYOFF_BRACKETS:
        return PLAYOFFS
    if bracket:
        return CONSOLATION
    return REGULAR if week <= regular_season_weeks(season) else PLAYOFFS


def best_lineup(team: dict, score: float) -> float | None:
    """The score the roster's best possible lineup would have put up: the
    top scorers at each position, as many as actually started there. None when
    any rostered player has no score (older bench data can be missing)."""
    roster = team.get('roster') or []
    if not roster or any(not isinstance(p.get('score'), (int, float)) for p in roster):
        return None
    slots: dict[str, int] = defaultdict(int)
    by_position: dict[str, list[float]] = defaultdict(list)
    started = 0.0
    for player in roster:
        position = hof.canonical_profile_position(player.get('position'))
        by_position[position].append(float(player['score']))
        if player.get('starter'):
            slots[position] += 1
            started += float(player['score'])
    if not slots:
        return None
    best = sum(sum(sorted(by_position[pos], reverse=True)[:n]) for pos, n in slots.items())
    # Measured against the starters, so any manual adjustment to the team
    # total carries over unchanged.
    return float(score) + max(best - started, 0.0)


def _projection(team: dict) -> float | None:
    value = team.get('pregame_total')
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def flatten_season(season_data: dict) -> tuple[list[TeamGame], list[PlayerGame]]:
    season = season_data['season']
    team_games: list[TeamGame] = []
    player_games: list[PlayerGame] = []
    # First-leg scores of two-week matchups, so the second leg can carry the
    # combined result.
    first_legs: dict[tuple, dict[str, float]] = {}
    for week in season_data['weeks']:
        week_num = week.get('week')
        if not isinstance(week_num, int) or week.get('has_scores') is False:
            continue
        label = hof.get_week_name(week_num, season)
        for matchup in week.get('matchups', []):
            t1, t2 = matchup.get('team1'), matchup.get('team2')
            if not isinstance(t1, dict) or not isinstance(t2, dict):
                continue
            s1, s2 = hof.get_team_score(t1), hof.get_team_score(t2)
            if s1 is None or s2 is None:
                continue
            bracket = bracket_for(matchup, week_num, season)
            two_week = bool(matchup.get('two_week'))
            totals = None
            if two_week:
                key = (
                    matchup.get('bracket'),
                    *sorted((t1.get('abbrev', ''), t2.get('abbrev', ''))),
                )
                if key in first_legs:
                    leg = first_legs.pop(key)
                    totals = {
                        t1.get('abbrev', ''): leg.get(t1.get('abbrev', ''), 0.0) + float(s1),
                        t2.get('abbrev', ''): leg.get(t2.get('abbrev', ''), 0.0) + float(s2),
                    }
                else:
                    first_legs[key] = {
                        t1.get('abbrev', ''): float(s1),
                        t2.get('abbrev', ''): float(s2),
                    }
            for team, opp, score, opp_score in ((t1, t2, s1, s2), (t2, t1, s2, s1)):
                abbrev = team.get('abbrev', '')
                team_games.append(
                    TeamGame(
                        season=season,
                        week=week_num,
                        week_label=label,
                        bracket=bracket,
                        abbrev=abbrev,
                        franchises=franchises_for(abbrev),
                        score=float(score),
                        opp_abbrev=opp.get('abbrev', ''),
                        opp_franchises=franchises_for(opp.get('abbrev', '')),
                        opp_score=float(opp_score),
                        two_week=two_week,
                        result_score=totals[abbrev] if totals else None,
                        result_opp_score=totals[opp.get('abbrev', '')] if totals else None,
                        optimal=best_lineup(team, score),
                        projected=_projection(team),
                        opp_projected=_projection(opp),
                        title_game=matchup.get('bracket') == 'championship',
                        owners=tuple(hof.get_owner_codes(abbrev, season)),
                    )
                )
                for player in team.get('roster', []):
                    points = player.get('score')
                    if not isinstance(points, (int, float)):
                        continue
                    name = hof.clean_player_name(player.get('name', ''))
                    position = hof.canonical_profile_position(player.get('position'))
                    key = hof.player_identity_key(name, position)
                    if not key:
                        continue
                    player_games.append(
                        PlayerGame(
                            season=season,
                            week=week_num,
                            week_label=label,
                            bracket=bracket,
                            player_key=key,
                            name=name,
                            position=position,
                            abbrev=abbrev,
                            franchises=franchises_for(abbrev),
                            score=float(points),
                            starter=bool(player.get('starter')),
                            opp_franchises=franchises_for(opp.get('abbrev', '')),
                        )
                    )
    return team_games, player_games


# (season, week) -> {player key: team code} for everyone rostered that week.
Timeline = dict[tuple[int, int], dict[str, str]]


def roster_timeline(season_data: dict, names: dict[str, str]) -> Timeline:
    """Who was on which roster each week (taxi squads included), for tracing
    trades. Fills `names` with each key's display name."""
    season = season_data['season']
    timeline: Timeline = {}
    for week in season_data['weeks']:
        week_num = week.get('week')
        if not isinstance(week_num, int):
            continue
        owners: dict[str, str] = {}
        for matchup in week.get('matchups', []):
            for team in (matchup.get('team1'), matchup.get('team2')):
                if not isinstance(team, dict):
                    continue
                for player in (team.get('roster') or []) + (team.get('taxi_squad') or []):
                    if not isinstance(player, dict):
                        continue
                    name = hof.clean_player_name(player.get('name', ''))
                    key = hof.player_identity_key(name, player.get('position'))
                    if key and '::' not in key:
                        owners[key] = team.get('abbrev', '')
                        names.setdefault(key, name)
        if owners:
            timeline[(season, week_num)] = owners
    return timeline


def _normalized(text: str) -> str:
    """Text spaced like an identity key, padded so keys match whole words."""
    return f' {re.sub(r"[^a-z0-9]+", " ", text.casefold())} '


def _trade_text(trade: dict) -> str:
    parts = [str(trade.get('message') or '')]
    for side in ('proposer_gives', 'proposer_receives'):
        for player in (trade.get(side) or {}).get('players') or []:
            parts.append(player.get('name', '') if isinstance(player, dict) else str(player))
    text = ' | '.join(parts)
    # Suffixes are dropped from identity keys, so drop them here too.
    return _normalized(re.sub(r'\s+(?:Sr\.?|Jr\.?|II|III|IV|V)\b', '', text))


def trace_trade(trade: dict, timeline: Timeline, names: dict[str, str]) -> Trade | None:
    """Resolve a trade to the players each franchise received: every player
    the trade names who moved between the same two franchises across the
    trade week. Trades of only picks, or that can't be traced, return None."""
    season = trade.get('season')
    raw_week = trade.get('week')
    if not isinstance(season, int):
        return None
    week = int(raw_week) if str(raw_week).isdigit() else 0
    orders = sorted(timeline)
    before = [o for o in orders if o < (season, week)][-3:][::-1]
    after = [o for o in orders if o >= (season, max(week, 1))][:3]
    if not before or not after:
        return None
    text = _trade_text(trade)
    candidates = set(timeline[before[0]]) | set(timeline[after[0]])
    moves: dict[str, tuple[str, str]] = {}
    for key in candidates:
        if f' {key} ' not in text:
            continue
        old = next((timeline[o][key] for o in before if key in timeline[o]), None)
        new = next((timeline[o][key] for o in after if key in timeline[o]), None)
        if old and new:
            old_f, new_f = franchises_for(old)[0], franchises_for(new)[0]
            if old_f != new_f:
                moves[key] = (old_f, new_f)
    franchises = {f for pair in moves.values() for f in pair}
    if len(franchises) != 2:
        return None
    sides = []
    for franchise in sorted(franchises):
        keys = tuple(sorted(k for k, (_, to) in moves.items() if to == franchise))
        if not keys:
            return None
        sides.append(TradeSide(franchise, keys, tuple(names.get(k, k) for k in keys)))
    label = f'{season} offseason' if week == 0 else when(f'Week {week}', season)
    return Trade(season, week, label, (sides[0], sides[1]))


def load_trades(timeline: Timeline, names: dict[str, str]) -> list[Trade]:
    path = SHARED_DIR / 'transactions.json'
    if not path.exists():
        return []
    with open(path) as f:
        rows = json.load(f).get('transactions', [])
    trades = (trace_trade(t, timeline, names) for t in rows if t.get('type') == 'trade')
    return [t for t in trades if t is not None]


def resolve_draft_key(name: str, season: int, known: dict[int, set[str]]) -> str | None:
    """A draft-board name's player key. Early boards abbreviate first names
    ('T. Lawrence'), so those match a unique player started that season or later."""
    key = hof.player_identity_key(name)
    if not key:
        return None
    pool = set().union(*(keys for s, keys in known.items() if s >= season)) if known else set()
    if key in pool:
        return key
    short = re.match(r'^([a-z]) (.+)$', key)
    if short:
        initial, last = short.groups()
        matches = [k for k in pool if k.startswith(initial) and k.endswith(f' {last}')]
        if len(matches) == 1:
            return matches[0]
    return key


def load_drafts(player_games: list[PlayerGame]) -> list[Draftee]:
    path = SHARED_DIR / 'drafts.json'
    if not path.exists():
        return []
    with open(path) as f:
        drafts = json.load(f).get('drafts', [])
    known: dict[int, set[str]] = defaultdict(set)
    for p in player_games:
        known[p.season].add(p.player_key)
    out = []
    for draft in drafts:
        season = draft.get('year')
        if not isinstance(season, int):
            continue
        for rnd in draft.get('rounds', []):
            round_num = int(rnd['round']) if str(rnd.get('round', '')).isdigit() else None
            if round_num is None:
                continue
            for pick in rnd.get('picks', []):
                name = hof.clean_player_name(pick.get('player', ''))
                key = resolve_draft_key(name, season, known)
                if not key:
                    continue
                out.append(
                    Draftee(
                        season, draft.get('name', ''), draft.get('type', ''), round_num, key, name
                    )
                )
    return out


def load_rookie_seasons(keys: set[str]) -> dict[str, int]:
    """Each league player's NFL rookie season, from nflverse's player table.
    Names shared by players with different rookie seasons are left out. Empty
    (no rookie notes) when nflverse can't be reached."""
    try:
        import nflreadpy as nfl

        players = nfl.load_players().select(['display_name', 'rookie_season']).to_dicts()
    except Exception as err:  # network or nflverse outage: skip rookie notes
        print(f'Rookie seasons unavailable ({err}); skipping rookie notes.')
        return {}
    seasons: dict[str, set[int]] = defaultdict(set)
    for row in players:
        key = hof.player_identity_key(row.get('display_name') or '')
        if key in keys and isinstance(row.get('rookie_season'), int):
            seasons[key].add(row['rookie_season'])
    return {key: next(iter(s)) for key, s in seasons.items() if len(s) == 1}


def load_history(current_season: int, completed_through: int) -> tuple[list, list, Timeline, dict]:
    team_games, player_games = [], []
    timeline: Timeline = {}
    names: dict[str, str] = {}
    for season in hof.discover_seasons(current_season):
        if season > current_season:
            continue
        data = hof.load_season_data(season, current_season, completed_through)
        teams, players = flatten_season(data)
        team_games.extend(teams)
        player_games.extend(players)
        timeline.update(roster_timeline(data, names))
    return team_games, player_games, timeline, names


def owner_names(season: int) -> dict[str, str]:
    """The newsletter's owner short names (Griff, Kaminska, Spencer/Tim), so
    the site's card and the newsletter name teams the same way."""
    meta_path = SEASONS_DIR / str(season) / 'meta.json'
    if not meta_path.exists():
        return {}
    with open(meta_path) as f:
        return short_names(json.load(f))


def facts_path(season: int, week: int) -> Path:
    return SEASONS_DIR / str(season) / 'facts' / f'week_{week}.json'


def write_facts(facts: dict, path: Path) -> bool:
    """Write unless only the timestamp would change."""
    if path.exists():
        with open(path) as f:
            existing = json.load(f)
        if {k: v for k, v in existing.items() if k != 'generated_at'} == facts:
            return False
    output = {**facts, 'generated_at': datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)
        f.write('\n')
    return True


def default_week(season: int) -> int:
    hof_file = SHARED_DIR / 'hall_of_fame.json'
    if hof_file.exists():
        with open(hof_file) as f:
            week = json.load(f).get('completed_through', {}).get(str(season))
        if isinstance(week, int):
            return week
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int)
    parser.add_argument(
        '--week', type=int, help='Week to describe (default: HOF completed_through)'
    )
    parser.add_argument('--current-season', type=int, help='Live season (default: league_config)')
    parser.add_argument(
        '--backfill', action='store_true', help='Regenerate every scored week of --season'
    )
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()

    current = args.current_season or hof.configured_current_season()
    season = args.season or current
    completed = args.week if args.week is not None else default_week(current)
    if season == current and completed <= 0 and not args.backfill:
        print('No completed weeks yet; nothing to do.')
        return

    team_games, player_games, timeline, player_names = load_history(
        current, completed if season == current else 99
    )
    drafts = load_drafts(player_games)
    rookies = load_rookie_seasons({p.player_key for p in player_games})
    trades = load_trades(timeline, player_names)
    if args.backfill:
        weeks = sorted({g.week for g in team_games if g.season == season})
    else:
        weeks = [args.week if args.week is not None else completed]

    names = owner_names(season)
    for week in weeks:
        facts = generate_week_facts(
            team_games,
            player_games,
            season,
            week,
            limit=args.limit,
            drafts=drafts,
            trades=trades,
            owner_names=OWNER_NAMES,
            rookie_seasons=rookies,
        )
        facts['names'] = names
        path = facts_path(season, week)
        changed = write_facts(facts, path)
        status = 'wrote' if changed else 'unchanged'
        print(f'{season} week {week}: {len(facts["all"])} facts, {status} {path}')


if __name__ == '__main__':
    main()
