"""Pregame notes for an upcoming week: what to watch in each matchup.

The postgame "By the Numbers" notes (`qpfl.weekly_facts`) describe a week that
has been played. These describe one that hasn't: the history between the two
owners, the streaks each team carries in, players facing a franchise they used
to start for, and records or milestones a player could reach this week.

Everything is computed from completed games only, so a week in progress reads
the same before kickoff and after Thursday night. Notes use the same `Fact`
shape and `{team:X}` tokens as the weekly facts, so the site renders both the
same way. Output: web/data/seasons/{season}/pregame/week_{week}.json, written
by scripts/export_pregame.py.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from qpfl.weekly_facts import (
    CAREER_MILESTONES,
    CONSOLATION,
    GAME_MILESTONE,
    OWNER_WIN_MILESTONE,
    PLAYER,
    PLAYOFFS,
    REGULAR,
    REVENGE_MIN_STARTS,
    TEAM,
    TRADE_LOOKBACK_SEASONS,
    Fact,
    PlayerGame,
    TeamGame,
    Trade,
    WeekContext,
    _franchise_results,
    _is_rivalry,
    _primary_franchise,
    _result,
    _runs,
    _series,
    nth,
    number,
    ordinal,
    record,
    team,
    when,
)

# Team units have no "old team" to face.
REVENGE_POSITIONS = ('QB', 'RB', 'WR', 'TE', 'K')
# A record or milestone is "within reach" when this week's projection, with a
# little upside, covers the gap. 1.3x a projection is a good-not-great week.
REACH_FACTOR = 1.3
TEAM_STREAK_MIN = 3
SERIES_STREAK_MIN = 3
# A playoff meeting this recent is billed as a rematch.
REMATCH_SEASONS = 2
# Points a player needs against a former team before an average means anything.
REVENGE_VS_MIN_GAMES = 2
CAREER_START_MILESTONE = 50
THIRTY_POINT_PROJECTION = 18
PLAYOFF_LINE = 4
PLAYOFF_HISTORY_MIN = 2
# Meetings needed before a series' closest and widest games mean anything, and
# how close or lopsided they must be.
EXTREME_MIN_GAMES = 4
CLOSE_MEETING_POINTS = 2
BLOWOUT_MEETING_POINTS = 50
# Scoring against one opponent vs everyone else.
OPPONENT_SCORING_MIN_GAMES = 4
OPPONENT_SCORING_GAP = 10
FORM_STREAK_MIN = 3
SCORING_RANK_MIN_WEEKS = 3
HOT_POSITIONS = ('QB', 'RB', 'WR', 'TE')
HOT_POINTS = 20
HOT_STREAK_MIN = 3
LEADER_MIN_STARTS = 3
SET_LINEUP_SHARE = 0.8


@dataclass(frozen=True)
class RosterPlayer:
    """A player on an upcoming roster, with this week's projection if any."""

    player_key: str
    name: str
    position: str
    starter: bool
    projected: float | None = None


def _count(value: float, unit: str) -> str:
    """'1 point', '86 points'."""
    return f'{number(value)} {unit}' + ('' if value == 1 else 's')


def _slug(position: str) -> str:
    return position.lower().replace('/', '')


def _matchups(upcoming: Iterable[TeamGame]) -> list[tuple[TeamGame, TeamGame]]:
    """Pair the upcoming week's team rows into matchups, in schedule order."""
    rows = list(upcoming)
    by_abbrev = {g.abbrev: g for g in rows}
    seen: set[str] = set()
    pairs = []
    for game in rows:
        if game.abbrev in seen or game.opp_abbrev not in by_abbrev:
            continue
        seen.update((game.abbrev, game.opp_abbrev))
        pairs.append((game, by_abbrev[game.opp_abbrev]))
    return pairs


def _ranked(entries: Iterable[dict], exclude: Callable[[dict], bool]) -> list[dict]:
    """A record list without the player's own entry, best first."""
    return sorted(
        (e for e in entries if not exclude(e)), key=lambda e: e.get('value', 0), reverse=True
    )


def _not_mine(key: str, season: int | None = None) -> Callable[[dict], bool]:
    """Matches a player's own record entry (for one season, or any)."""

    def mine(entry: dict) -> bool:
        return entry.get('profile_key') == key and (season is None or entry.get('season') == season)

    return mine


# --------------------------------------------------------------------------- #
# Storylines
# --------------------------------------------------------------------------- #


def _series_storylines(ctx: WeekContext, a: TeamGame, b: TeamGame) -> list[Fact]:
    series = [g for g in _series(ctx, a) if g.decided and g.score > 0]
    subjects = [a.abbrev, b.abbrev]
    if not series:
        return [
            Fact(
                'pre_first_meeting',
                TEAM,
                subjects,
                f'{team(a.abbrev)} and {team(b.abbrev)} meet for the first time.',
                0.5,
            )
        ]

    # The card's head-to-head badge already shows the all-time record, so the
    # note covers the last meeting rather than restating it.
    facts = []
    last = series[-1]
    high, low = max(last.score, last.opp_score), min(last.score, last.opp_score)
    if last.won or last.lost:
        winner = a if last.won else b
        text = (
            f'{team(winner.abbrev)} won the last meeting {number(high)}-{number(low)} '
            f'({when(last.week_label, last.season)}).'
        )
    else:
        text = (
            f'The last meeting ended in a {number(high)}-{number(low)} tie '
            f'({when(last.week_label, last.season)}).'
        )
    facts.append(Fact('pre_last_meeting', TEAM, subjects, text, 0.35))

    result, length = _runs([_result(g) for g in series])[-1]
    if result in ('W', 'L') and length >= SERIES_STREAK_MIN:
        hot, cold = (a, b) if result == 'W' else (b, a)
        facts.append(
            Fact(
                'pre_series_streak',
                TEAM,
                [hot.abbrev, cold.abbrev],
                f'{team(hot.abbrev)} {_has(hot.abbrev)} won {length} straight against '
                f'{team(cold.abbrev)}.',
                0.45 + 0.04 * min(length, 8),
                check=_win(hot.abbrev),
            )
        )

    playoff = [g for g in series if g.bracket == PLAYOFFS]
    if playoff and playoff[-1].season >= ctx.season - REMATCH_SEASONS + 1:
        game = playoff[-1]
        winner = a if game.won else b
        scores = sorted((game.score, game.opp_score), reverse=True)
        facts.append(
            Fact(
                'pre_playoff_rematch',
                TEAM,
                subjects,
                f'A rematch of the {game.season} {game.week_label}, which '
                f'{team(winner.abbrev)} won {number(scores[0])}-{number(scores[1])}.',
                0.6 if game.title_game else 0.5,
            )
        )
    return facts


def _win(abbrev: str, expect: bool = True) -> dict:
    """Comes true when `abbrev` wins (or, with expect=False, loses)."""
    return {'type': 'win', 'team': abbrev, 'expect': expect}


def _player_points(abbrev: str, player: RosterPlayer, points: float, over: bool = False) -> dict:
    """Comes true when the player starts and scores `points` or more (more than, with over)."""
    check = {
        'type': 'player_points',
        'team': abbrev,
        'player': player.name,
        'position': player.position,
        'min': round(points, 2),
    }
    if over:
        check['over'] = True
    return check


def _player_start(abbrev: str, player: RosterPlayer) -> dict:
    return {
        'type': 'player_start',
        'team': abbrev,
        'player': player.name,
        'position': player.position,
    }


def _has(abbrev: str) -> str:
    return f'{{has:{abbrev}}}'


def _is(abbrev: str) -> str:
    return f'{{is:{abbrev}}}'


def _team_streak_storylines(
    ctx: WeekContext, a: TeamGame, b: TeamGame, results: Mapping[str, list[TeamGame]]
) -> list[Fact]:
    facts = []
    for side in (a, b):
        games = results.get(_primary_franchise(side), [])
        if not games:
            continue
        result, length = _runs([_result(g) for g in games])[-1]
        if result not in ('W', 'L') or length < TEAM_STREAK_MIN:
            continue
        word = 'won' if result == 'W' else 'lost'
        facts.append(
            Fact(
                'pre_team_streak',
                TEAM,
                [side.abbrev],
                f'{team(side.abbrev)} {_has(side.abbrev)} {word} {length} straight.',
                0.3 + 0.04 * min(length, 10),
                check=_win(side.abbrev, result == 'W'),
            )
        )
    return facts


def _standings_storylines(a: TeamGame, b: TeamGame, ranks: Mapping[str, int]) -> list[Fact]:
    rank_a, rank_b = ranks.get(a.abbrev), ranks.get(b.abbrev)
    if not rank_a or not rank_b or a.bracket != 'regular':
        return []
    (hi, hi_rank), (lo, lo_rank) = sorted(((a, rank_a), (b, rank_b)), key=lambda item: item[1])
    subjects = [hi.abbrev, lo.abbrev]
    if hi_rank == 1 and lo_rank == 2:
        text = (
            f'First place is on the line: {team(hi.abbrev)} (1st) against {team(lo.abbrev)} (2nd).'
        )
        return [Fact('pre_standings_top', TEAM, subjects, text, 0.65)]
    if lo_rank <= PLAYOFF_LINE:
        return [
            Fact(
                'pre_standings_top',
                TEAM,
                subjects,
                f'A meeting of playoff-position teams: {team(hi.abbrev)} ({ordinal(hi_rank)}) '
                f'and {team(lo.abbrev)} ({ordinal(lo_rank)}).',
                0.5,
            )
        ]
    if hi_rank <= PLAYOFF_LINE < lo_rank and lo_rank - hi_rank <= 2:
        return [
            Fact(
                'pre_standings_line',
                TEAM,
                subjects,
                f'{team(hi.abbrev)} ({ordinal(hi_rank)}) and {team(lo.abbrev)} '
                f'({ordinal(lo_rank)}) meet on either side of the playoff line.',
                0.55,
            )
        ]
    return []


def _rivalry_storylines(ctx: WeekContext, a: TeamGame, b: TeamGame, is_rivalry: bool) -> list[Fact]:
    if not is_rivalry:
        return []
    games = [g for g in _series(ctx, a) if _is_rivalry(g) and g.decided]
    wins = sum(1 for g in games if g.won)
    losses = sum(1 for g in games if g.lost)
    if not games:
        text = f"It's Rivalry Week, and {team(a.abbrev)} and {team(b.abbrev)} meet in it for the first time."
    else:
        text = (
            f"It's Rivalry Week: {team(a.abbrev)} {_is(a.abbrev)} "
            f'{record(wins, losses, len(games) - wins - losses)} against {team(b.abbrev)} '
            'in Rivalry Week games.'
        )
    return [Fact('pre_rivalry', TEAM, [a.abbrev, b.abbrev], text, 0.6)]


def _series_history_storylines(ctx: WeekContext, a: TeamGame, b: TeamGame) -> list[Fact]:
    """Playoff meetings, and the closest and most lopsided games, between the owners."""
    series = [g for g in _series(ctx, a) if g.decided and g.score > 0 and g.single_game]
    subjects = [a.abbrev, b.abbrev]
    facts = []

    playoff = [g for g in series if g.bracket == PLAYOFFS]
    if len(playoff) >= PLAYOFF_HISTORY_MIN:
        wins = sum(1 for g in playoff if g.won)
        losses = sum(1 for g in playoff if g.lost)
        if wins == losses:
            split = f'they have split them {wins}-{losses}'
        else:
            leader = a if wins > losses else b
            split = f'{team(leader.abbrev)} won {max(wins, losses)} of them'
        facts.append(
            Fact(
                'pre_series_playoffs',
                TEAM,
                subjects,
                f'{team(a.abbrev)} and {team(b.abbrev)} have met {len(playoff)} times in the '
                f'playoffs; {split}.',
                0.5 + 0.03 * min(len(playoff), 5),
            )
        )

    if len(series) >= EXTREME_MIN_GAMES:
        closest = min(series, key=lambda g: (g.margin, g.order))
        widest = max(series, key=lambda g: (g.margin, g.order))
        for game, kind, qualifies in (
            (closest, 'closest', closest.margin <= CLOSE_MEETING_POINTS and closest.margin > 0),
            (widest, 'widest', widest.margin >= BLOWOUT_MEETING_POINTS),
        ):
            if not qualifies:
                continue
            winner = a if game.won else b
            high, low = max(game.score, game.opp_score), min(game.score, game.opp_score)
            lead = (
                f'Their closest meeting was decided by {_count(game.margin, "point")}'
                if kind == 'closest'
                else f'Their most lopsided meeting was a {number(game.margin)}-point win'
            )
            facts.append(
                Fact(
                    f'pre_series_{kind}',
                    TEAM,
                    subjects,
                    f'{lead}: {team(winner.abbrev)} won {number(high)}-{number(low)} '
                    f'({when(game.week_label, game.season)}).',
                    0.4,
                )
            )
    return facts


def _opponent_scoring_storylines(ctx: WeekContext, a: TeamGame, b: TeamGame) -> list[Fact]:
    """A team that scores unusually high (or low) against this opponent."""
    facts = []
    for side, other in ((a, b), (b, a)):
        series = [g for g in _series(ctx, side) if g.score > 0 and g.single_game]
        if len(series) < OPPONENT_SCORING_MIN_GAMES:
            continue
        mine = set(side.owners) or set(side.franchises)
        rest = [
            g
            for g in ctx.team_all
            if g.score > 0
            and g.single_game
            and (set(g.owners) or set(g.franchises)) & mine
            and g not in series
        ]
        if len(rest) < OPPONENT_SCORING_MIN_GAMES:
            continue
        versus = sum(g.score for g in series) / len(series)
        elsewhere = sum(g.score for g in rest) / len(rest)
        gap = versus - elsewhere
        if abs(gap) < OPPONENT_SCORING_GAP:
            continue
        facts.append(
            Fact(
                'pre_opponent_scoring',
                TEAM,
                [side.abbrev, other.abbrev],
                f'{team(side.abbrev)} {_has(side.abbrev)} averaged {number(round(versus, 1))} '
                f'against {team(other.abbrev)} in {len(series)} meetings, '
                f'{number(round(abs(gap), 1))} {"more" if gap > 0 else "fewer"} than against '
                'everyone else.',
                0.4 + min(abs(gap), 30) / 150,
            )
        )
    return facts


def _season_weeks(ctx: WeekContext) -> dict[int, list[TeamGame]]:
    """This season's completed regular-season weeks."""
    weeks: dict[int, list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        if g.season == ctx.season and g.bracket == REGULAR and g.score > 0:
            weeks[g.week].append(g)
    return dict(sorted(weeks.items()))


def _form_storylines(
    ctx: WeekContext, a: TeamGame, b: TeamGame, weeks: Mapping[int, list[TeamGame]]
) -> list[Fact]:
    """Each team's current run of 100-point weeks and top- or bottom-half finishes."""
    facts = []
    for side in (a, b):
        franchise = _primary_franchise(side)
        line = []
        for games in weeks.values():
            mine = next((g for g in games if franchise in g.franchises), None)
            if mine is None:
                continue
            higher = sum(1 for g in games if g.score > mine.score)
            line.append((mine.score >= 100, higher < len(games) // 2))
        if not line:
            continue
        hundreds = _trailing(line, lambda row: row[0])
        top, bottom = _trailing(line, lambda row: row[1]), _trailing(line, lambda row: not row[1])
        if hundreds >= FORM_STREAK_MIN:
            facts.append(
                Fact(
                    'pre_form_hundreds',
                    TEAM,
                    [side.abbrev],
                    f'{team(side.abbrev)} {_has(side.abbrev)} scored 100 or more in {hundreds} '
                    'straight weeks.',
                    0.35 + 0.04 * min(hundreds, 8),
                    check={'type': 'team_points', 'team': side.abbrev, 'min': 100},
                )
            )
        half, run = ('top', top) if top >= bottom else ('bottom', bottom)
        if run >= FORM_STREAK_MIN:
            facts.append(
                Fact(
                    f'pre_form_{half}_half',
                    TEAM,
                    [side.abbrev],
                    f'{team(side.abbrev)} {_has(side.abbrev)} finished in the {half} half of '
                    f'the league {run} weeks running.',
                    0.3 + 0.04 * min(run, 8),
                    check={'type': 'top_half', 'team': side.abbrev, 'expect': half == 'top'},
                )
            )
    return facts


def _trailing(rows: list, test: Callable) -> int:
    """How many of the latest rows in a row pass `test`."""
    count = 0
    for row in reversed(rows):
        if not test(row):
            break
        count += 1
    return count


def _scoring_rank_storylines(
    a: TeamGame, b: TeamGame, weeks: Mapping[int, list[TeamGame]]
) -> list[Fact]:
    """Where the two teams rank in points per game this season."""
    totals: dict[str, list[float]] = defaultdict(list)
    for games in weeks.values():
        for g in games:
            totals[_primary_franchise(g)].append(g.score)
    if len(weeks) < SCORING_RANK_MIN_WEEKS or len(totals) < 4:
        return []
    ppg = {f: sum(s) / len(s) for f, s in totals.items()}
    order = sorted(ppg, key=lambda f: -ppg[f])
    rank = {f: i + 1 for i, f in enumerate(order)}
    ra, rb = rank.get(_primary_franchise(a)), rank.get(_primary_franchise(b))
    if not ra or not rb:
        return []
    (hi, hi_rank), (lo, lo_rank) = sorted(((a, ra), (b, rb)), key=lambda item: item[1])
    subjects = [hi.abbrev, lo.abbrev]
    last = len(order)
    if hi_rank == 1 and lo_rank == last:
        text = (
            f"The league's highest-scoring team, {team(hi.abbrev)}, faces the lowest, "
            f'{team(lo.abbrev)}.'
        )
    elif lo_rank <= 3:
        text = (
            f"Two of the league's top scorers meet: {team(hi.abbrev)} ({ordinal(hi_rank)} in "
            f'points per game) and {team(lo.abbrev)} ({ordinal(lo_rank)}).'
        )
    elif hi_rank >= last - 2:
        text = (
            f"Two of the league's lowest scorers meet: {team(hi.abbrev)} ({ordinal(hi_rank)} in "
            f'points per game) and {team(lo.abbrev)} ({ordinal(lo_rank)}).'
        )
    else:
        return []
    return [Fact('pre_scoring_ranks', TEAM, subjects, text, 0.45)]


def _player_storylines(
    ctx: WeekContext, side: TeamGame, roster: Iterable[RosterPlayer]
) -> list[Fact]:
    """Starters on a hot run, and starters leading their position this season."""
    starts: dict[str, list[PlayerGame]] = defaultdict(list)
    season_points: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    season_starts: dict[str, int] = defaultdict(int)
    for p in ctx.player_all:
        starts[p.player_key].append(p)
        if p.season == ctx.season:
            season_points[p.position][p.player_key] += p.score
            season_starts[p.player_key] += 1
    facts = []
    for player in roster:
        if not player.starter or player.position not in HOT_POSITIONS:
            continue
        run = _trailing(starts.get(player.player_key, []), lambda p: p.score >= HOT_POINTS)
        if run >= HOT_STREAK_MIN:
            facts.append(
                Fact(
                    'pre_player_hot',
                    PLAYER,
                    [side.abbrev],
                    f'{player.name} has scored {HOT_POINTS}+ in {run} straight starts.',
                    0.4 + 0.05 * min(run, 6),
                    check=_player_points(side.abbrev, player, HOT_POINTS),
                )
            )
        leaders = season_points.get(player.position, {})
        if (
            leaders
            and season_starts[player.player_key] >= LEADER_MIN_STARTS
            and max(leaders, key=lambda k: leaders[k]) == player.player_key
        ):
            facts.append(
                Fact(
                    'pre_player_leader',
                    PLAYER,
                    [side.abbrev],
                    f'{player.name} leads all QPFL {player.position} starters this season with '
                    f'{_count(leaders[player.player_key], "point")}.',
                    0.45,
                )
            )
    return facts


def _projection_storylines(
    matchups: list[tuple[TeamGame, TeamGame]],
    rosters: Mapping[str, list[RosterPlayer]],
    team_projections: Mapping[str, float] | None = None,
) -> dict[tuple[str, str], list[Fact]]:
    """The week's closest projected game and its biggest projected favorite.

    Uses each team's pregame projection when the week file has one: it is the
    "Proj" line on the matchup card, and it stays fixed once games kick off,
    where the starters' own projections keep moving through the week.
    """
    team_projections = team_projections or {}
    # A lineup that isn't set yet projects far too low. Teams do leave a slot
    # empty on purpose, so a lineup counts once it's most of the way there.
    full = max((sum(p.starter for p in roster) for roster in rosters.values()), default=0)
    needed = math.ceil(full * SET_LINEUP_SHARE)
    projected = {}
    for a, b in matchups:
        totals = []
        for side in (a, b):
            starters = [p for p in rosters.get(side.abbrev, []) if p.starter]
            if not full or len(starters) < needed or any(p.projected is None for p in starters):
                break
            pregame = team_projections.get(side.abbrev)
            totals.append(
                pregame if pregame is not None else sum(p.projected or 0.0 for p in starters)
            )
        if len(totals) == 2:
            projected[(a.abbrev, b.abbrev)] = (a, b, totals[0], totals[1])
    if len(projected) < 2:
        return {}
    margin = {key: abs(v[2] - v[3]) for key, v in projected.items()}
    out: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for key, kind in (
        (min(margin, key=lambda k: margin[k]), 'closest'),
        (max(margin, key=lambda k: margin[k]), 'widest'),
    ):
        a, b, pa, pb = projected[key]
        fav = a if pa >= pb else b
        gap = number(round(margin[key], 1))
        text = (
            f'The closest projected game of the week: {team(fav.abbrev)} by {gap}.'
            if kind == 'closest'
            else f"The week's biggest projected favorite: {team(fav.abbrev)} by {gap}."
        )
        out[key].append(
            Fact(
                f'pre_projection_{kind}',
                TEAM,
                [a.abbrev, b.abbrev],
                text,
                0.45,
                check=_win(fav.abbrev),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Revenge games
# --------------------------------------------------------------------------- #


def _revenge(
    ctx: WeekContext,
    side: TeamGame,
    opponent: TeamGame,
    roster: Iterable[RosterPlayer],
    trades: Iterable[Trade],
) -> list[Fact]:
    """Players facing a franchise they started for, or that traded them away."""
    mine, theirs = _primary_franchise(side), _primary_franchise(opponent)
    starts: dict[str, list[PlayerGame]] = defaultdict(list)
    versus: dict[str, list[PlayerGame]] = defaultdict(list)
    for p in ctx.player_all:
        if p.franchises and p.franchises[0] == theirs:
            starts[p.player_key].append(p)
        if theirs in p.opp_franchises[:1]:
            versus[p.player_key].append(p)
    acquired: dict[str, Trade] = {}
    for trade in trades:
        if trade.season < ctx.season - TRADE_LOOKBACK_SEASONS or trade.order >= ctx.target:
            continue
        for received, gave in (trade.sides, trade.sides[::-1]):
            if received.franchise == mine and gave.franchise == theirs:
                for key in received.player_keys:
                    acquired[key] = trade

    roster = list(roster)
    # Before a lineup is set nobody is a starter; "on the bench" would mislead.
    lineup_set = any(p.starter for p in roster)
    facts = []
    for player in roster:
        if player.position not in REVENGE_POSITIONS:
            continue
        old = starts.get(player.player_key, [])
        deal = acquired.get(player.player_key)
        if len(old) < REVENGE_MIN_STARTS and deal is None:
            continue
        details = []
        if deal is not None:
            details.append(f'traded away {deal.label}')
        if old:
            first, last = old[0].season, old[-1].season
            span = str(first) if first == last else f'{first}-{last}'
            details.append(
                f'{_count(len(old), "start")}, {_count(sum(p.score for p in old), "point")} '
                f'there, {span}'
            )
        text = f'{player.name} faces former team {team(opponent.abbrev)} ({"; ".join(details)}).'
        against = versus.get(player.player_key, [])
        if len(against) >= REVENGE_VS_MIN_GAMES:
            avg = sum(p.score for p in against) / len(against)
            text += f' Averages {number(round(avg, 1))} in {len(against)} starts against them.'
        if lineup_set and not player.starter:
            text += ' On the bench for now.'
        facts.append(
            Fact(
                'pre_revenge',
                PLAYER,
                [side.abbrev, opponent.abbrev],
                text,
                0.45
                + (0.1 if player.starter else 0)
                + (0.1 if deal else 0)
                + min(len(old), 30) / 200,
                ['starter' if player.starter else 'bench'],
                check=_win(side.abbrev) if player.starter else None,
            )
        )
    return facts


# --------------------------------------------------------------------------- #
# Records and milestones
# --------------------------------------------------------------------------- #


@dataclass
class _Totals:
    points: float = 0.0
    starts: int = 0
    thirties: int = 0


def _player_totals(
    games: Iterable[PlayerGame], key_for: Callable[[str], str]
) -> dict[str, _Totals]:
    totals: dict[str, _Totals] = defaultdict(_Totals)
    for p in games:
        row = totals[key_for(p.player_key)]
        row.points += p.score
        row.starts += 1
        row.thirties += p.score >= 30
    return totals


def _passing(entries: list[dict], current: float, reach: float) -> dict | None:
    """The best-ranked entry the player could pass with `reach` more."""
    for entry in entries:
        value = entry.get('value', 0)
        if current < value < current + reach:
            return entry
    return None


def _entry_label(entry: dict, with_season: bool = True) -> str:
    name = entry.get('player') or entry.get('team_name') or entry.get('team', '')
    season = entry.get('season')
    return f'{name} ({season})' if season and with_season else name


def _player_records(
    ctx: WeekContext,
    side: TeamGame,
    roster: Iterable[RosterPlayer],
    groups: Mapping[str, dict],
    key_for: Callable[[str], str],
) -> tuple[list[Fact], list[Fact]]:
    season_totals = _player_totals((p for p in ctx.player_all if p.season == ctx.season), key_for)
    career_totals = _player_totals(ctx.player_all, key_for)
    records: list[Fact] = []
    milestones: list[Fact] = []
    for player in roster:
        projected = player.projected or 0.0
        if not player.starter or projected <= 0:
            continue
        key = key_for(player.player_key)
        reach = projected * REACH_FACTOR
        subjects = [side.abbrev]
        season_row = season_totals.get(key, _Totals())
        career_row = career_totals.get(key, _Totals())

        for scope, row, group_ids, desc in (
            (
                'season',
                season_row,
                (
                    'player-season-most-points',
                    f'player-season-most-points-{_slug(player.position)}',
                ),
                ('single-season points', f'single-season {player.position} points'),
            ),
            (
                'career',
                career_row,
                (
                    'player-career-most-points',
                    f'player-career-most-points-{_slug(player.position)}',
                ),
                ('career points', f'career {player.position} points'),
            ),
        ):
            for group_id, label in zip(group_ids, desc, strict=True):
                group = groups.get(group_id)
                if not group:
                    continue
                own = _not_mine(key, ctx.season if scope == 'season' else None)
                entry = _passing(_ranked(group.get('entries', []), own), row.points, reach)
                if entry is None:
                    continue
                gap = entry['value'] - row.points
                rank = entry.get('rank') or 0
                records.append(
                    Fact(
                        f'pre_record_{scope}',
                        PLAYER,
                        subjects,
                        f'{player.name} is {_count(gap, "point")} behind '
                        f'{_entry_label(entry, scope == "season")} '
                        f'for {ordinal(rank)} in {label}, with {number(projected)} projected '
                        'this week.',
                        0.55 + 0.25 / max(rank, 1) + (0.1 if group_id == group_ids[0] else 0),
                        [scope, group_id],
                        check=_player_points(side.abbrev, player, gap, over=True),
                    )
                )
                break  # the overall list when it's reachable, else the position list

        starts_group = groups.get('player-career-most-starts')
        if starts_group:
            entries = _ranked(starts_group.get('entries', []), _not_mine(key))
            entry = next(
                (e for e in entries if career_row.starts <= e['value'] < career_row.starts + 1),
                None,
            )
            if entry:
                records.append(
                    Fact(
                        'pre_record_starts',
                        PLAYER,
                        subjects,
                        f"{player.name}'s next start would be career start "
                        f'{career_row.starts + 1}, passing {_entry_label(entry, False)} for '
                        f'{ordinal(entry.get("rank") or 0)} all-time.',
                        0.5,
                        ['career', 'player-career-most-starts'],
                        check=_player_start(side.abbrev, player),
                    )
                )
        thirty_group = groups.get('player-career-thirty-point-games')
        if thirty_group and projected >= THIRTY_POINT_PROJECTION:
            entries = _ranked(thirty_group.get('entries', []), _not_mine(key))
            entry = next(
                (e for e in entries if career_row.thirties <= e['value'] < career_row.thirties + 1),
                None,
            )
            if entry:
                records.append(
                    Fact(
                        'pre_record_thirties',
                        PLAYER,
                        subjects,
                        f'A 30-point game would move {player.name} past {_entry_label(entry, False)} '
                        f'for {ordinal(entry.get("rank") or 0)} in career 30-point games.',
                        0.45,
                        ['career', 'player-career-thirty-point-games'],
                        check=_player_points(side.abbrev, player, 30),
                    )
                )

        mark = next(
            (m for m in CAREER_MILESTONES if career_row.points < m <= career_row.points + reach),
            None,
        )
        if mark:
            milestones.append(
                Fact(
                    'pre_milestone_points',
                    PLAYER,
                    subjects,
                    f'{player.name} needs {_count(mark - career_row.points, "point")} for '
                    f'{number(mark)} career points as a QPFL starter.',
                    0.4 + 0.05 * CAREER_MILESTONES.index(mark) / 2,
                    check=_player_points(side.abbrev, player, mark - career_row.points),
                )
            )
        if career_row.starts and (career_row.starts + 1) % CAREER_START_MILESTONE == 0:
            milestones.append(
                Fact(
                    'pre_milestone_starts',
                    PLAYER,
                    subjects,
                    f'{player.name} is set for career start {career_row.starts + 1}.',
                    0.35,
                    check=_player_start(side.abbrev, player),
                )
            )
    return records, milestones


def _team_records(
    ctx: WeekContext,
    side: TeamGame,
    groups: Mapping[str, dict],
    owner_code: Callable[[str], str],
) -> list[Fact]:
    """A win (or loss) that would tie or extend a streak in the record book."""
    facts: list[Fact] = []
    me = owner_code(side.abbrev)
    games = [
        g
        for g in ctx.team_all
        if g.decided
        and g.bracket != CONSOLATION
        and (g.score > 0 or g.opp_score > 0)
        and owner_code(g.abbrev) == me
    ]
    if not games:
        return facts
    result, length = _runs([_result(g) for g in games])[-1]
    group_id = {'W': 'team-longest-win-streak', 'L': 'team-longest-losing-streak'}.get(result)
    group = groups.get(group_id or '')
    if not group or length < TEAM_STREAK_MIN:
        return facts
    # The record book includes the streak still running; leave it out.
    running = games[-1]
    entries = _ranked(
        group.get('entries', []),
        lambda e: (
            e.get('season') == running.season
            and e.get('week') == running.week
            and owner_code(e.get('team', '')) == me
        ),
    )
    entry = next((e for e in entries if e['value'] <= length + 1), None)
    if entry is None:
        return facts
    kind = 'win' if result == 'W' else 'losing'
    outcome = 'win' if result == 'W' else 'loss'
    verb = 'tie' if entry['value'] == length + 1 else 'pass'
    facts.append(
        Fact(
            f'pre_record_{kind}_streak',
            TEAM,
            [side.abbrev],
            f'A {outcome} would make it {length + 1} straight for {team(side.abbrev)}, enough to '
            f'{verb} {_entry_label(entry)} for {ordinal(entry.get("rank") or 0)} on the longest '
            f'{kind} streak list.',
            0.6 if result == 'W' else 0.5,
            [group_id or ''],
            check=_win(side.abbrev, result == 'W'),
        )
    )
    return facts


def _owner_milestones(
    ctx: WeekContext, side: TeamGame, owner_names: Mapping[str, str]
) -> list[Fact]:
    facts = []
    for owner in side.owners:
        name = owner_names.get(owner)
        if not name:
            continue
        games = [g for g in ctx.team_all if owner in g.owners and g.score > 0]
        wins = sum(1 for g in games if g.won)
        if wins and (wins + 1) % OWNER_WIN_MILESTONE == 0:
            facts.append(
                Fact(
                    'pre_milestone_owner_wins',
                    TEAM,
                    [side.abbrev],
                    f"A win would be {name}'s {nth(wins + 1)} career win.",
                    0.45 + 0.05 * min((wins + 1) // OWNER_WIN_MILESTONE, 4),
                    check=_win(side.abbrev),
                )
            )
        if games and (len(games) + 1) % GAME_MILESTONE == 0:
            facts.append(
                Fact(
                    'pre_milestone_owner_games',
                    TEAM,
                    [side.abbrev],
                    f'{name} plays career game {len(games) + 1} this week.',
                    0.35,
                )
            )
    return facts


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def _series_summary(ctx: WeekContext, a: TeamGame) -> dict:
    """The owners' head-to-head series coming into the week, from team1's side:
    the same owner-based series the storylines and postgame notes use."""
    series = [g for g in _series(ctx, a) if g.decided and g.score > 0]
    scored = [g for g in series if g.single_game]
    this_season = [g for g in series if g.season == ctx.season]

    def tally(games: list[TeamGame]) -> dict:
        wins = sum(1 for g in games if g.won)
        losses = sum(1 for g in games if g.lost)
        return {'wins': wins, 'losses': losses, 'ties': len(games) - wins - losses}

    return {
        'games': len(series),
        **tally(series),
        'season': tally(this_season),
        'scored_games': len(scored),
        'points_for': round(sum(g.score for g in scored), 2),
        'points_against': round(sum(g.opp_score for g in scored), 2),
    }


def _sorted(facts: list[Fact]) -> list[dict]:
    return [f.to_dict() for f in sorted(facts, key=lambda f: -f.notability)]


def generate_pregame(
    team_games: list[TeamGame],
    player_games: list[PlayerGame],
    season: int,
    week: int,
    upcoming: list[TeamGame],
    rosters: Mapping[str, list[RosterPlayer]],
    record_groups: Iterable[dict] = (),
    ranks: Mapping[str, int] | None = None,
    trades: Iterable[Trade] = (),
    owner_names: Mapping[str, str] | None = None,
    profile_key_for: Callable[[str], str] | None = None,
    owner_code: Callable[[str], str] | None = None,
    is_rivalry: bool = False,
    team_projections: Mapping[str, float] | None = None,
) -> dict:
    """Notes for each of the week's matchups, from games before it only.

    `upcoming` holds one TeamGame row per team for the week (scores unused),
    which carries the owners and franchises each side plays for.
    `team_projections` maps each team to its pregame projected total.
    """
    target = (season, week)
    ctx = WeekContext(
        [g for g in team_games if g.order < target],
        [p for p in player_games if p.order < target],
        season,
        week,
    )
    groups = {g['id']: g for g in record_groups if g.get('id')}
    key_for = profile_key_for or (lambda key: key)
    code_for = owner_code or (lambda abbrev: abbrev)
    trades = list(trades)
    results = _franchise_results(ctx, regular_only=False)

    weeks = _season_weeks(ctx)
    pairs = _matchups(upcoming)
    projections = _projection_storylines(pairs, rosters, team_projections)
    matchups = []
    for a, b in pairs:
        storylines = [
            *_rivalry_storylines(ctx, a, b, is_rivalry),
            *_standings_storylines(a, b, ranks or {}),
            *projections.get((a.abbrev, b.abbrev), []),
            *_series_storylines(ctx, a, b),
            *_series_history_storylines(ctx, a, b),
            *_opponent_scoring_storylines(ctx, a, b),
            *_team_streak_storylines(ctx, a, b, results),
            *_form_storylines(ctx, a, b, weeks),
            *_scoring_rank_storylines(a, b, weeks),
        ]
        revenge: list[Fact] = []
        records: list[Fact] = []
        milestones: list[Fact] = []
        for side, other in ((a, b), (b, a)):
            roster = rosters.get(side.abbrev, [])
            storylines += _player_storylines(ctx, side, roster)
            revenge += _revenge(ctx, side, other, roster, trades)
            player_records, player_milestones = _player_records(ctx, side, roster, groups, key_for)
            records += player_records + _team_records(ctx, side, groups, code_for)
            milestones += player_milestones + _owner_milestones(ctx, side, owner_names or {})
        matchups.append(
            {
                'team1': a.abbrev,
                'team2': b.abbrev,
                'storylines': _sorted(storylines),
                'revenge': _sorted(revenge),
                'records': _sorted(records),
                'milestones': _sorted(milestones),
                'series': _series_summary(ctx, a),
            }
        )
    return {
        'season': season,
        'week': week,
        'week_label': upcoming[0].week_label if upcoming else f'Week {week}',
        'history_through': max((g.order for g in ctx.team_all), default=None),
        'matchups': matchups,
    }
