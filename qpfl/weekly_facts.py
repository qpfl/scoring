"""Weekly "By the Numbers" facts: one week's results in league-history context.

The engine is pure. It takes every team and player game the league has played
(flattened by `scripts/export_weekly_facts.py`) plus a target week, compares the
target week only against what came before it, and returns notes like "the
4th-highest score in league history" or "the most since Week 9, 2024".

Facts name teams with `{team:ABBREV}` tokens so the newsletter (owner short
names) and the site (team names) can each render them their own way.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

REGULAR = 'regular'
PLAYOFFS = 'playoffs'
CONSOLATION = 'consolation'

LEAGUE = 'league'
TEAM = 'team'
PLAYER = 'player'

# How far down an all-time list a result has to land to be worth a note.
LEAGUE_TOP = 10
LEAGUE_TOP_SHORT = 5
FRANCHISE_TOP = 5
# "One of only N" clubs stay notable while they are this small.
MARGIN_CLUB_MAX = 15
PLAYER_CLUB_MAX_GAMES = 25
POSITION_CLUB_MAX_GAMES = 10
# A "most since" callback needs at least this many league weeks of gap.
SINCE_MIN_GAP_WEEKS = 17
SINCE_STANDALONE_GAP_WEEKS = 34
MIN_FRANCHISE_GAMES = 20
STREAK_MIN = 4
SNAPPED_STREAK_MIN = 5
CAREER_MILESTONES = (250, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000)
BIG_GAME_POINTS = 40
HOT_STREAK_POINTS = 30
HOT_STREAK_MIN = 3
# Season starts and career clubs stop being news once this many have done it.
RARE_CLUB_MAX = 6
MILESTONE_CLUB_MAX = 10
MILESTONE_POSITIONS = ('QB', 'RB', 'WR', 'TE')
# Team-unit positions score in narrow, heavily tied ranges; ranking them is noise.
RANKED_POSITIONS = ('QB', 'RB', 'WR', 'TE', 'K', 'D/ST')
CLUB_POSITIONS = ('QB', 'RB', 'WR', 'TE', 'D/ST')
SERIES_LEAD_MIN_GAMES = 6
PLAYOFF_SPOTS = 4
# A playoff-odds note needs this many earlier teams with the same record, and
# their playoff rate has to be at least this lopsided either way.
PLAYOFF_ODDS_MIN_SAMPLE = 5
PLAYOFF_ODDS_EXTREME = 0.8
OWNER_WIN_MILESTONE = 25
OWNER_POINT_MILESTONE = 5000
LINEUP_COST_MIN_MARGIN = 15
LOYALTY_MILESTONE = 25
VERSUS_MIN_GAMES = 6
REVENGE_MIN_STARTS = 8
REVENGE_MIN_POINTS = 20
TRADE_LOOKBACK_SEASONS = 1

# Notes per team across the headline and "more notes" lists together.
MORE_PER_TEAM = 4

CATEGORY_WEIGHT = {LEAGUE: 1.0, PLAYER: 0.9, TEAM: 0.8}


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TeamGame:
    season: int
    week: int
    week_label: str
    bracket: str
    abbrev: str
    franchises: tuple[str, ...]
    score: float
    opp_abbrev: str
    opp_franchises: tuple[str, ...]
    opp_score: float
    # Two-week playoff legs: each week's score is real, but only the final leg
    # carries a result, decided by the two-week totals in result_*_score.
    two_week: bool = False
    result_score: float | None = None
    result_opp_score: float | None = None
    # The best score the same roster could have started (None when any bench
    # score is missing), the pregame projection (2026 on), whether this is the
    # championship, and the owner codes credited with the game.
    optimal: float | None = None
    projected: float | None = None
    opp_projected: float | None = None
    title_game: bool = False
    owners: tuple[str, ...] = ()

    @property
    def order(self) -> tuple[int, int]:
        return (self.season, self.week)

    @property
    def single_game(self) -> bool:
        """A one-week matchup, whose margin and combined score mean something."""
        return not self.two_week

    @property
    def decided(self) -> bool:
        """Carries a win/loss: every one-week game, plus a two-week final leg."""
        return not self.two_week or self.result_score is not None

    def _result_scores(self) -> tuple[float, float]:
        if self.result_score is not None and self.result_opp_score is not None:
            return self.result_score, self.result_opp_score
        return self.score, self.opp_score

    @property
    def won(self) -> bool:
        mine, theirs = self._result_scores()
        return self.decided and mine > theirs

    @property
    def lost(self) -> bool:
        mine, theirs = self._result_scores()
        return self.decided and mine < theirs

    @property
    def margin(self) -> float:
        return abs(self.score - self.opp_score)


@dataclass(frozen=True)
class PlayerGame:
    season: int
    week: int
    week_label: str
    bracket: str
    player_key: str
    name: str
    position: str
    abbrev: str
    franchises: tuple[str, ...]
    score: float
    starter: bool = True
    opp_franchises: tuple[str, ...] = ()

    @property
    def order(self) -> tuple[int, int]:
        return (self.season, self.week)


@dataclass(frozen=True)
class Draftee:
    """One pick from a league draft, joined to the player's identity key."""

    season: int
    draft: str
    kind: str
    round: int
    player_key: str
    name: str


@dataclass(frozen=True)
class TradeSide:
    franchise: str
    player_keys: tuple[str, ...]
    names: tuple[str, ...]


@dataclass(frozen=True)
class Trade:
    """A trade whose players could be traced from one roster to the other."""

    season: int
    week: int
    label: str
    sides: tuple[TradeSide, TradeSide]

    @property
    def order(self) -> tuple[int, int]:
        return (self.season, self.week)


@dataclass
class Fact:
    id: str
    category: str
    subjects: list[str]
    template: str
    notability: float
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'category': self.category,
            'subjects': self.subjects,
            'template': self.template,
            'notability': round(self.notability, 3),
            'tags': self.tags,
        }


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


def rank_of(value: float, population: Iterable[float], higher: bool = True) -> tuple[int, int, int]:
    """Rank `value` within a population that already contains it.

    Returns (rank, total, tied) where `tied` counts the *other* entries with
    the same value, so a unique record is (1, n, 0).
    """
    values = list(population)
    better = sum(1 for v in values if (v > value if higher else v < value))
    tied = sum(1 for v in values if v == value) - 1
    return better + 1, len(values), max(tied, 0)


def ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
    return f'{number}{suffix}'


def nth(number: int) -> str:
    """'first' reads better than '1st' in prose."""
    return 'first' if number == 1 else ordinal(number)


def article(number: int) -> str:
    """'a' or 'an' before a spoken number (an 8-game, an 11-game)."""
    return 'an' if str(number).startswith('8') or number in (11, 18) else 'a'


def rank_phrase(rank: int, tied: int, superlative: str) -> str:
    """'the highest', 'tied for the 3rd-highest', ..."""
    core = superlative if rank == 1 else f'{ordinal(rank)}-{superlative}'
    return f'tied for the {core}' if tied else f'the {core}'


def number(value: float) -> str:
    value = float(value)
    return f'{value:,.0f}' if value.is_integer() else f'{value:,.1f}'


def team(abbrev: str) -> str:
    return f'{{team:{abbrev}}}'


def has(abbrev: str) -> str:
    """'has' or 'have', agreeing with however the consumer names the team."""
    return f'{{has:{abbrev}}}'


def is_(abbrev: str) -> str:
    """'is' or 'are', agreeing with however the consumer names the team."""
    return f'{{is:{abbrev}}}'


TOKEN_PATTERN = re.compile(r'\{(team|has|is):([^}]+)\}')
PLURAL_VERBS = {'has': 'have', 'is': 'are'}


def is_plural_name(name: str) -> bool:
    """Co-owned teams read as plural: 'Spencer/Tim have', 'Joe & Joe are'."""
    return '/' in name or '&' in name or ' and ' in name


def render(template: str, names: dict[str, str]) -> str:
    """Swap `{team:X}` tokens for display names (falling back to the abbrev)
    and `{has:X}`/`{is:X}` for verbs that agree with that name. The newsletter
    and site renderers mirror this."""

    def swap(match: re.Match[str]) -> str:
        kind: str = match.group(1)
        abbrev: str = match.group(2)
        name = names.get(abbrev, abbrev)
        if kind == 'team':
            return name
        return PLURAL_VERBS[kind] if is_plural_name(name) else kind

    return TOKEN_PATTERN.sub(swap, template)


def when(label: str, season: int) -> str:
    if label.startswith('Week '):
        return f'{label}, {season}'
    return f'the {season} {label}'


def week_index(orders: Iterable[tuple[int, int]]) -> dict[tuple[int, int], int]:
    return {order: i for i, order in enumerate(sorted(set(orders)))}


def regular_season_weeks(season: int) -> int:
    return 14 if season <= 2021 else 15


def top_half_value(season: int) -> float:
    """Rank points for a top-half week: a full point through 2021, half since."""
    return 1.0 if season <= 2021 else 0.5


def record(wins: float, losses: float, ties: float = 0) -> str:
    text = f'{wins:g}-{losses:g}'
    return f'{text}-{ties:g}' if ties else text


def names_list(items: list[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    if len(items) <= 2:
        return ' and '.join(items)
    return f'{", ".join(items[:-1])} and {items[-1]}'


def _rarity(rank: int) -> float:
    """1.0 for a record, decaying with rank."""
    return 1.0 / math.pow(rank, 0.6)


def _scope_tags(bracket: str) -> list[str]:
    return [bracket]


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class WeekContext:
    """Everything a detector needs: the target week and the history before it."""

    def __init__(
        self,
        team_games: list[TeamGame],
        player_games: list[PlayerGame],
        season: int,
        week: int,
        first_season: int | None = None,
        drafts: Iterable[Draftee] = (),
        trades: Iterable[Trade] = (),
        owner_names: dict[str, str] | None = None,
        rookie_seasons: dict[str, int] | None = None,
    ):
        target = (season, week)
        if first_season is not None:
            team_games = [g for g in team_games if g.season >= first_season]
            player_games = [g for g in player_games if g.season >= first_season]
        self.season = season
        self.week = week
        self.target = target
        self.team_all = sorted((g for g in team_games if g.order <= target), key=lambda g: g.order)
        # Starters drive every player record; bench rows only feed lineup notes.
        in_range = sorted((g for g in player_games if g.order <= target), key=lambda g: g.order)
        self.player_all = [g for g in in_range if g.starter]
        self.bench_all = [g for g in in_range if not g.starter]
        self.bench_current = [g for g in self.bench_all if g.order == target]
        self.drafts = [d for d in drafts if d.season <= season]
        self.trades = [t for t in trades if t.order <= target]
        self.owner_names = owner_names or {}
        self.rookie_seasons = rookie_seasons or {}
        self.current = [g for g in self.team_all if g.order == target]
        self.history = [g for g in self.team_all if g.order < target]
        self.player_current = [g for g in self.player_all if g.order == target]
        self.player_history = [g for g in self.player_all if g.order < target]
        self.index = week_index(g.order for g in self.team_all)

    def gap_weeks(self, order: tuple[int, int]) -> int:
        return self.index.get(self.target, 0) - self.index.get(order, 0)

    def matchups(self) -> list[tuple[TeamGame, TeamGame]]:
        """This week's matchups, each listed once as (winner-or-first, other)."""
        seen = set()
        pairs = []
        for game in self.current:
            key = (game.abbrev, game.opp_abbrev)
            if key in seen or (game.opp_abbrev, game.abbrev) in seen:
                continue
            opponent = next(
                (
                    g
                    for g in self.current
                    if g.abbrev == game.opp_abbrev and g.opp_abbrev == game.abbrev
                ),
                None,
            )
            if opponent is None:
                continue
            seen.add(key)
            first = game.won or (not opponent.won and game.score >= opponent.score)
            pairs.append((game, opponent) if first else (opponent, game))
        return pairs

    def franchise_games(self, franchise: str, games: Iterable[TeamGame]) -> list[TeamGame]:
        return [g for g in games if franchise in g.franchises]


def _primary_franchise(game: TeamGame) -> str:
    return game.franchises[0] if game.franchises else game.abbrev


def _unique_games(games: Iterable[TeamGame]) -> list[TeamGame]:
    """One row per matchup (team rows come in mirrored pairs)."""
    seen = set()
    out = []
    for g in games:
        key = (g.season, g.week, *sorted((g.abbrev, g.opp_abbrev)))
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


def _most_since(
    ctx: WeekContext,
    value: float,
    games: Iterable[TeamGame],
    get: Callable[[TeamGame], float],
    higher: bool = True,
) -> TeamGame | None:
    """The latest prior game that matched or beat `value`, or None for a record."""
    latest = None
    for g in games:
        if g.order >= ctx.target:
            continue
        v = get(g)
        matched = v >= value if higher else v <= value
        if matched and (latest is None or g.order > latest.order):
            latest = g
    return latest


# --------------------------------------------------------------------------- #
# League + franchise team detectors
# --------------------------------------------------------------------------- #


def _team_score_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    scored = [g for g in ctx.team_all if g.score > 0]
    league_scores = [g.score for g in scored]
    for game in ctx.current:
        if game.score <= 0:
            continue
        for higher, word, fewest in ((True, 'highest', 'most'), (False, 'lowest', 'fewest')):
            rank, total, tied = rank_of(game.score, league_scores, higher)
            franchise = _primary_franchise(game)
            history = [g for g in scored if franchise in g.franchises]
            parts = []
            category = TEAM
            notability = 0.0
            if rank <= LEAGUE_TOP:
                parts.append(f'{rank_phrase(rank, tied, word)} score in league history')
                category = LEAGUE
                notability = _rarity(rank)
            elif len(history) >= MIN_FRANCHISE_GAMES:
                f_rank, _, f_tied = rank_of(game.score, [g.score for g in history], higher)
                if f_rank <= FRANCHISE_TOP:
                    parts.append(
                        f'{rank_phrase(f_rank, f_tied, fewest)} points in franchise history'
                    )
                    notability = 0.8 * _rarity(f_rank)
            since = _most_since(ctx, game.score, history, lambda g: g.score, higher)
            if since is not None:
                gap = ctx.gap_weeks(since.order)
                if parts and gap >= SINCE_MIN_GAP_WEEKS:
                    parts.append(f'the {fewest} since {when(since.week_label, since.season)}')
                elif not parts and gap >= SINCE_STANDALONE_GAP_WEEKS:
                    parts.append(
                        f'the {fewest} points since {when(since.week_label, since.season)}'
                    )
                    notability = 0.45 + min(gap, 102) / 102 * 0.25
            if not parts:
                continue
            text = f"{team(game.abbrev)}'s {number(game.score)} was {' and '.join(parts)}"
            facts.append(
                Fact(
                    id=f'team_score_{"high" if higher else "low"}',
                    category=category,
                    subjects=[game.abbrev],
                    template=text + '.',
                    notability=notability,
                    tags=_scope_tags(game.bracket),
                )
            )
    return facts


def _club_size(values: Iterable[float], threshold: float, higher: bool = True) -> int:
    return sum(1 for v in values if (v >= threshold if higher else v <= threshold))


def _matchup_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    decided = [
        g for g in _unique_games(ctx.team_all) if g.single_game and g.score > 0 and g.opp_score > 0
    ]
    margins = [g.margin for g in decided]
    combined = [g.score + g.opp_score for g in decided]
    for winner, loser in ctx.matchups():
        if not winner.single_game or winner.score <= 0 or loser.score <= 0:
            continue
        subjects = [winner.abbrev, loser.abbrev]
        tags = _scope_tags(winner.bracket)
        margin = winner.margin
        head = (
            f'{team(winner.abbrev)} and {team(loser.abbrev)} tied at {number(winner.score)}'
            if margin == 0
            else f'{team(winner.abbrev)} beat {team(loser.abbrev)} by {number(margin)}'
        )

        # Blowouts
        rank, _, tied = rank_of(margin, margins, True)
        if rank <= LEAGUE_TOP:
            facts.append(
                Fact(
                    'margin_alltime',
                    LEAGUE,
                    subjects,
                    f'{head}, {rank_phrase(rank, tied, "largest")} margin of victory in league history.',
                    _rarity(rank),
                    tags,
                )
            )
        else:
            for threshold in (100, 90, 80, 70, 60, 50, 40):
                if margin >= threshold:
                    size = _club_size(margins, threshold)
                    if size <= MARGIN_CLUB_MAX:
                        facts.append(
                            Fact(
                                'margin_club',
                                LEAGUE,
                                subjects,
                                f'{head}, one of only {size} games decided by {threshold}+ points in league history.',
                                0.35 + 0.3 / size**0.5,
                                tags,
                            )
                        )
                    break

        # Nail-biters
        rank, _, tied = rank_of(margin, margins, False)
        close_club = _club_size(margins, max(margin, 1), False)
        if margin <= 3 and close_club <= MARGIN_CLUB_MAX:
            what = (
                'a tie'
                if margin == 0
                else f'{number(max(margin, 1))} point{"s" if max(margin, 1) != 1 else ""} or fewer'
            )
            if margin == 0:
                text = f'{head}, just the {ordinal(_club_size(margins, 0, False))} tie in league history.'
            else:
                text = (
                    f'{head}, one of only {close_club} games decided by {what} in league history.'
                )
            facts.append(
                Fact('margin_close', LEAGUE, subjects, text, 0.4 + 0.3 / close_club**0.5, tags)
            )

        # Shootouts
        total = winner.score + loser.score
        rank, _, tied = rank_of(total, combined, True)
        if rank <= LEAGUE_TOP:
            facts.append(
                Fact(
                    'combined_alltime',
                    LEAGUE,
                    subjects,
                    f'{team(winner.abbrev)} ({number(winner.score)}) and {team(loser.abbrev)} '
                    f'({number(loser.score)}) combined for {number(total)}, '
                    f'{rank_phrase(rank, tied, "most")} in a matchup in league history.',
                    0.9 * _rarity(rank),
                    tags,
                )
            )

        # Hard-luck losses and lucky wins
        losing = [g.score for g in ctx.team_all if g.single_game and g.lost and g.score > 0]
        rank, _, tied = rank_of(loser.score, losing, True)
        if margin > 0 and rank <= LEAGUE_TOP_SHORT:
            facts.append(
                Fact(
                    'losing_score_high',
                    LEAGUE,
                    [loser.abbrev],
                    f"{team(loser.abbrev)}'s {number(loser.score)} in a loss to {team(winner.abbrev)} is "
                    f'{rank_phrase(rank, tied, "highest")} losing score in league history.',
                    0.85 * _rarity(rank),
                    tags,
                )
            )
        winning = [g.score for g in ctx.team_all if g.single_game and g.won and g.score > 0]
        rank, _, tied = rank_of(winner.score, winning, False)
        if margin > 0 and rank <= LEAGUE_TOP_SHORT:
            facts.append(
                Fact(
                    'winning_score_low',
                    LEAGUE,
                    [winner.abbrev],
                    f'{team(winner.abbrev)} won with just {number(winner.score)}, '
                    f'{rank_phrase(rank, tied, "lowest")} winning score in league history.',
                    0.85 * _rarity(rank),
                    tags,
                )
            )
    return facts


def _league_week_facts(ctx: WeekContext) -> list[Fact]:
    """Whole-week numbers, averaged per team so 8- and 10-team years compare."""
    by_week: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        by_week[g.order].append(g)
    complete = {
        order: games
        for order, games in by_week.items()
        if games and all(g.score > 0 for g in games)
    }
    if ctx.target not in complete:
        return []
    averages = {
        order: sum(g.score for g in games) / len(games) for order, games in complete.items()
    }
    tops = {order: max(g.score for g in games) for order, games in complete.items()}
    current = complete[ctx.target]
    tags = sorted({g.bracket for g in current})
    facts = []
    avg = averages[ctx.target]
    for higher, word in ((True, 'highest'), (False, 'lowest')):
        rank, _, tied = rank_of(round(avg, 1), [round(v, 1) for v in averages.values()], higher)
        if rank <= LEAGUE_TOP_SHORT:
            facts.append(
                Fact(
                    f'league_week_{"high" if higher else "low"}',
                    LEAGUE,
                    [],
                    f'Teams averaged {number(round(avg, 1))} points this week, '
                    f'{rank_phrase(rank, tied, word)}-scoring week in league history.',
                    0.95 * _rarity(rank),
                    tags,
                )
            )
    top = tops[ctx.target]
    rank, _, tied = rank_of(top, list(tops.values()), False)
    if rank <= 3:
        leader = next(g for g in current if g.score == top)
        facts.append(
            Fact(
                'week_top_low',
                LEAGUE,
                [leader.abbrev],
                f"{team(leader.abbrev)}'s {number(top)} led the league, "
                f'{rank_phrase(rank, tied, "lowest")} score to top a week in league history.',
                0.7 * _rarity(rank),
                tags,
            )
        )
    return facts


def _runs(results: list[str]) -> list[tuple[str, int]]:
    """Collapse a W/L/T sequence into (result, length) runs."""
    runs: list[tuple[str, int]] = []
    for r in results:
        if runs and runs[-1][0] == r:
            runs[-1] = (r, runs[-1][1] + 1)
        else:
            runs.append((r, 1))
    return runs


def _result(game: TeamGame) -> str:
    return 'W' if game.won else 'L' if game.lost else 'T'


def _franchise_results(ctx: WeekContext, regular_only: bool) -> dict[str, list[TeamGame]]:
    """Each franchise's decided games in order. Streaks follow every game a
    team plays (a playoff loss ends a win streak); season records and pace
    stay regular-season only."""
    out: dict[str, list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        if (regular_only and g.bracket != REGULAR) or not g.decided or g.score <= 0:
            continue
        for f in g.franchises:
            out[f].append(g)
    return out


def _streak_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    by_franchise = _franchise_results(ctx, regular_only=False)
    regular_by_franchise = _franchise_results(ctx, regular_only=True)
    # Every run that has ever happened, per result type, for league ranking.
    league_runs: dict[str, list[int]] = defaultdict(list)
    for games in by_franchise.values():
        for result, length in _runs([_result(g) for g in games]):
            league_runs[result].append(length)
    regular_league_runs: dict[str, list[int]] = defaultdict(list)
    for games in regular_by_franchise.values():
        for result, length in _runs([_result(g) for g in games]):
            regular_league_runs[result].append(length)

    for game in ctx.current:
        if not game.decided or game.score <= 0:
            continue
        franchise = _primary_franchise(game)
        games = by_franchise.get(franchise, [])
        if not games or games[-1].order != ctx.target:
            continue
        runs = _runs([_result(g) for g in games])
        result, length = runs[-1]
        word = {'W': 'won', 'L': 'lost'}.get(result)

        # A regular-season-only streak runs longer when it skips past playoff
        # or consolation results; it is only ever reported with that caveat.
        regular_length = 0
        regular_games = regular_by_franchise.get(franchise, [])
        if game.bracket == REGULAR and regular_games and regular_games[-1].order == ctx.target:
            regular_result, n = _runs([_result(g) for g in regular_games])[-1]
            if regular_result == result and n > length:
                regular_length = n

        # One number per team: when the regular-season run is longer, it is the
        # one reported (with its label), never both side by side.
        if word and length >= STREAK_MIN and not regular_length:
            rank, _, tied = rank_of(length, league_runs[result], True)
            franchise_runs = [n for r, n in runs if r == result]
            kind = 'win' if result == 'W' else 'losing'
            text = f'{team(game.abbrev)} {has(game.abbrev)} {word} {length} straight'
            notability = 0.3 + 0.04 * min(length, 10)
            if rank <= 3:
                text += f', {rank_phrase(rank, tied, "longest")} {kind} streak in league history'
                notability = max(0.9 * _rarity(rank), 0.65)
            elif max(franchise_runs) == length and len(franchise_runs) > 1:
                text += f', the longest {kind} streak in franchise history'
                notability = 0.6
            facts.append(
                Fact(
                    f'streak_{kind}',
                    TEAM,
                    [game.abbrev],
                    text + '.',
                    notability,
                    _scope_tags(game.bracket),
                )
            )
        elif word and regular_length >= STREAK_MIN:
            kind = 'win' if result == 'W' else 'losing'
            rank, _, tied = rank_of(regular_length, regular_league_runs[result], True)
            text = (
                f'{team(game.abbrev)} {has(game.abbrev)} {word} {regular_length} '
                'straight regular-season games'
            )
            notability = 0.25 + 0.04 * min(regular_length, 10)
            if rank <= 3:
                text += (
                    f', {rank_phrase(rank, tied, "longest")} regular-season {kind} streak '
                    'in league history'
                )
                notability = max(0.8 * _rarity(rank), 0.55)
            facts.append(
                Fact(
                    f'streak_{kind}_regular',
                    TEAM,
                    [game.abbrev],
                    text + '.',
                    notability,
                    ['regular'],
                )
            )
        if len(runs) >= 2:
            prev_result, prev_length = runs[-2]
            # Only the game that ended the streak, not every week after it.
            if (
                length == 1
                and result != prev_result
                and prev_result in ('W', 'L')
                and prev_length >= SNAPPED_STREAK_MIN
            ):
                if prev_result == 'W':
                    text = f"{team(game.opp_abbrev)} snapped {team(game.abbrev)}'s {prev_length}-game win streak."
                else:
                    text = (
                        f'{team(game.abbrev)} snapped {article(prev_length)} '
                        f'{prev_length}-game losing streak.'
                    )
                facts.append(
                    Fact(
                        'streak_snapped',
                        TEAM,
                        [game.abbrev, game.opp_abbrev] if prev_result == 'W' else [game.abbrev],
                        text,
                        0.4 + 0.04 * min(prev_length, 10),
                        _scope_tags(game.bracket),
                    )
                )
    return facts


NUMBER_WORDS = {2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight'}


def _season_start_facts(ctx: WeekContext) -> list[Fact]:
    """Unbeaten and winless starts. Teams sharing a start this week get one
    combined note instead of one "first time since" line apiece."""
    facts = []
    by_franchise = _franchise_results(ctx, regular_only=True)
    shared: dict[str, list[tuple[TeamGame, str | None, int]]] = defaultdict(list)
    prior_counts: dict[str, list[int]] = {}
    for game in ctx.current:
        if game.bracket != REGULAR or not game.decided:
            continue
        franchise = _primary_franchise(game)
        season_games = [g for g in by_franchise.get(franchise, []) if g.season == ctx.season]
        n = len(season_games)
        if n < 3 or season_games[-1].order != ctx.target:
            continue
        for result, label in (('W', f'{n}-0'), ('L', f'0-{n}')):
            if not all(_result(g) == result for g in season_games):
                continue
            # Every earlier franchise-season that opened the same way.
            starts = []
            for f, games in by_franchise.items():
                seasons: dict[int, list[TeamGame]] = defaultdict(list)
                for g in games:
                    seasons[g.season].append(g)
                for season, rows in seasons.items():
                    if season == ctx.season:
                        continue
                    if len(rows) >= n and all(_result(g) == result for g in rows[:n]):
                        starts.append((f, season))
            mine = sorted(s for f, s in starts if f == franchise)
            league_count = len(starts) + 1
            per_season: dict[int, int] = defaultdict(int)
            for _, season in starts:
                per_season[season] += 1
            prior_counts[label] = list(per_season.values())
            if not mine:
                since = 'first time in franchise history'
            elif ctx.season - mine[-1] >= 2:
                since = f'first time since {mine[-1]}'
            else:
                since = None
            shared[label].append((game, since, league_count))
            parts = []
            if league_count == 1:
                parts.append(f'the first {label} start in league history')
            else:
                if not mine:
                    parts.append('for the first time in franchise history')
                elif ctx.season - mine[-1] >= 2:
                    parts.append(f'for the first time since {mine[-1]}')
                if league_count <= RARE_CLUB_MAX:
                    parts.append(f'just the {nth(league_count)} {label} start in league history')
            if not parts:
                continue
            text = f'{team(game.abbrev)} {is_(game.abbrev)} {label}'
            for part in parts:
                text += (' ' if part.startswith('for ') else ', ') + part
            text += '.'
            facts.append(
                Fact(
                    'season_start',
                    TEAM,
                    [game.abbrev],
                    text,
                    0.5 + 0.4 / league_count**0.5 if league_count <= RARE_CLUB_MAX else 0.45,
                    ['regular'],
                )
            )
    for label, entries in shared.items():
        if len(entries) < 2:
            continue
        subjects = [entry[0].abbrev for entry in entries]
        facts = [x for x in facts if not (x.id == 'season_start' and x.subjects[0] in subjects)]
        n = sum(int(x) for x in label.split('-'))
        prior = prior_counts.get(label, [])
        head = f'{NUMBER_WORDS.get(len(entries), str(len(entries)))} teams are {label}'
        if not prior:
            head += f', the first {label} starts in league history'
        elif len(entries) > max(prior):
            head += f', the most through {n} games in league history'
        elif len(entries) == max(prior):
            head += f', tied for the most through {n} games in league history'
        items = [
            team(leader.abbrev) + (f' ({note})' if note and prior else '')
            for leader, note, _ in entries
        ]
        facts.append(
            Fact(
                'season_start_shared',
                LEAGUE,
                subjects,
                f'{head}: {names_list(items)}.',
                0.45 + (0.2 if not prior or len(entries) >= max(prior) else 0),
                ['regular'],
            )
        )
    return facts


def _head_to_head_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    for winner, loser in ctx.matchups():
        if not winner.won or winner.score <= 0:
            continue
        a, b = _primary_franchise(winner), _primary_franchise(loser)
        series = [
            g
            for g in ctx.team_all
            if g.decided and a in g.franchises and b in g.opp_franchises and g.score > 0
        ]
        wins = sum(1 for g in series if g.won)
        losses = sum(1 for g in series if g.lost)
        record = f'{wins}-{losses}' + (
            f'-{len(series) - wins - losses}' if len(series) > wins + losses else ''
        )
        runs = _runs([_result(g) for g in series])
        streak = runs[-1][1] if runs and runs[-1][0] == 'W' else 0
        prior_wins = [g for g in series[:-1] if g.won]
        subjects = [winner.abbrev, loser.abbrev]
        tags = _scope_tags(winner.bracket)
        if len(series) >= 3 and not prior_wins:
            facts.append(
                Fact(
                    'h2h_first_win',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} beat {team(loser.abbrev)} for the first time in '
                    f'{len(series)} meetings.',
                    0.6 + 0.02 * min(len(series), 10),
                    tags,
                )
            )
        elif prior_wins and ctx.gap_weeks(prior_wins[-1].order) >= SINCE_STANDALONE_GAP_WEEKS:
            last = prior_wins[-1]
            facts.append(
                Fact(
                    'h2h_drought',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} beat {team(loser.abbrev)} for the first time since '
                    f'{when(last.week_label, last.season)} (series: {record}).',
                    0.55,
                    tags,
                )
            )
        elif streak >= STREAK_MIN:
            facts.append(
                Fact(
                    'h2h_streak',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} {has(winner.abbrev)} won {streak} straight against '
                    f'{team(loser.abbrev)} '
                    f'(series: {record}).',
                    0.35 + 0.04 * min(streak, 10),
                    tags,
                )
            )
        elif len(series) >= SERIES_LEAD_MIN_GAMES and wins - 1 == losses:
            facts.append(
                Fact(
                    'h2h_lead',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} beat {team(loser.abbrev)} to break a tie in the '
                    f'all-time series and take a {record} lead.',
                    0.45,
                    tags,
                )
            )
        elif len(series) >= SERIES_LEAD_MIN_GAMES and wins == losses:
            facts.append(
                Fact(
                    'h2h_even',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} beat {team(loser.abbrev)} to even the all-time '
                    f'series at {record}.',
                    0.4,
                    tags,
                )
            )
    return facts


def _pace_facts(ctx: WeekContext) -> list[Fact]:
    """Points for through N regular-season games, against every franchise-season."""
    facts = []
    by_franchise = _franchise_results(ctx, regular_only=True)
    season_rows: dict[tuple[str, int], list[TeamGame]] = defaultdict(list)
    for f, games in by_franchise.items():
        for g in games:
            season_rows[(f, g.season)].append(g)
    for game in ctx.current:
        if game.bracket != REGULAR:
            continue
        franchise = _primary_franchise(game)
        mine = season_rows.get((franchise, ctx.season), [])
        n = len(mine)
        if n < 3 or mine[-1].order != ctx.target:
            continue
        totals = [sum(g.score for g in rows[:n]) for rows in season_rows.values() if len(rows) >= n]
        total = sum(g.score for g in mine)
        for higher, word in ((True, 'most'), (False, 'fewest')):
            rank, _, tied = rank_of(total, totals, higher)
            if rank <= 3:
                facts.append(
                    Fact(
                        f'pace_{"high" if higher else "low"}',
                        TEAM,
                        [game.abbrev],
                        f'{team(game.abbrev)} {has(game.abbrev)} scored {number(total)} points '
                        f'through {n} games, '
                        f'{rank_phrase(rank, tied, word)} through {n} games in league history.',
                        0.75 * _rarity(rank),
                        ['regular'],
                    )
                )
    return facts


def _top_half_facts(ctx: WeekContext) -> list[Fact]:
    """Consecutive regular-season weeks finishing in the top half of the league."""
    by_week: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        if g.bracket == REGULAR and g.score > 0:
            by_week[g.order].append(g)
    top_half: dict[str, list[tuple[tuple[int, int], bool]]] = defaultdict(list)
    for order in sorted(by_week):
        games = by_week[order]
        cutoff = len(games) // 2
        for g in games:
            rank = 1 + sum(1 for other in games if other.score > g.score)
            for f in g.franchises:
                top_half[f].append((order, rank <= cutoff))
    league_runs: list[int] = []
    for rows in top_half.values():
        league_runs.extend(
            n for r, n in _runs(['Y' if hit else 'N' for _, hit in rows]) if r == 'Y'
        )
    facts = []
    for game in ctx.current:
        if game.bracket != REGULAR:
            continue
        rows = top_half.get(_primary_franchise(game), [])
        if not rows or rows[-1][0] != ctx.target:
            continue
        result, length = _runs(['Y' if hit else 'N' for _, hit in rows])[-1]
        if result != 'Y' or length < 5:
            continue
        rank, _, tied = rank_of(length, league_runs, True)
        text = (
            f'{team(game.abbrev)} {has(game.abbrev)} finished in the top half '
            f'{length} straight weeks'
        )
        if rank <= 3:
            text += f', {rank_phrase(rank, tied, "longest")} such run in league history'
        facts.append(
            Fact(
                'top_half_streak',
                TEAM,
                [game.abbrev],
                text + '.',
                0.45 + (0.3 if rank <= 3 else 0),
                ['regular'],
            )
        )
    return facts


# --------------------------------------------------------------------------- #
# Player detectors
# --------------------------------------------------------------------------- #


def _player_label(p: PlayerGame) -> str:
    return f'{p.name} ({team(p.abbrev)})'


def _player_game_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    all_scores = [p.score for p in ctx.player_all]
    by_position: dict[str, list[PlayerGame]] = defaultdict(list)
    for p in ctx.player_all:
        by_position[p.position].append(p)

    for p in ctx.player_current:
        parts = []
        notability = 0.0
        category = PLAYER
        tags = _scope_tags(p.bracket)

        rank, _, tied = rank_of(p.score, all_scores, True)
        if rank <= LEAGUE_TOP and p.score > 0:
            parts.append(
                f'{rank_phrase(rank, tied, "highest")} single-game score in league history'
            )
            notability = _rarity(rank)
        elif p.position in RANKED_POSITIONS:
            pos_scores = [g.score for g in by_position[p.position]]
            rank, _, tied = rank_of(p.score, pos_scores, True)
            if rank <= LEAGUE_TOP_SHORT and p.score > 0 and tied <= 2:
                parts.append(
                    f'{rank_phrase(rank, tied, "best")} {p.position} game in league history'
                )
                notability = 0.85 * _rarity(rank)

        # "Nth player ever to score X+"
        club: tuple[int, list[PlayerGame], str | None] | None = None
        for threshold in range(int(p.score // 5 * 5), 0, -5):
            if threshold < 20:
                break
            games = [g for g in ctx.player_all if g.score >= threshold]
            if len(games) <= PLAYER_CLUB_MAX_GAMES:
                club = (threshold, games, None)
            break
        if club is None and p.position in CLUB_POSITIONS:
            for threshold in range(int(p.score // 5 * 5), 0, -5):
                if threshold < 15:
                    break
                games = [g for g in by_position[p.position] if g.score >= threshold]
                if len(games) <= POSITION_CLUB_MAX_GAMES:
                    club = (threshold, games, p.position)
                break
        if club:
            threshold, games, position = club
            prior_players = {g.player_key for g in games if g.order < ctx.target}
            players_through = len(prior_players | {p.player_key})
            who = f'{position} ' if position else 'player '
            if p.player_key in prior_players:
                times = sum(1 for g in games if g.player_key == p.player_key)
                parts.append(
                    f'his {ordinal(times)} {threshold}+ game; only {players_through} '
                    f'{who.strip()}s have ever reached {threshold}'
                )
            else:
                parts.append(f'just the {nth(players_through)} {who}ever to score {threshold}+')
            notability = max(notability, 0.5 + 0.4 / players_through**0.5)

        if not parts:
            continue
        facts.append(
            Fact(
                'player_game',
                category,
                [p.abbrev],
                f'{_player_label(p)} scored {number(p.score)}, ' + ', and '.join(parts) + '.',
                notability,
                tags,
            )
        )

        # Franchise single-game record for a player
        franchise = p.franchises[0] if p.franchises else p.abbrev
        franchise_scores = [g.score for g in ctx.player_all if franchise in g.franchises]
        f_rank, _, f_tied = rank_of(p.score, franchise_scores, True)
        if (
            f_rank == 1
            and len(franchise_scores) > 100
            and not any('league history' in x for x in parts[:1])
        ):
            facts.append(
                Fact(
                    'player_franchise_record',
                    PLAYER,
                    [p.abbrev],
                    f"{p.name}'s {number(p.score)} is "
                    f'{"tied for " if f_tied else ""}the most by a {team(p.abbrev)} player in franchise history.',
                    0.7,
                    tags,
                )
            )
    return facts


def _player_low_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    by_position: dict[str, list[float]] = defaultdict(list)
    for p in ctx.player_all:
        by_position[p.position].append(p.score)
    shame_count = sum(1 for p in ctx.player_all if p.position == 'D/ST' and p.score == -6)
    for p in ctx.player_current:
        tags = _scope_tags(p.bracket)
        if p.position == 'D/ST' and p.score == -6:
            facts.append(
                Fact(
                    'defensive_shame',
                    PLAYER,
                    [p.abbrev],
                    f'The {_player_label(p)} defense bottomed out at -6, the '
                    f'{ordinal(shame_count)} entry in the Defensive Hall of Shame.',
                    0.55,
                    tags,
                )
            )
            continue
        if p.position not in ('QB', 'RB', 'WR', 'TE', 'K'):
            continue
        rank, _, tied = rank_of(p.score, by_position[p.position], False)
        if rank <= 3 and p.score < 0 and tied <= 2:
            facts.append(
                Fact(
                    'player_low',
                    PLAYER,
                    [p.abbrev],
                    f'{_player_label(p)} posted {number(p.score)}, '
                    f'{rank_phrase(rank, tied, "worst")} {p.position} game in league history.',
                    0.6 * _rarity(rank),
                    tags,
                )
            )
    return facts


def _player_career_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    career: dict[str, float] = defaultdict(float)
    big_games: dict[str, int] = defaultdict(int)
    for p in ctx.player_history:
        career[p.player_key] += p.score
        if p.score >= BIG_GAME_POINTS:
            big_games[p.player_key] += 1
    after = dict(career)
    after_big = dict(big_games)
    for p in ctx.player_current:
        after[p.player_key] = after.get(p.player_key, 0.0) + p.score
        if p.score >= BIG_GAME_POINTS:
            after_big[p.player_key] = after_big.get(p.player_key, 0) + 1

    for p in ctx.player_current:
        before, now = career.get(p.player_key, 0.0), after[p.player_key]
        crossed = [m for m in CAREER_MILESTONES if before < m <= now]
        club = sum(1 for total in after.values() if crossed and total >= crossed[-1])
        if crossed and p.position in MILESTONE_POSITIONS and club <= MILESTONE_CLUB_MAX:
            mark = crossed[-1]
            facts.append(
                Fact(
                    'career_milestone',
                    PLAYER,
                    [p.abbrev],
                    f'{_player_label(p)} passed {number(mark)} career QPFL points as a starter, '
                    f'the {nth(club)} player to get there.',
                    0.4 + 0.4 / club**0.5,
                    _scope_tags(p.bracket),
                )
            )
        if p.score >= BIG_GAME_POINTS:
            count = after_big[p.player_key]
            rank, _, tied = rank_of(count, list(after_big.values()), True)
            if count >= 3 and rank <= 3:
                facts.append(
                    Fact(
                        'career_big_games',
                        PLAYER,
                        [p.abbrev],
                        f'{_player_label(p)} has {count} career {BIG_GAME_POINTS}-point games, '
                        f'{rank_phrase(rank, tied, "most")} in league history.',
                        0.5 + 0.2 * _rarity(rank),
                        _scope_tags(p.bracket),
                    )
                )
    return facts


def _player_streak_facts(ctx: WeekContext) -> list[Fact]:
    """Consecutive starts at HOT_STREAK_POINTS+ within one season."""
    starts: dict[tuple[str, int], list[PlayerGame]] = defaultdict(list)
    for p in ctx.player_all:
        starts[(p.player_key, p.season)].append(p)
    league_runs: list[int] = []
    current_runs: dict[str, int] = {}
    for (key, season), rows in starts.items():
        runs = _runs(['Y' if g.score >= HOT_STREAK_POINTS else 'N' for g in rows])
        league_runs.extend(n for r, n in runs if r == 'Y')
        if season == ctx.season and rows[-1].order == ctx.target and runs[-1][0] == 'Y':
            current_runs[key] = runs[-1][1]
    facts = []
    for p in ctx.player_current:
        length = current_runs.get(p.player_key, 0)
        if length < HOT_STREAK_MIN:
            continue
        rank, _, tied = rank_of(length, league_runs, True)
        text = f'{_player_label(p)} has scored {HOT_STREAK_POINTS}+ in {length} straight starts'
        notability = 0.4 + 0.05 * length
        if rank <= 3:
            text += f', {rank_phrase(rank, tied, "longest")} streak in league history'
            notability = 0.8 * _rarity(rank)
        facts.append(
            Fact(
                'player_hot_streak',
                PLAYER,
                [p.abbrev],
                text + '.',
                notability,
                _scope_tags(p.bracket),
            )
        )
    return facts


def _cycle_facts(ctx: WeekContext) -> list[Fact]:
    """A win that completes a beat-every-team cycle faster than the franchise
    (or anyone in the league) ever had before."""
    rivals = {_primary_franchise(g) for g in ctx.current}
    cycles = all_cycles(ctx.team_all, rivals)
    prior = [c for c in cycles if c.end.order < ctx.target]
    this_week = [c for c in cycles if c.end.order == ctx.target]
    league_best = min(prior, key=lambda c: (c.games, c.end.order), default=None)
    fastest_now = min((c.games for c in this_week), default=None)
    facts = []
    for cycle in this_week:
        mine = [c.games for c in prior if c.franchise == cycle.franchise]
        span = (
            f'{team(cycle.end.abbrev)} {has(cycle.end.abbrev)} now beaten every other team in a span of '
            f'{cycle.games} games ({when(cycle.start.week_label, cycle.start.season)} '
            f'to {when(cycle.end.week_label, cycle.end.season)})'
        )
        # A league record has to beat every earlier cycle and match the best
        # one finished this same week.
        sets_record = (league_best is None or cycle.games < league_best.games) and (
            cycle.games == fastest_now
        )
        if sets_record:
            record = ''
            if league_best is not None:
                holder = (
                    'their own'
                    if league_best.franchise == cycle.franchise
                    else f"{team(league_best.franchise)}'s"
                )
                record = f', breaking {holder} record of {league_best.games}'
            text, notability, category = (
                f'{span}, the fastest in league history{record}.',
                1.0,
                LEAGUE,
            )
        elif league_best is not None and cycle.games == league_best.games:
            holder = (
                'their own'
                if league_best.franchise == cycle.franchise
                else f"{team(league_best.franchise)}'s"
            )
            text, notability, category = f'{span}, tying {holder} league record.', 0.85, LEAGUE
        elif not mine:
            text, notability, category = (
                f'{span}, the first time the franchise has done it.',
                0.5,
                TEAM,
            )
        elif cycle.games < min(mine):
            text, notability, category = (
                f'{span}, the fastest in franchise history (previous best: {min(mine)}).',
                0.6,
                TEAM,
            )
        else:
            continue
        facts.append(
            Fact(
                'cycle_fastest',
                category,
                [cycle.end.abbrev],
                text,
                notability,
                _scope_tags(cycle.end.bracket),
            )
        )
    return facts


# --------------------------------------------------------------------------- #
# Lineup decisions (bench scores)
# --------------------------------------------------------------------------- #


def _left_on_bench(game: TeamGame) -> float | None:
    if game.optimal is None or game.score <= 0:
        return None
    return max(game.optimal - game.score, 0.0)


def _lineup_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    tracked = [g for g in ctx.team_all if _left_on_bench(g) is not None]
    left_all = [_left_on_bench(g) or 0.0 for g in tracked]
    # Losses a best-possible lineup would have won, per franchise-season.
    costly: dict[tuple[str, int], int] = defaultdict(int)
    for g in tracked:
        if g.single_game and g.lost and (g.optimal or 0) > g.opp_score:
            costly[(_primary_franchise(g), g.season)] += 1

    for game in ctx.current:
        left = _left_on_bench(game)
        if left is None:
            continue
        franchise = _primary_franchise(game)
        tags = _scope_tags(game.bracket)

        rank, _, tied = rank_of(left, left_all, True)
        history = [_left_on_bench(g) or 0.0 for g in tracked if franchise in g.franchises]
        head = (
            f'{team(game.abbrev)} left {number(left)} points on the bench '
            f'({number(game.score)} of a possible {number(game.optimal or 0)})'
        )
        if left > 0 and rank <= LEAGUE_TOP_SHORT:
            facts.append(
                Fact(
                    'bench_points',
                    LEAGUE,
                    [game.abbrev],
                    f'{head}, {rank_phrase(rank, tied, "most")} in league history.',
                    0.85 * _rarity(rank),
                    tags,
                )
            )
        elif left > 0 and len(history) >= MIN_FRANCHISE_GAMES:
            f_rank, _, f_tied = rank_of(left, history, True)
            if f_rank == 1:
                facts.append(
                    Fact(
                        'bench_points',
                        TEAM,
                        [game.abbrev],
                        f'{head}, {rank_phrase(1, f_tied, "most")} in franchise history.',
                        0.55,
                        tags,
                    )
                )

        count = costly[(franchise, game.season)]
        if (
            game.single_game
            and game.lost
            and (game.optimal or 0) > game.opp_score
            and (game.margin >= LINEUP_COST_MIN_MARGIN or count >= 3)
        ):
            text = (
                f'{team(game.abbrev)} lost to {team(game.opp_abbrev)} by '
                f'{number(game.margin)} but would have won by starting the best lineup on '
                f'the roster ({number(game.optimal or 0)})'
            )
            notability = 0.4 + min((game.optimal or 0) - game.opp_score, 30) / 100
            if count >= 2:
                text += f', the {ordinal(count)} time this season'
                rank, _, tied = rank_of(count, list(costly.values()), True)
                if count >= 3 and rank == 1:
                    text += f' and {rank_phrase(1, tied, "most")} in a season in league history'
                    notability = 0.75
                else:
                    notability += 0.05 * count
            facts.append(Fact('lineup_cost', TEAM, [game.abbrev], text + '.', notability, tags))

        if game.score == game.optimal:
            perfect = [g for g in tracked if franchise in g.franchises and g.score == g.optimal]
            prior = [g for g in perfect if g.order < ctx.target]
            if not prior and len(history) >= MIN_FRANCHISE_GAMES:
                text = (
                    f'{team(game.abbrev)} started the best possible lineup for the first '
                    'time in franchise history.'
                )
                notability = 0.6
            elif prior and ctx.gap_weeks(prior[-1].order) >= SINCE_STANDALONE_GAP_WEEKS:
                last = prior[-1]
                text = (
                    f'{team(game.abbrev)} started the best possible lineup for the first '
                    f'time since {when(last.week_label, last.season)}.'
                )
                notability = 0.45
            else:
                continue
            facts.append(Fact('perfect_lineup', TEAM, [game.abbrev], text, notability, tags))
    return facts


def _bench_player_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    every = [p.score for p in ctx.bench_all]
    by_position: dict[str, list[float]] = defaultdict(list)
    for p in ctx.bench_all:
        by_position[p.position].append(p.score)
    for p in ctx.bench_current:
        if p.score <= 0:
            continue
        rank, _, tied = rank_of(p.score, every, True)
        if rank <= LEAGUE_TOP_SHORT:
            what = f'{rank_phrase(rank, tied, "most")} by a benched player'
            notability = 0.8 * _rarity(rank)
        elif p.position in MILESTONE_POSITIONS:
            rank, _, tied = rank_of(p.score, by_position[p.position], True)
            if rank > 3 or tied > 2:
                continue
            what = f'{rank_phrase(rank, tied, "most")} by a benched {p.position}'
            notability = 0.6 * _rarity(rank)
        else:
            continue
        facts.append(
            Fact(
                'bench_player',
                PLAYER,
                [p.abbrev],
                f'{_player_label(p)} scored {number(p.score)} on the bench, {what} in league history.',
                notability,
                _scope_tags(p.bracket),
            )
        )
    return facts


# --------------------------------------------------------------------------- #
# Luck and schedule
# --------------------------------------------------------------------------- #


def _season_rows(ctx: WeekContext) -> dict[tuple[str, int], list[TeamGame]]:
    """Each franchise-season's decided regular-season games, in order."""
    rows: dict[tuple[str, int], list[TeamGame]] = defaultdict(list)
    for f, games in _franchise_results(ctx, regular_only=True).items():
        for g in games:
            rows[(f, g.season)].append(g)
    return rows


def _regular_weeks(ctx: WeekContext) -> dict[tuple[int, int], list[TeamGame]]:
    by_week: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        if g.bracket == REGULAR and g.score > 0:
            by_week[g.order].append(g)
    return by_week


def _current_rows(ctx: WeekContext, rows: dict[tuple[str, int], list[TeamGame]]):
    """(game, franchise, n, season rows) for this week's regular-season teams
    that have played at least 3 games."""
    for game in ctx.current:
        if game.bracket != REGULAR:
            continue
        franchise = _primary_franchise(game)
        mine = rows.get((franchise, ctx.season), [])
        if len(mine) >= 3 and mine[-1].order == ctx.target:
            yield game, franchise, len(mine), mine


def _all_play_facts(ctx: WeekContext) -> list[Fact]:
    """Record against the whole league each week, compared with the real one."""
    all_play: dict[tuple[tuple[int, int], str], tuple[int, int, int]] = {}
    for order, games in _regular_weeks(ctx).items():
        for g in games:
            others = [o.score for o in games if o is not g]
            all_play[(order, g.abbrev)] = (
                sum(1 for s in others if s < g.score),
                sum(1 for s in others if s > g.score),
                sum(1 for s in others if s == g.score),
            )

    def tally(games: list[TeamGame]) -> tuple[float, tuple[int, int, int]] | None:
        totals = [all_play.get((g.order, g.abbrev)) for g in games]
        if any(t is None for t in totals):
            return None
        w = sum(t[0] for t in totals if t)
        lost = sum(t[1] for t in totals if t)
        t_ = sum(t[2] for t in totals if t)
        played = w + lost + t_
        actual = sum(1.0 if g.won else 0.5 if not g.lost else 0.0 for g in games) / len(games)
        return actual - (w + 0.5 * t_) / played if played else 0.0, (w, lost, t_)

    rows = _season_rows(ctx)
    facts = []
    for game, _, n, mine in _current_rows(ctx, rows):
        mine_tally = tally(mine)
        if mine_tally is None:
            continue
        luck, (w, lost, t_) = mine_tally
        population = [x[0] for x in (tally(r[:n]) for r in rows.values() if len(r) >= n) if x]
        wins = sum(1 for g in mine if g.won)
        losses = sum(1 for g in mine if g.lost)
        actual = record(wins, losses, n - wins - losses)
        all_play_pct = (w + 0.5 * t_) / max(w + lost + t_, 1)
        for higher, word in ((True, 'luckiest'), (False, 'unluckiest')):
            # "Despite" only reads right when the all-play record points the
            # other way from the real one.
            if (luck <= 0 or all_play_pct > 0.5) if higher else (luck >= 0 or all_play_pct < 0.5):
                continue
            rank, _, tied = rank_of(luck, population, higher)
            if rank != 1:
                continue
            facts.append(
                Fact(
                    'all_play',
                    TEAM,
                    [game.abbrev],
                    f'{team(game.abbrev)} {is_(game.abbrev)} {actual} despite '
                    f'{article(w)} {record(w, lost, t_)} record against the whole league, '
                    f'{rank_phrase(rank, tied, word)} start through {n} games in league history.',
                    0.75 * _rarity(rank),
                    ['regular'],
                )
            )
    return facts


def _points_against_facts(ctx: WeekContext) -> list[Fact]:
    rows = _season_rows(ctx)
    facts = []
    for game, _, n, mine in _current_rows(ctx, rows):
        totals = [sum(g.opp_score for g in r[:n]) for r in rows.values() if len(r) >= n]
        total = sum(g.opp_score for g in mine)
        for higher, word in ((True, 'most'), (False, 'fewest')):
            rank, _, tied = rank_of(total, totals, higher)
            if rank == 1:
                facts.append(
                    Fact(
                        f'points_against_{"high" if higher else "low"}',
                        TEAM,
                        [game.abbrev],
                        f'Opponents have scored {number(total)} points against '
                        f'{team(game.abbrev)} through {n} games, '
                        f'{rank_phrase(rank, tied, word)} through {n} games in league history.',
                        0.6 * _rarity(rank),
                        ['regular'],
                    )
                )
    return facts


def _schedule_luck_facts(ctx: WeekContext) -> list[Fact]:
    """How far opponents scored above (or below) their own season averages."""
    rows = _season_rows(ctx)
    # Every team-season's regular-season scores, by its code that season.
    team_scores: dict[tuple[str, int], list[float]] = defaultdict(list)
    for g in ctx.team_all:
        if g.bracket == REGULAR and g.score > 0:
            team_scores[(g.abbrev, g.season)].append(g.score)

    def above(games: list[TeamGame], n: int) -> float | None:
        total = 0.0
        for g in games:
            scores = team_scores.get((g.opp_abbrev, g.season), [])[:n]
            if not scores:
                return None
            total += g.opp_score - sum(scores) / len(scores)
        return total

    facts = []
    for game, _, n, mine in _current_rows(ctx, rows):
        value = above(mine, n)
        if value is None:
            continue
        population = [
            v for v in (above(r[:n], n) for r in rows.values() if len(r) >= n) if v is not None
        ]
        for higher, word in ((True, 'above'), (False, 'below')):
            if (value <= 0) if higher else (value >= 0):
                continue
            rank, _, tied = rank_of(round(value, 1), [round(v, 1) for v in population], higher)
            if rank != 1:
                continue
            facts.append(
                Fact(
                    f'schedule_luck_{"tough" if higher else "easy"}',
                    TEAM,
                    [game.abbrev],
                    f'Opponents have scored a combined {number(round(abs(value), 1))} points '
                    f'{word} their season averages against {team(game.abbrev)} through {n} games, '
                    f'{rank_phrase(rank, tied, "most")} in league history.',
                    0.55 * _rarity(rank),
                    ['regular'],
                )
            )
    return facts


def _weekly_extreme_facts(ctx: WeekContext) -> list[Fact]:
    """Straight regular-season weeks with the league's top (or bottom) score."""
    by_week = _regular_weeks(ctx)
    facts = []
    for higher, word in ((True, 'top'), (False, 'lowest')):
        hits: dict[str, list[bool]] = defaultdict(list)
        last_order: dict[str, tuple[int, int]] = {}
        for order in sorted(by_week):
            games = by_week[order]
            best = (max if higher else min)(g.score for g in games)
            for g in games:
                for f in g.franchises:
                    hits[f].append(g.score == best)
                    last_order[f] = order
        league_runs = [
            n
            for seq in hits.values()
            for r, n in _runs(['Y' if h else 'N' for h in seq])
            if r == 'Y'
        ]
        for game in ctx.current:
            franchise = _primary_franchise(game)
            if game.bracket != REGULAR or last_order.get(franchise) != ctx.target:
                continue
            result, length = _runs(['Y' if h else 'N' for h in hits[franchise]])[-1]
            if result != 'Y' or length < (2 if higher else 3):
                continue
            rank, _, tied = rank_of(length, league_runs, True)
            text = (
                f"{team(game.abbrev)} posted the league's {word} score for the "
                f'{ordinal(length)} straight week'
            )
            notability = 0.35 + 0.08 * length
            if rank <= 2:
                text += f', {rank_phrase(rank, tied, "longest")} such run in league history'
                notability = max(notability, 0.75 * _rarity(rank))
            facts.append(
                Fact(
                    f'week_{"high" if higher else "low"}_streak',
                    TEAM,
                    [game.abbrev],
                    text + '.',
                    notability,
                    ['regular'],
                )
            )
    return facts


# --------------------------------------------------------------------------- #
# Standings and stakes
# --------------------------------------------------------------------------- #


def _team_seasons(ctx: WeekContext) -> dict[tuple[int, str], list[TeamGame]]:
    """Each team code's decided regular-season games per season. Team codes,
    not franchises, so a co-owned 2021 team counts once."""
    out: dict[tuple[int, str], list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        if g.bracket == REGULAR and g.decided and g.score > 0:
            out[(g.season, g.abbrev)].append(g)
    return out


def _win_loss(games: list[TeamGame]) -> str:
    wins = sum(1 for g in games if g.won)
    losses = sum(1 for g in games if g.lost)
    return record(wins, losses, len(games) - wins - losses)


def _playoff_odds_facts(ctx: WeekContext) -> list[Fact]:
    """'Teams that start 3-0 have made the playoffs 9 of 11 times.'"""
    seasons = _team_seasons(ctx)
    made = {(g.season, g.abbrev) for g in ctx.team_all if g.bracket == PLAYOFFS}
    # Only seasons whose playoffs are already in the books.
    finished = {s for s, _ in made if s < ctx.season}
    groups: dict[str, list[TeamGame]] = defaultdict(list)
    n = 0
    for game in ctx.current:
        mine = seasons.get((ctx.season, game.abbrev), [])
        if game.bracket != REGULAR or len(mine) < 3 or mine[-1].order != ctx.target:
            continue
        n = len(mine)
        if n >= regular_season_weeks(ctx.season):
            continue
        groups[_win_loss(mine)].append(game)
    facts = []
    for label, games in groups.items():
        sample = [
            key
            for key, rows in seasons.items()
            if key[0] in finished and len(rows) >= n and _win_loss(rows[:n]) == label
        ]
        hits = sum(1 for key in sample if key in made)
        total = len(sample)
        rate = hits / total if total else 0.0
        if (
            total < PLAYOFF_ODDS_MIN_SAMPLE
            or PLAYOFF_ODDS_EXTREME > rate > 1 - PLAYOFF_ODDS_EXTREME
        ):
            continue
        subjects = [g.abbrev for g in games]
        who = (
            f'{team(subjects[0])} {is_(subjects[0])}'
            if len(subjects) == 1
            else f'{names_list([team(a) for a in subjects])} are'
        )
        start = f'started {label}'
        if hits == 0:
            tail = f'no team that {start} has made the playoffs (0 for {total}).'
        elif hits == total:
            tail = f'every team that {start} has made the playoffs ({total} for {total}).'
        else:
            tail = f'teams that {start} have made the playoffs {hits} of {total} times.'
        facts.append(
            Fact(
                'playoff_odds',
                TEAM,
                subjects,
                f'{who} {label}; {tail}',
                0.4 + 0.25 * abs(rate - 0.5) * 2,
                ['regular'],
            )
        )
    return facts


def _rank_point_weeks(ctx: WeekContext, season: int) -> list[tuple[int, dict[str, float]]]:
    """Rank points earned each completed regular-season week: 1 for a win (½ a
    tie) plus the top-half bonus, split when teams tie across the cutoff."""
    by_week = {order: games for order, games in _regular_weeks(ctx).items() if order[0] == season}
    weeks = []
    bonus = top_half_value(season)
    for order in sorted(by_week):
        games = by_week[order]
        points = {g.abbrev: (1.0 if g.won else 0.5 if not g.lost else 0.0) for g in games}
        cutoff = len(games) // 2
        ordered = sorted(g.score for g in games)[::-1]
        for g in games:
            first = ordered.index(g.score) + 1
            tied = ordered.count(g.score)
            in_top = sum(1 for pos in range(first, first + tied) if pos <= cutoff)
            points[g.abbrev] += bonus * in_top / tied
        weeks.append((order[1], points))
    return weeks


def _playoff_status(totals: dict[str, float], remaining: int, bonus: float) -> dict[str, str]:
    """'clinched' / 'eliminated' for teams whose fate no remaining result can
    change. Ties count against the team, so this never calls one too early."""
    most = 1.0 + bonus
    status = {}
    for abbrev, mine in totals.items():
        others = [v for a, v in totals.items() if a != abbrev]
        if sum(1 for v in others if v + most * remaining >= mine) < PLAYOFF_SPOTS:
            status[abbrev] = 'clinched'
        elif sum(1 for v in others if v > mine + most * remaining) >= PLAYOFF_SPOTS:
            status[abbrev] = 'eliminated'
    return status


def _status_weeks(ctx: WeekContext, season: int) -> dict[str, dict[str, int]]:
    """For each team in a season, the games left when it clinched or was
    eliminated (first week only)."""
    totals: dict[str, float] = defaultdict(float)
    reached: dict[str, dict[str, int]] = defaultdict(dict)
    weeks = _rank_point_weeks(ctx, season)
    for played, (_, points) in enumerate(weeks, start=1):
        for abbrev, value in points.items():
            totals[abbrev] += value
        remaining = regular_season_weeks(season) - played
        for abbrev, state in _playoff_status(
            dict(totals), remaining, top_half_value(season)
        ).items():
            reached[abbrev].setdefault(state, remaining)
    return reached


def _clinch_facts(ctx: WeekContext) -> list[Fact]:
    if not any(g.bracket == REGULAR for g in ctx.current):
        return []
    now = _status_weeks(ctx, ctx.season)
    weeks = _rank_point_weeks(ctx, ctx.season)
    if not weeks or weeks[-1][0] != ctx.week:
        return []
    remaining = regular_season_weeks(ctx.season) - len(weeks)
    earlier = {s for s, _ in ctx.index if s < ctx.season}
    history: dict[str, list[int]] = defaultdict(list)
    for season in earlier:
        for states in _status_weeks(ctx, season).values():
            for state, left in states.items():
                history[state].append(left)
    facts = []
    for abbrev, states in now.items():
        for state, left in states.items():
            if left != remaining or (state == 'eliminated' and not left):
                continue  # reached earlier, or just the final standings
            text = (
                f'{team(abbrev)} clinched a playoff spot'
                if state == 'clinched'
                else f'{team(abbrev)} can no longer make the playoffs'
            )
            notability = 0.5 if state == 'clinched' else 0.4
            if left:
                text += f' with {left} game{"s" if left != 1 else ""} to play'
                rank, _, tied = rank_of(left, history[state] + [left], True)
                if rank <= 2 and history[state]:
                    kind = 'clinch' if state == 'clinched' else 'elimination'
                    text += f', {rank_phrase(rank, tied, "earliest")} {kind} in league history'
                    notability = 0.7 * _rarity(rank)
            facts.append(
                Fact(f'playoff_{state}', TEAM, [abbrev], text + '.', notability, ['regular'])
            )
    return facts


def _champions(ctx: WeekContext) -> dict[int, TeamGame]:
    """Each finished season's title-game winner."""
    return {g.season: g for g in ctx.history if g.title_game and g.won}


def _title_defense_facts(ctx: WeekContext) -> list[Fact]:
    champions = _champions(ctx)
    defending = champions.get(ctx.season - 1)
    if defending is None:
        return []
    rows = _season_rows(ctx)
    franchise = _primary_franchise(defending)
    mine = rows.get((franchise, ctx.season), [])
    n = len(mine)
    if n < 3 or mine[-1].order != ctx.target or mine[-1].bracket != REGULAR:
        return []

    def pct(games: list[TeamGame]) -> float:
        return sum(1.0 if g.won else 0.5 if not g.lost else 0.0 for g in games) / len(games)

    defenses = []
    for season, champ in champions.items():
        prior = rows.get((_primary_franchise(champ), season + 1), [])
        if season + 1 < ctx.season and len(prior) >= n:
            defenses.append(pct(prior[:n]))
    if len(defenses) < 3:
        return []
    value = pct(mine)
    game = mine[-1]
    facts = []
    for higher, word in ((True, 'best'), (False, 'worst')):
        rank, _, tied = rank_of(value, defenses + [value], higher)
        if rank != 1 or (value <= 0.5 if higher else value >= 0.5):
            continue
        facts.append(
            Fact(
                'title_defense',
                TEAM,
                [game.abbrev],
                f'Defending champion {team(game.abbrev)} {is_(game.abbrev)} {_win_loss(mine)}, '
                f'{rank_phrase(1, tied, word)} start to a title defense in league history.',
                0.8 if not tied else 0.6,
                ['regular'],
            )
        )
    return facts


# --------------------------------------------------------------------------- #
# Owner and player careers
# --------------------------------------------------------------------------- #


def _owner_facts(ctx: WeekContext) -> list[Fact]:
    """Owner (person, not franchise) milestones: career wins and points,
    playoffs included, across every team they have owned."""
    wins: dict[str, int] = defaultdict(int)
    points: dict[str, float] = defaultdict(float)
    for g in ctx.history:
        if g.score <= 0:
            continue
        for owner in g.owners:
            points[owner] += g.score
            wins[owner] += 1 if g.won else 0
    after_wins, after_points = dict(wins), dict(points)
    owner_team: dict[str, str] = {}
    for g in ctx.current:
        if g.score <= 0:
            continue
        for owner in g.owners:
            after_points[owner] = after_points.get(owner, 0.0) + g.score
            after_wins[owner] = after_wins.get(owner, 0) + (1 if g.won else 0)
            owner_team[owner] = g.abbrev
    facts = []
    for owner, abbrev in owner_team.items():
        name = ctx.owner_names.get(owner)
        if not name:
            continue
        for before, after, step, unit, minimum in (
            (wins.get(owner, 0), after_wins[owner], OWNER_WIN_MILESTONE, 'career wins', 25),
            (
                points.get(owner, 0.0),
                after_points[owner],
                OWNER_POINT_MILESTONE,
                'career points',
                5000,
            ),
        ):
            mark = int(after // step * step)
            if mark < minimum or before >= mark:
                continue
            totals = after_wins if unit == 'career wins' else after_points
            club = sum(1 for v in totals.values() if v >= mark)
            text = f'{name} reached {number(mark)} {unit}'
            text += (
                ', the first owner to get there'
                if club == 1
                else f', the {nth(club)} owner to get there'
            )
            facts.append(
                Fact(
                    'owner_milestone',
                    TEAM,
                    [abbrev],
                    text + '.',
                    0.45 + 0.3 / club**0.5,
                    _scope_tags(ctx.current[0].bracket),
                )
            )
    return facts


def _loyalty_facts(ctx: WeekContext) -> list[Fact]:
    """Starts by one player for one franchise."""
    starts: dict[tuple[str, str], int] = defaultdict(int)
    for p in ctx.player_all:
        if p.position in MILESTONE_POSITIONS:
            starts[(p.player_key, p.franchises[0] if p.franchises else p.abbrev)] += 1
    facts = []
    for p in ctx.player_current:
        if p.position not in MILESTONE_POSITIONS:
            continue
        key = (p.player_key, p.franchises[0] if p.franchises else p.abbrev)
        count = starts[key]
        best_other = max((n for k, n in starts.items() if k != key), default=0)
        record_now = count > best_other and count - 1 <= best_other
        if not record_now and (count < LOYALTY_MILESTONE * 3 or count % LOYALTY_MILESTONE):
            continue
        text = f'{p.name} made his {ordinal(count)} start for {team(p.abbrev)}'
        if count > best_other:
            text += ', the most by any player for one franchise'
        facts.append(
            Fact(
                'player_loyalty',
                PLAYER,
                [p.abbrev],
                text + '.',
                0.6 if record_now else 0.45,
                _scope_tags(p.bracket),
            )
        )
    return facts


def _versus_facts(ctx: WeekContext) -> list[Fact]:
    """A player's career average against one franchise (min. 5 games)."""
    games: dict[tuple[str, str], list[float]] = defaultdict(list)
    for p in ctx.player_all:
        if p.position in MILESTONE_POSITIONS and p.opp_franchises:
            games[(p.player_key, p.opp_franchises[0])].append(p.score)
    averages = {k: sum(v) / len(v) for k, v in games.items() if len(v) >= VERSUS_MIN_GAMES}
    population = [round(v, 1) for v in averages.values()]
    facts = []
    for p in ctx.player_current:
        if not p.opp_franchises or p.score < REVENGE_MIN_POINTS:
            continue
        key = (p.player_key, p.opp_franchises[0])
        if key not in averages:
            continue
        avg = round(averages[key], 1)
        rank, _, tied = rank_of(avg, population, True)
        if rank > 3:
            continue
        facts.append(
            Fact(
                'player_versus',
                PLAYER,
                [p.abbrev, p.opp_franchises[0]],
                f'{_player_label(p)} has averaged {number(avg)} in {len(games[key])} career '
                f'games against {team(p.opp_franchises[0])}, '
                f'{rank_phrase(rank, tied, "best")} average by any player against one '
                f'team (min. {VERSUS_MIN_GAMES} games).',
                0.6 * _rarity(rank),
                _scope_tags(p.bracket),
            )
        )
    return facts


def _revenge_facts(ctx: WeekContext) -> list[Fact]:
    """A big game against a franchise the player used to start for."""
    starts: dict[tuple[str, str], list[PlayerGame]] = defaultdict(list)
    for p in ctx.player_history:
        if p.franchises:
            starts[(p.player_key, p.franchises[0])].append(p)
    facts = []
    for p in ctx.player_current:
        if p.position not in MILESTONE_POSITIONS or p.score < REVENGE_MIN_POINTS:
            continue
        for opp in p.opp_franchises[:1]:
            if opp in p.franchises:
                continue
            old = starts.get((p.player_key, opp), [])
            if len(old) < REVENGE_MIN_STARTS:
                continue
            first, last = old[0].season, old[-1].season
            span = str(first) if first == last else f'{first}-{last}'
            facts.append(
                Fact(
                    'revenge_game',
                    PLAYER,
                    [p.abbrev, opp],
                    f'{p.name} scored {number(p.score)} for {team(p.abbrev)} against his old '
                    f'team, {team(opp)}, for whom he made {len(old)} starts ({span}).',
                    0.45 + min(p.score - REVENGE_MIN_POINTS, 20) / 100,
                    _scope_tags(p.bracket),
                )
            )
    return facts


def _position_group_facts(ctx: WeekContext) -> list[Fact]:
    """Combined points from a team's two starting RBs or WRs."""
    groups: dict[tuple[tuple[int, int], str, str], list[float]] = defaultdict(list)
    for p in ctx.player_all:
        if p.position in ('RB', 'WR'):
            groups[(p.order, p.abbrev, p.position)].append(p.score)
    franchise_of = {(g.order, g.abbrev): _primary_franchise(g) for g in ctx.team_all}
    bracket_of = {g.abbrev: g.bracket for g in ctx.current}
    facts = []
    for position in ('RB', 'WR'):
        rows = {k: sum(v) for k, v in groups.items() if k[2] == position and len(v) >= 2}
        league = list(rows.values())
        for (order, abbrev, _), total in rows.items():
            if order != ctx.target or total <= 0:
                continue
            rank, _, tied = rank_of(total, league, True)
            if rank <= 3:
                what = (
                    f"{rank_phrase(rank, tied, 'most')} by any team's {position}s in league history"
                )
                notability, category = 0.75 * _rarity(rank), LEAGUE
            else:
                franchise = franchise_of.get((order, abbrev), abbrev)
                mine = [v for (o, a, _), v in rows.items() if franchise_of.get((o, a)) == franchise]
                f_rank, _, f_tied = rank_of(total, mine, True)
                if f_rank != 1 or f_tied or len(mine) < MIN_FRANCHISE_GAMES:
                    continue
                what = f'{rank_phrase(1, f_tied, "most")} in franchise history'
                notability, category = 0.5, TEAM
            facts.append(
                Fact(
                    'position_group',
                    category,
                    [abbrev],
                    f"{team(abbrev)}'s {position}s combined for {number(total)}, {what}.",
                    notability,
                    _scope_tags(bracket_of.get(abbrev, REGULAR)),
                )
            )
    return facts


# --------------------------------------------------------------------------- #
# Drafts and trades
# --------------------------------------------------------------------------- #


def _season_points(
    games: Iterable[PlayerGame], season: int, through: tuple[int, int]
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for p in games:
        if p.season == season and p.order <= through:
            totals[p.player_key] += p.score
    return totals


def _draft_class_facts(ctx: WeekContext) -> list[Fact]:
    """A late pick taking over the lead in his draft class."""
    classes: dict[str, list[Draftee]] = defaultdict(list)
    for d in ctx.drafts:
        if (
            d.season == ctx.season
            and d.kind in ('offseason', 'midseason')
            and 'Expansion' not in d.draft
        ):
            classes[d.draft].append(d)
    if not classes:
        return []
    now = _season_points(ctx.player_all, ctx.season, ctx.target)
    before = _season_points(ctx.player_history, ctx.season, ctx.target)
    playing = {p.player_key: p for p in ctx.player_current}
    facts = []
    for draft, picks in classes.items():

        def leader(points: dict[str, float], picks: list[Draftee] = picks) -> Draftee | None:
            scored = [d for d in picks if points.get(d.player_key, 0) > 0]
            if not scored:
                return None
            best = max(points[d.player_key] for d in scored)
            top = [d for d in scored if points[d.player_key] == best]
            return top[0] if len(top) == 1 else None

        new, old = leader(now), leader(before)
        if new is None or new.round < 3 or (old and old.player_key == new.player_key):
            continue
        p = playing.get(new.player_key)
        if p is None or p.position not in MILESTONE_POSITIONS or ctx.week < 4:
            continue
        facts.append(
            Fact(
                'draft_class_leader',
                PLAYER,
                [p.abbrev],
                f'{_player_label(p)}, a {ordinal(new.round)}-round pick, now leads the {draft} '
                f'class with {number(now[new.player_key])} points.',
                0.5,
                _scope_tags(p.bracket),
            )
        )
    return facts


def _rookie_facts(ctx: WeekContext) -> list[Fact]:
    """Games and season totals in a player's NFL rookie season."""
    rookie_season = ctx.rookie_seasons
    rookie_games = [p for p in ctx.player_all if rookie_season.get(p.player_key) == p.season]
    if not rookie_games:
        return []
    facts = []
    scores = [p.score for p in rookie_games]
    # Full rookie seasons before this one, and this season so far.
    seasons: dict[tuple[str, int], float] = defaultdict(float)
    names: dict[tuple[str, int], PlayerGame] = {}
    for p in rookie_games:
        seasons[(p.player_key, p.season)] += p.score
        names[(p.player_key, p.season)] = p
    past = {k: v for k, v in seasons.items() if k[1] < ctx.season}
    record_key = max(past, key=lambda k: past[k], default=None)
    for p in ctx.player_current:
        if rookie_season.get(p.player_key) != ctx.season:
            continue
        rank, _, tied = rank_of(p.score, scores, True)
        if rank <= 3 and p.score > 0:
            facts.append(
                Fact(
                    'rookie_game',
                    PLAYER,
                    [p.abbrev],
                    f'{_player_label(p)} scored {number(p.score)}, '
                    f'{rank_phrase(rank, tied, "most")} by a rookie in league history.',
                    0.7 * _rarity(rank),
                    _scope_tags(p.bracket),
                )
            )
        total = seasons[(p.player_key, ctx.season)]
        if record_key is not None and total - p.score <= past[record_key] < total:
            holder = names[record_key]
            facts.append(
                Fact(
                    'rookie_season_record',
                    PLAYER,
                    [p.abbrev],
                    f'{_player_label(p)} has {number(total)} points this season, passing '
                    f"{holder.name}'s {number(past[record_key])} ({holder.season}) for the most "
                    'by a rookie in league history.',
                    0.75,
                    _scope_tags(p.bracket),
                )
            )
    return facts


def _trade_facts(ctx: WeekContext) -> list[Fact]:
    """A recent trade's lead changing hands: points its players have scored as
    starters for their new franchise since the deal."""
    facts = []
    for trade in ctx.trades:
        if trade.season < ctx.season - TRADE_LOOKBACK_SEASONS:
            continue

        def side_points(side: TradeSide, games: list[PlayerGame], trade: Trade = trade) -> float:
            keys = set(side.player_keys)
            return sum(
                p.score
                for p in games
                if p.player_key in keys
                and side.franchise in p.franchises
                and p.order >= trade.order
            )

        a, b = trade.sides
        before = (side_points(a, ctx.player_history), side_points(b, ctx.player_history))
        after = (side_points(a, ctx.player_all), side_points(b, ctx.player_all))
        if after[0] == after[1] or sum(after) < 40:
            continue
        lead_now = 0 if after[0] > after[1] else 1
        lead_before = None if before[0] == before[1] else 0 if before[0] > before[1] else 1
        if lead_before is None and sum(before) == 0 or lead_before == lead_now:
            continue
        win, lose = (a, b) if lead_now == 0 else (b, a)
        win_pts, lose_pts = max(after), min(after)
        # The franchises' current team codes this week.
        code = {f: g.abbrev for g in ctx.current for f in g.franchises}
        win_code, lose_code = (
            code.get(win.franchise, win.franchise),
            code.get(lose.franchise, lose.franchise),
        )

        def players(side: TradeSide) -> str:
            shown = list(side.names[:2])
            if len(side.names) > 2:
                shown.append(f'{len(side.names) - 2} more')
            return names_list(shown)

        facts.append(
            Fact(
                'trade_lead',
                TEAM,
                [win_code, lose_code],
                f"{team(win_code)}'s side of the {trade.label} trade with {team(lose_code)} "
                f'({players(win)}) took the lead this week, {number(win_pts)} to '
                f'{number(lose_pts)} in starter points since the deal ({players(lose)}).',
                0.5,
                ['regular'],
            )
        )
    return facts


# --------------------------------------------------------------------------- #
# Projections (pregame totals, 2026 on)
# --------------------------------------------------------------------------- #


def _projection_facts(ctx: WeekContext) -> list[Fact]:
    projected = [g for g in ctx.team_all if g.projected is not None and g.score > 0]
    prior_weeks = {g.order for g in projected if g.order < ctx.target}
    if len(prior_weeks) < 2 or not any(g.projected is not None for g in ctx.current):
        return []
    first = min(g.season for g in projected)
    scope = 'this season' if first == ctx.season else f'since projections began in {first}'
    facts = []

    # Upsets: the winner's projected deficit.
    upsets = [
        (g.opp_projected - (g.projected or 0), g)
        for g in projected
        if g.single_game
        and g.won
        and g.opp_projected is not None
        and g.opp_projected > (g.projected or 0)
    ]
    deficits = [d for d, _ in upsets]
    for gap, g in upsets:
        if g.order != ctx.target:
            continue
        rank, _, tied = rank_of(gap, deficits, True)
        if rank == 1:
            facts.append(
                Fact(
                    'projection_upset',
                    TEAM,
                    [g.abbrev, g.opp_abbrev],
                    f'{team(g.abbrev)} beat {team(g.opp_abbrev)} despite a projected '
                    f'{number(round(gap, 1))}-point deficit, '
                    f'{rank_phrase(1, tied, "biggest")} upset by projection {scope}.',
                    0.6,
                    _scope_tags(g.bracket),
                )
            )

    diffs = [g.score - (g.projected or 0) for g in projected]
    for g in ctx.current:
        if g.projected is None or g.score <= 0:
            continue
        diff = g.score - g.projected
        for higher in (True, False):
            if (diff <= 0) if higher else (diff >= 0):
                continue
            rank, _, tied = rank_of(diff, diffs, higher)
            if rank != 1:
                continue
            what = (
                f'beat a {number(round(g.projected, 1))}-point projection by '
                f'{number(round(diff, 1))}, {rank_phrase(1, tied, "most")} {scope}'
                if higher
                else f'fell {number(round(-diff, 1))} short of a '
                f'{number(round(g.projected, 1))}-point projection, '
                f'{rank_phrase(1, tied, "furthest")} any team has fallen short {scope}'
            )
            facts.append(
                Fact(
                    f'projection_{"beat" if higher else "miss"}',
                    TEAM,
                    [g.abbrev],
                    f'{team(g.abbrev)} {what}.',
                    0.5,
                    _scope_tags(g.bracket),
                )
            )
    return facts


DETECTORS: tuple[Callable[[WeekContext], list[Fact]], ...] = (
    _team_score_facts,
    _matchup_facts,
    _league_week_facts,
    _streak_facts,
    _season_start_facts,
    _head_to_head_facts,
    _pace_facts,
    _top_half_facts,
    _player_game_facts,
    _player_low_facts,
    _player_career_facts,
    _player_streak_facts,
    _cycle_facts,
    _lineup_facts,
    _bench_player_facts,
    _all_play_facts,
    _points_against_facts,
    _schedule_luck_facts,
    _weekly_extreme_facts,
    _playoff_odds_facts,
    _clinch_facts,
    _title_defense_facts,
    _owner_facts,
    _loyalty_facts,
    _versus_facts,
    _revenge_facts,
    _position_group_facts,
    _draft_class_facts,
    _rookie_facts,
    _trade_facts,
    _projection_facts,
)


# --------------------------------------------------------------------------- #
# Curation + entry point
# --------------------------------------------------------------------------- #


def curate(facts: list[Fact], limit: int = 10, per_team: int = 3) -> list[Fact]:
    """The most notable facts, spread across categories and teams."""
    ranked = sorted(
        facts,
        key=lambda f: (-f.notability * CATEGORY_WEIGHT.get(f.category, 1.0), f.id, f.template),
    )
    picked: list[Fact] = []
    per_subject: dict[str, int] = defaultdict(int)

    def take(fact: Fact) -> bool:
        if fact in picked or len(picked) >= limit:
            return False
        if any(per_subject[s] >= per_team for s in fact.subjects):
            return False
        picked.append(fact)
        for s in fact.subjects:
            per_subject[s] += 1
        return True

    for category in (LEAGUE, PLAYER, TEAM):
        for fact in ranked:
            if fact.category == category and take(fact):
                break
    for fact in ranked:
        take(fact)
    return sorted(picked, key=lambda f: ranked.index(f))


def generate_week_facts(
    team_games: list[TeamGame],
    player_games: list[PlayerGame],
    season: int,
    week: int,
    limit: int = 10,
    first_season: int | None = None,
    drafts: Iterable[Draftee] = (),
    trades: Iterable[Trade] = (),
    owner_names: dict[str, str] | None = None,
    rookie_seasons: dict[str, int] | None = None,
) -> dict:
    ctx = WeekContext(
        team_games,
        player_games,
        season,
        week,
        first_season,
        drafts,
        trades,
        owner_names,
        rookie_seasons,
    )
    if not ctx.current:
        return {'season': season, 'week': week, 'headline': [], 'more': [], 'all': []}
    facts: list[Fact] = []
    for detector in DETECTORS:
        facts.extend(detector(ctx))
    ranked = sorted(
        facts,
        key=lambda f: (-f.notability * CATEGORY_WEIGHT.get(f.category, 1.0), f.id, f.template),
    )
    previous = ctx.history[-1] if ctx.history else None
    headline = curate(facts, limit=limit)
    return {
        'season': season,
        'week': week,
        'week_label': ctx.current[0].week_label,
        'history_through': f'{previous.season} {previous.week_label}' if previous else None,
        'headline': [f.to_dict() for f in headline],
        'more': [f.to_dict() for f in more_notes(ranked, headline)],
        'all': [f.to_dict() for f in ranked],
    }


def more_notes(
    ranked: list[Fact], headline: list[Fact], per_team: int = MORE_PER_TEAM
) -> list[Fact]:
    """The rest of the week's notes for the site's "more notes" list, capped
    per team (headline notes included) so one team can't fill it."""
    per_subject: dict[str, int] = defaultdict(int)
    for fact in headline:
        for s in fact.subjects:
            per_subject[s] += 1
    out = []
    for fact in ranked:
        if fact in headline or any(per_subject[s] >= per_team for s in fact.subjects):
            continue
        out.append(fact)
        for s in fact.subjects:
            per_subject[s] += 1
    return out


# --------------------------------------------------------------------------- #
# Beat-everyone cycles (Hall of Fame)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cycle:
    """The shortest run of a franchise's games with a win over every rival."""

    franchise: str
    games: int
    start: TeamGame
    end: TeamGame


def all_cycles(team_games: Iterable[TeamGame], franchises: Iterable[str]) -> list[Cycle]:
    """Every beat-everyone cycle, one per game that completed one: the shortest
    stretch of a franchise's consecutive games (every decided game, playoffs
    included) ending with the win that crossed off its last unbeaten rival
    among `franchises`.

    A co-owned team (2021's CGK/SRY, CWR/SLS) counts only as its primary
    franchise here, so one win can't cross off two rivals, and a franchise
    can't be beaten before it had a team of its own."""
    franchise_set = set(franchises)
    by_franchise: dict[str, list[TeamGame]] = defaultdict(list)
    for g in sorted(team_games, key=lambda g: g.order):
        if not g.decided or g.score <= 0:
            continue
        if g.franchises and g.franchises[0] in franchise_set:
            by_franchise[g.franchises[0]].append(g)

    cycles = []
    for franchise, games in by_franchise.items():
        rivals = franchise_set - {franchise}
        if not rivals:
            continue
        beaten = [
            {g.opp_franchises[0]} & rivals if g.won and g.opp_franchises else set() for g in games
        ]
        counts: dict[str, int] = defaultdict(int)
        start = 0
        for end, opponents in enumerate(beaten):
            for rival in opponents:
                counts[rival] += 1
            # Drop games off the front that the window doesn't need.
            while start < end and all(counts[rival] > 1 for rival in beaten[start]):
                for rival in beaten[start]:
                    counts[rival] -= 1
                start += 1
            complete = all(counts[rival] for rival in rivals)
            if complete and any(counts[rival] == 1 for rival in opponents):
                cycles.append(Cycle(franchise, end - start + 1, games[start], games[end]))
    return cycles


def fastest_cycles(team_games: Iterable[TeamGame], franchises: Iterable[str]) -> list[Cycle]:
    """Each franchise's fastest cycle (see all_cycles), fewest games first.
    Franchises that never managed one are left out; ties go to whoever
    finished first."""
    best: dict[str, Cycle] = {}
    for cycle in all_cycles(team_games, franchises):
        current = best.get(cycle.franchise)
        if current is None or (cycle.games, cycle.end.order) < (current.games, current.end.order):
            best[cycle.franchise] = cycle
    return sorted(best.values(), key=lambda c: (c.games, c.end.order, c.franchise))
