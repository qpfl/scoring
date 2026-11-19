"""Cross-season chart data for the site's charts and QPFLTok.

Pure functions over the flattened history rows that `scripts/export_weekly_facts.py`
already builds (`TeamGame` / `PlayerGame`). `scripts/export_charts.py` writes the
result to web/data/shared/charts.json; web/charts-managers.js draws it.

Each history row is one side of one game, so every game appears twice. Charts
key on franchises (the ten current seats, with earlier owners' eras folded in)
except the manager fingerprints, which key on owner codes. See
docs/PLAN_qpfltok_and_charts.md.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from qpfl.weekly_facts import PLAYOFFS, REGULAR, PlayerGame, TeamGame, regular_season_weeks

# Bump when the file's shape changes in a way old clients can't read.
CHARTS_VERSION = 3

ELO_START = 1500.0
ELO_K = 24.0
ELO_REGRESSION = 1 / 3
ELO_PLAYOFF_WEIGHT = 1.25

# Fingerprints rank owners with at least this many regular-season games.
FINGERPRINT_MIN_GAMES = 14
CLUTCH_MARGIN = 10.0
CLUTCH_MIN_GAMES = 3

PLAYER_NEMESES_SHOWN = 5
STREAKS_SHOWN = 8

FINGERPRINT_TRAITS = (
    ('scoring', 'Scoring', 'Points per game'),
    ('consistency', 'Consistency', 'Steadiest week to week (lowest spread)'),
    ('lineup_iq', 'Lineup IQ', 'Share of the best possible lineup started'),
    ('luck', 'Luck', 'Wins above all-play pace, per game'),
    ('clutch', 'Clutch', f'Win % in games decided by under {CLUTCH_MARGIN:g}'),
    ('playoffs', 'Playoffs', 'Playoff win %'),
)


def _result(game: TeamGame) -> float | None:
    """1, 0 or 0.5 for the row's side, or None for an undecided first leg."""
    if not game.decided:
        return None
    if game.won:
        return 1.0
    if game.lost:
        return 0.0
    return 0.5


def _result_margin(game: TeamGame) -> float:
    mine = game.result_score if game.result_score is not None else game.score
    theirs = game.result_opp_score if game.result_opp_score is not None else game.opp_score
    return abs(mine - theirs)


def _counted(games: Iterable[TeamGame], brackets=(REGULAR, PLAYOFFS)) -> list[TeamGame]:
    return sorted((g for g in games if g.bracket in brackets), key=lambda g: (g.order, g.abbrev))


def _unique_games(games: Iterable[TeamGame]) -> list[TeamGame]:
    """One row per game (the first side seen), in order."""
    seen: set[tuple] = set()
    out = []
    for g in sorted(games, key=lambda g: (g.order, g.abbrev)):
        key = (g.season, g.week, *sorted((g.abbrev, g.opp_abbrev)))
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


def _week_label(season: int, week: int) -> str:
    return f'{season} W{week}'


# ---- Elo ----


def elo_history(team_games: Sequence[TeamGame]) -> dict[str, Any]:
    """Franchise Elo after every week of regular season and playoffs.

    Start at 1500 with K=24; a game's change is scaled by the margin
    (ln(|margin| + 1) × 2.2 / (winner's edge × 0.001 + 2.2), so blowouts count
    more and favorites gain less); playoff games weigh 1.25×; between seasons
    every rating moves a third of the way back to 1500. A two-week playoff
    game counts once, on its deciding leg, by the two-week totals.
    """
    games = [g for g in _unique_games(_counted(team_games)) if _result(g) is not None]
    rating: dict[str, float] = {}
    labels: list[str] = []
    series: dict[str, list[float | None]] = defaultdict(list)
    season = None
    by_week: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    for g in games:
        by_week[g.order].append(g)

    for (game_season, week), week_games in sorted(by_week.items()):
        if season is not None and game_season != season:
            for f in rating:
                rating[f] -= (rating[f] - ELO_START) * ELO_REGRESSION
        season = game_season
        for g in week_games:
            ra = statistics.fmean(rating.get(f, ELO_START) for f in g.franchises)
            rb = statistics.fmean(rating.get(f, ELO_START) for f in g.opp_franchises)
            result = _result(g)
            expected = 1 / (1 + 10 ** ((rb - ra) / 400))
            if result == 0.5:
                multiplier = 1.0
            else:
                edge = (ra - rb) if result == 1 else (rb - ra)
                multiplier = math.log(_result_margin(g) + 1) * 2.2 / (edge * 0.001 + 2.2)
            weight = ELO_PLAYOFF_WEIGHT if g.bracket == PLAYOFFS else 1.0
            delta = ELO_K * weight * multiplier * (result - expected)
            for f in g.franchises:
                rating[f] = rating.get(f, ELO_START) + delta
            for f in g.opp_franchises:
                rating[f] = rating.get(f, ELO_START) - delta
        labels.append(_week_label(game_season, week))
        for f in set(series) | set(rating):
            values = series[f]
            values.extend([None] * (len(labels) - 1 - len(values)))
            values.append(round(rating[f], 1) if f in rating else None)

    return {
        'labels': labels,
        'series': dict(sorted(series.items())),
        'current': {f: round(r, 1) for f, r in sorted(rating.items())},
    }


# ---- Manager fingerprints ----


def _percentiles(values: dict[str, float | None]) -> dict[str, float | None]:
    """Each value's place among the others, 0 (lowest) to 1 (highest)."""
    known = {k: v for k, v in values.items() if v is not None}
    out: dict[str, float | None] = dict.fromkeys(values)
    if len(known) < 2:
        return {k: (0.5 if k in known else None) for k in values}
    ordered = sorted(known.values())
    for key, value in known.items():
        below = sum(1 for v in ordered if v < value)
        equal = sum(1 for v in ordered if v == value) - 1
        out[key] = round((below + equal / 2) / (len(ordered) - 1), 3)
    return out


def manager_fingerprints(team_games: Sequence[TeamGame], names: dict[str, str]) -> dict[str, Any]:
    """Six traits per owner, each with its value and its percentile among owners."""
    regular = [g for g in team_games if g.bracket == REGULAR]
    week_scores: dict[tuple[int, int], list[tuple[str, float]]] = defaultdict(list)
    for g in regular:
        week_scores[g.order].append((g.abbrev, g.score))

    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            'scores': [],
            'optimal': 0.0,
            'started': 0.0,
            'wins': 0.0,
            'expected': 0.0,
            'close': [],
            'playoff': [],
            'seasons': set(),
        }
    )
    for g in regular:
        result = _result(g)
        field = week_scores[g.order]
        beaten = sum(
            1 if g.score > s else 0.5 if g.score == s else 0 for a, s in field if a != g.abbrev
        )
        expected = beaten / max(1, len(field) - 1)
        for owner in g.owners:
            s = stats[owner]
            s['scores'].append(g.score)
            s['seasons'].add(g.season)
            if g.optimal:
                s['optimal'] += g.optimal
                s['started'] += g.score
            if result is not None:
                s['wins'] += result
                s['expected'] += expected
                if _result_margin(g) < CLUTCH_MARGIN:
                    s['close'].append(result)
    for g in team_games:
        result = _result(g)
        if g.bracket == PLAYOFFS and result is not None:
            for owner in g.owners:
                stats[owner]['playoff'].append(result)

    eligible = {o: s for o, s in stats.items() if len(s['scores']) >= FINGERPRINT_MIN_GAMES}
    values: dict[str, dict[str, float | None]] = {trait: {} for trait, _, _ in FINGERPRINT_TRAITS}
    for owner, s in eligible.items():
        games = len(s['scores'])
        values['scoring'][owner] = round(statistics.fmean(s['scores']), 1)
        values['consistency'][owner] = -round(statistics.pstdev(s['scores']), 1)
        values['lineup_iq'][owner] = round(s['started'] / s['optimal'], 3) if s['optimal'] else None
        values['luck'][owner] = round((s['wins'] - s['expected']) / games, 3)
        values['clutch'][owner] = (
            round(statistics.fmean(s['close']), 3) if len(s['close']) >= CLUTCH_MIN_GAMES else None
        )
        values['playoffs'][owner] = (
            round(statistics.fmean(s['playoff']), 3) if s['playoff'] else None
        )
    pct = {trait: _percentiles(v) for trait, v in values.items()}

    owners = []
    for owner, s in sorted(eligible.items()):
        owners.append(
            {
                'code': owner,
                'name': names.get(owner, owner),
                'games': len(s['scores']),
                'seasons': sorted(s['seasons']),
                'values': {
                    trait: (abs(v) if trait == 'consistency' and v is not None else v)
                    for trait, v in ((t, values[t][owner]) for t, _, _ in FINGERPRINT_TRAITS)
                },
                'pct': {trait: pct[trait][owner] for trait, _, _ in FINGERPRINT_TRAITS},
            }
        )
    return {
        'traits': [
            {'id': t, 'label': label, 'about': about} for t, label, about in FINGERPRINT_TRAITS
        ],
        'owners': owners,
    }


# ---- Head-to-head and nemeses ----


def head_to_head(team_games: Sequence[TeamGame]) -> dict[str, dict[str, list[float]]]:
    """{franchise: {opponent: [wins, losses, ties, points for, points against]}}."""
    out: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0, 0, 0.0, 0.0])
    )
    for g in _counted(team_games):
        result = _result(g)
        if result is None:
            continue
        for f in g.franchises:
            for opp in g.opp_franchises:
                if f == opp:
                    continue
                row = out[f][opp]
                row[0 if result == 1 else 1 if result == 0 else 2] += 1
                row[3] = round(row[3] + g.score, 1)
                row[4] = round(row[4] + g.opp_score, 1)
    return {f: dict(sorted(opps.items())) for f, opps in sorted(out.items())}


def player_nemeses(player_games: Sequence[PlayerGame]) -> dict[str, list[list[Any]]]:
    """The opposing starters who have scored the most against each franchise:
    {franchise: [[name, position, points, starts]]}."""
    totals: dict[str, dict[str, list[Any]]] = defaultdict(dict)
    for p in player_games:
        if not p.starter or p.bracket not in (REGULAR, PLAYOFFS):
            continue
        for opp in p.opp_franchises:
            if opp in p.franchises:
                continue
            row = totals[opp].setdefault(p.player_key, [p.name, p.position, 0.0, 0])
            row[2] = round(row[2] + p.score, 1)
            row[3] += 1
    return {
        f: sorted(rows.values(), key=lambda r: (-r[2], r[0]))[:PLAYER_NEMESES_SHOWN]
        for f, rows in sorted(totals.items())
    }


# ---- Streaks ----


def streaks(team_games: Sequence[TeamGame]) -> dict[str, Any]:
    """Longest regular-season win and losing streaks (carrying across seasons)
    and each franchise's current streak. Ties end a streak."""
    by_franchise: dict[str, list[tuple[tuple[int, int], float]]] = defaultdict(list)
    for g in _counted(team_games, brackets=(REGULAR,)):
        result = _result(g)
        if result is None:
            continue
        for f in g.franchises:
            by_franchise[f].append((g.order, result))

    runs: list[dict[str, Any]] = []
    current: dict[str, list[Any]] = {}
    for f, results in sorted(by_franchise.items()):
        results.sort()
        start = 0
        for i in range(1, len(results) + 1):
            if i < len(results) and results[i][1] == results[start][1]:
                continue
            kind = {1.0: 'W', 0.0: 'L'}.get(results[start][1])
            length = i - start
            if kind:
                runs.append(
                    {
                        'franchise': f,
                        'kind': kind,
                        'length': length,
                        'start': list(results[start][0]),
                        'end': list(results[i - 1][0]),
                        'active': i == len(results),
                    }
                )
                if i == len(results):
                    current[f] = [kind, length]
            start = i

    def top(kind: str) -> list[dict[str, Any]]:
        chosen = [r for r in runs if r['kind'] == kind]
        chosen.sort(key=lambda r: (-r['length'], r['end'], r['franchise']))
        return chosen[:STREAKS_SHOWN]

    return {'wins': top('W'), 'losses': top('L'), 'current': current}


# ---- Scores and season arcs ----


def score_distributions(team_games: Sequence[TeamGame]) -> dict[str, list[float]]:
    """Every regular-season score by franchise."""
    out: dict[str, list[float]] = defaultdict(list)
    for g in _counted(team_games, brackets=(REGULAR,)):
        for f in g.franchises:
            out[f].append(round(g.score, 1))
    return dict(sorted(out.items()))


def season_arcs(team_games: Sequence[TeamGame]) -> dict[str, dict[str, list[float]]]:
    """Cumulative regular-season wins after each week: {franchise: {season: [...]}}."""
    out: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for g in _counted(team_games, brackets=(REGULAR,)):
        result = _result(g)
        if result is None:
            continue
        for f in g.franchises:
            arc = out[f].setdefault(str(g.season), [])
            arc.append((arc[-1] if arc else 0) + result)
    return {f: dict(sorted(seasons.items())) for f, seasons in sorted(out.items())}


# ---- Weekly awards ----


def weekly_awards(
    team_games: Sequence[TeamGame], player_games: Sequence[PlayerGame], season: int, week: int
) -> list[dict[str, Any]]:
    """The week's fixed awards, for the facts file, the Matchups page and QPFLTok.

    Each award names the team (that week's code) and, for player awards, the
    player. An award with no candidate (no projections, no bench) is left out.
    """
    sides = [g for g in team_games if g.season == season and g.week == week]
    if not sides:
        return []
    players = [p for p in player_games if p.season == season and p.week == week]
    starters = [p for p in players if p.starter]
    bench = [p for p in players if not p.starter]
    decided = [g for g in sides if g.decided and g.single_game]
    awards: list[dict[str, Any]] = []

    def add(award_id, label, emoji, team, value, **extra):
        awards.append(
            {'id': award_id, 'label': label, 'emoji': emoji, 'team': team, 'value': value, **extra}
        )

    if starters:
        mvp = max(starters, key=lambda p: (p.score, p.name))
        add('mvp', 'MVP', '⭐', mvp.abbrev, mvp.score, player=mvp.name, position=mvp.position)
    high = max(sides, key=lambda g: (g.score, g.abbrev))
    add('high_score', 'High score', '🔥', high.abbrev, high.score, opp=high.opp_abbrev)
    low = min(sides, key=lambda g: (g.score, g.abbrev))
    add('low_score', 'Low score', '🧊', low.abbrev, low.score, opp=low.opp_abbrev)
    winners = [g for g in decided if g.won]
    if winners:
        blowout = max(winners, key=lambda g: (g.margin, g.abbrev))
        add(
            'blowout',
            'Biggest blowout',
            '⚔️',
            blowout.abbrev,
            round(blowout.margin, 1),
            opp=blowout.opp_abbrev,
            score=[blowout.score, blowout.opp_score],
        )
        close = min(winners, key=lambda g: (g.margin, g.abbrev))
        add(
            'nail_biter',
            'Nail-biter',
            '😬',
            close.abbrev,
            round(close.margin, 1),
            opp=close.opp_abbrev,
            score=[close.score, close.opp_score],
        )
        upsets = [
            g
            for g in winners
            if g.projected is not None
            and g.opp_projected is not None
            and g.projected < g.opp_projected
        ]
        if upsets:
            upset = min(upsets, key=lambda g: (g.projected - g.opp_projected, g.abbrev))
            add(
                'upset',
                'Upset of the week',
                '⚡',
                upset.abbrev,
                round(upset.projected - upset.opp_projected, 1),
                opp=upset.opp_abbrev,
                score=[upset.score, upset.opp_score],
                projected=[upset.projected, upset.opp_projected],
            )
    if bench:
        sat = max(bench, key=lambda p: (p.score, p.name))
        if sat.score > 0:
            add(
                'bench_mvp',
                'Bench MVP',
                '🪑',
                sat.abbrev,
                sat.score,
                player=sat.name,
                position=sat.position,
            )
    left = [g for g in sides if g.optimal is not None and g.optimal > g.score]
    if left:
        worst = max(left, key=lambda g: (g.optimal - g.score, g.abbrev))
        add(
            'left_on_bench',
            'Most left on the bench',
            '🤦',
            worst.abbrev,
            round(worst.optimal - worst.score, 1),
            score=worst.score,
            optimal=worst.optimal,
        )
    return awards


# ---- Costliest drops ----

DROP_WINDOW_WEEKS = 17
DROPS_SHOWN = 10


def costliest_drops(
    timeline: dict[tuple[int, int], dict[str, str]],
    player_games: Sequence[PlayerGame],
    franchise_of,
    names: dict[str, str],
) -> list[dict[str, Any]]:
    """Players a team let go during the regular season (off every roster the
    next week, so not traded) and the points they then scored starting for
    other teams over the next 17 weeks. `franchise_of(code)` maps a season's
    team code to franchises."""
    weeks = sorted(timeline)
    index = {w: i for i, w in enumerate(weeks)}

    def comparable(i: int) -> bool:
        # Every team plays every regular-season week, so a player missing
        # from all rosters the next week was let go. Playoff weeks leave out
        # eliminated teams, and the offseason reshuffles rosters, so those
        # transitions say nothing.
        (season, _), (next_season, next_week) = weeks[i], weeks[i + 1]
        return season == next_season and next_week <= regular_season_weeks(season)

    starts: dict[str, list[PlayerGame]] = defaultdict(list)
    for p in player_games:
        if p.starter:
            starts[p.player_key].append(p)

    drops = []
    for i in range(len(weeks) - 1):
        if not comparable(i):
            continue
        now, nxt = timeline[weeks[i]], timeline[weeks[i + 1]]
        for key, code in now.items():
            if key in nxt:
                continue
            dropped_by = set(franchise_of(code))
            later = [
                p
                for p in starts.get(key, [])
                if (p.season, p.week) in index
                and i < index[(p.season, p.week)] <= i + DROP_WINDOW_WEEKS
                and not (set(p.franchises) & dropped_by)
            ]
            points = sum(p.score for p in later)
            if points <= 0:
                continue
            drops.append(
                {
                    'player': names.get(key, later[0].name),
                    'team': sorted(dropped_by)[0],
                    'season': weeks[i][0],
                    'week': weeks[i][1],
                    'points': round(points, 1),
                    'starts': len(later),
                    'to': sorted({f for p in later for f in p.franchises}),
                }
            )
    drops.sort(key=lambda d: (-d['points'], d['season'], d['week']))
    return drops[:DROPS_SHOWN]


def build_charts(
    team_games: Sequence[TeamGame],
    player_games: Sequence[PlayerGame],
    *,
    current_season: int,
    completed_through: int,
    names: dict[str, str] | None = None,
    timeline: dict[tuple[int, int], dict[str, str]] | None = None,
    franchise_of=None,
    player_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Every precomputed chart block, keyed by chart id.

    `completed_through` is the last completed week of `current_season`; the
    history rows passed in must already stop there. `names` maps owner and
    franchise codes to the names the charts show.
    """
    names = names or {}
    return {
        'version': CHARTS_VERSION,
        'season': current_season,
        'completed_through': completed_through,
        'names': dict(sorted(names.items())),
        'elo': elo_history(team_games),
        'fingerprints': manager_fingerprints(team_games, names),
        'head_to_head': head_to_head(team_games),
        'player_nemeses': player_nemeses(player_games),
        'streaks': streaks(team_games),
        'scores': score_distributions(team_games),
        'season_arcs': season_arcs(team_games),
        'costliest_drops': costliest_drops(
            timeline or {}, player_games, franchise_of or (lambda code: (code,)), player_names or {}
        ),
    }
