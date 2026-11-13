"""Scorigami: which final scores have happened in QPFL history, and how often.

A final is one decided matchup, named by the winning and losing score. A
two-week playoff matchup counts once, with its combined two-week totals, on
its final leg. Unscored and forfeited games (a zero on either side) are not
finals. Ties are finals like any other and sit on the grid's diagonal.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # weekly_facts imports this module for its scorigami note.
    from qpfl.weekly_facts import TeamGame

# Newest first, how many first-time finals the Hall of Fame lists.
RECENT = 10


@dataclass(frozen=True)
class Final:
    season: int
    week: int
    week_label: str
    bracket: str
    winner: str
    loser: str
    high: int
    low: int

    @property
    def order(self) -> tuple[int, int]:
        return (self.season, self.week)

    @property
    def score(self) -> tuple[int, int]:
        return (self.high, self.low)

    @property
    def tie(self) -> bool:
        return self.high == self.low


def finals(team_games: Iterable[TeamGame]) -> list[Final]:
    """Every decided matchup once, oldest first."""
    seen = set()
    out = []
    for game in sorted(team_games, key=lambda g: (g.order, g.abbrev)):
        if not game.decided:
            continue
        key = (game.season, game.week, *sorted((game.abbrev, game.opp_abbrev)))
        if key in seen:
            continue
        seen.add(key)
        mine, theirs = game._result_scores()
        if mine <= 0 or theirs <= 0:
            continue
        first = mine > theirs or (mine == theirs and game.abbrev <= game.opp_abbrev)
        winner, loser = (game.abbrev, game.opp_abbrev) if first else (game.opp_abbrev, game.abbrev)
        out.append(
            Final(
                season=game.season,
                week=game.week,
                week_label=game.week_label,
                bracket=game.bracket,
                winner=winner,
                loser=loser,
                high=round(max(mine, theirs)),
                low=round(min(mine, theirs)),
            )
        )
    return out


def _game(final: Final, names: dict) -> dict:
    entry = {
        'season': final.season,
        'week': final.week,
        'week_label': final.week_label,
        'winner': final.winner,
        'loser': final.loser,
    }
    for side in ('winner', 'loser'):
        name = names.get((final.season, final.week, getattr(final, side)))
        if name:
            entry[f'{side}_name'] = name
    return entry


def build_scorigami(team_games: Iterable[TeamGame], team_names: dict | None = None) -> dict:
    """The Hall of Fame's scorigami block.

    `team_names` maps (season, week, abbrev) to that week's team name.
    """
    names = team_names or {}
    history = finals(team_games)
    cells: dict[tuple[int, int], dict] = {}
    firsts: list[tuple[int, Final]] = []
    for final in history:
        cell = cells.get(final.score)
        if cell is None:
            cell = {'w': final.high, 'l': final.low, 'count': 0, 'first': _game(final, names)}
            cells[final.score] = cell
            firsts.append((len(cells), final))
        cell['count'] += 1
        cell['latest'] = _game(final, names)
        cell.setdefault('games', []).append(cell['latest'])
    for cell in cells.values():
        # First and latest already name every game of a final seen once or
        # twice; only a third time needs the whole list.
        if cell['count'] < 3:
            del cell['games']
        if cell['count'] == 1:
            del cell['latest']
    games = len(history)
    return {
        'games': games,
        'unique': len(cells),
        'max_score': max((f.high for f in history), default=0),
        'cells': sorted(cells.values(), key=lambda c: (-c['w'], -c['l'])),
        'recent': [
            {'w': f.high, 'l': f.low, 'nth': nth, **_game(f, names)}
            for nth, f in reversed(firsts[-RECENT:])
        ],
        'ties': [{'score': f.high, **_game(f, names)} for f in history if f.tie],
    }
