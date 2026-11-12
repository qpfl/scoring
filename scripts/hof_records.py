"""The Hall of Fame record book: every all-time record as structured entries.

Built on the flattened team and player games that the weekly facts use
(`scripts/export_weekly_facts.flatten_season`), so a record and a weekly note
about it always agree. Each record group is

    {id, title, category, unit, entries: [{rank, value, season, week, ...}]}

Entries name teams by their code that week (`team`), the owner identity
credited with it (`owner_code`), and players by career profile key
(`profile_key`), so the site can link each one without parsing text.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable

from qpfl.weekly_facts import CONSOLATION, PLAYOFFS, REGULAR, PlayerGame, TeamGame
from scripts import export_hall_of_fame as hof

TOP = 5
# Season and career leaderboards for players are worth a longer list.
POSITIONS = ('QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL')

# Records nobody wants to hold. Owner pages list these apart from the rest.
SHAME = {
    'team-game-fewest-points',
    'team-game-bench-points',
    'team-season-worst-ppg',
    'team-season-worst-record',
    'team-longest-losing-streak',
    'player-game-bench-points',
    'player-game-fewest-points',
    'player-game-fewest-points-k',
    'player-game-defense-shame',
}

CATEGORIES = (
    ('team-game', 'Team · Game'),
    ('team-season', 'Team · Season'),
    ('playoffs', 'Playoffs'),
    ('player-game', 'Player · Game'),
    ('player-season', 'Player · Season'),
    ('player-career', 'Player · Career'),
    ('league', 'League'),
)


def _ranked(rows: list[dict], *, lowest: bool = False, limit: int = TOP) -> tuple[list[dict], int]:
    """Best `limit` rows by value, ranked with ties sharing a rank, and how many
    more rows tie the last one shown. Among equal values, whoever got there
    first is listed first."""
    rows = sorted(rows, key=lambda r: (r.get('season', 0), r.get('week', 0)))
    rows.sort(key=lambda r: r['value'], reverse=not lowest)
    ranked = []
    for i, row in enumerate(rows[:limit]):
        rank = ranked[-1]['rank'] if ranked and ranked[-1]['value'] == row['value'] else i + 1
        ranked.append({'rank': rank, **row})
    tied = sum(1 for row in rows[limit:] if ranked and row['value'] == ranked[-1]['value'])
    return ranked, tied


def _clean(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if value not in (None, '', [])}


class RecordBook:
    """Collects record groups from every team and player game."""

    def __init__(
        self,
        all_seasons: list[dict],
        owner_label: Callable[[str, int], str],
        profile_key_for: Callable[[str], str] | None = None,
        franchises: Iterable[str] = (),
    ):
        self.franchises = list(franchises)
        # Imported here: export_weekly_facts imports export_hall_of_fame at load.
        from scripts.export_weekly_facts import flatten_season

        self.owner_label = owner_label
        self.profile_key_for = profile_key_for or (lambda key: key)
        self.complete_seasons = {
            s['season'] for s in all_seasons if s.get('regular_season_complete', True)
        }
        self.team_games: list[TeamGame] = []
        self.player_games: list[PlayerGame] = []
        self.team_names: dict[tuple[int, int, str], str] = {}
        # A team's name as of its last game of the season.
        self.season_names: dict[tuple[int, str], str] = {}
        for season_data in all_seasons:
            team_games, player_games = flatten_season(season_data)
            self.team_games.extend(team_games)
            self.player_games.extend(player_games)
            for week in season_data['weeks']:
                for matchup in week.get('matchups', []):
                    for side in ('team1', 'team2'):
                        team = matchup.get(side)
                        if isinstance(team, dict) and team.get('abbrev'):
                            name = hof.clean_team_name(team.get('name', ''))
                            season = season_data['season']
                            self.team_names[(season, week.get('week'), team['abbrev'])] = name
                            self.season_names[(season, team['abbrev'])] = name
        # Unscored and forfeited games (a zero) aren't performances.
        self.scored = [g for g in self.team_games if g.score > 0 and g.opp_score > 0]
        self.groups: list[dict] = []

    # ------------------------------------------------------------------ #
    # Entry builders
    # ------------------------------------------------------------------ #

    def _team_fields(self, abbrev: str, season: int, week: int | None = None) -> dict:
        name = self.team_names.get((season, week, abbrev)) or self.season_names.get(
            (season, abbrev), ''
        )
        return {
            'team': abbrev,
            'team_name': name,
            'owner_code': hof._owner_identity_code(abbrev),
            'owner': self.owner_label(abbrev, season),
        }

    def _game_entry(self, game: TeamGame, value: float, **extra) -> dict:
        return {
            'value': value,
            'season': game.season,
            'week': game.week,
            'week_label': game.week_label,
            **self._team_fields(game.abbrev, game.season, game.week),
            'opponent': game.opp_abbrev,
            'opponent_name': self.team_names.get((game.season, game.week, game.opp_abbrev), ''),
            'score': game.score,
            'opponent_score': game.opp_score,
            **extra,
        }

    def _player_entry(self, game: PlayerGame, value: float) -> dict:
        return {
            'value': value,
            'player': game.name,
            'profile_key': self.profile_key_for(game.player_key),
            'position': game.position,
            'season': game.season,
            'week': game.week,
            'week_label': game.week_label,
            **self._team_fields(game.abbrev, game.season, game.week),
        }

    def add(
        self,
        group_id: str,
        title: str,
        category: str,
        rows: Iterable[dict],
        *,
        unit: str = 'pts',
        lowest: bool = False,
        limit: int = TOP,
        position: str | None = None,
        note: str | None = None,
    ) -> None:
        ranked, tied = _ranked(list(rows), lowest=lowest, limit=limit)
        entries = [_clean(e) for e in ranked]
        if not entries:
            return
        self.groups.append(
            _clean(
                {
                    'id': group_id,
                    'title': title,
                    'category': category,
                    'unit': unit,
                    'position': position,
                    'note': note,
                    'shame': group_id in SHAME or None,
                    'entries': entries,
                    'more_tied': tied or None,
                }
            )
        )

    # ------------------------------------------------------------------ #
    # Team records
    # ------------------------------------------------------------------ #

    def team_game_records(self) -> None:
        games = self.scored
        decided = [g for g in games if g.decided and g.single_game]
        self.add(
            'team-game-most-points',
            'Most Points in a Game',
            'team-game',
            (self._game_entry(g, g.score) for g in games),
        )
        self.add(
            'team-game-fewest-points',
            'Fewest Points in a Game',
            'team-game',
            (self._game_entry(g, g.score) for g in games),
            lowest=True,
        )
        self.add(
            'team-game-biggest-win',
            'Largest Margin of Victory',
            'team-game',
            (self._game_entry(g, g.margin) for g in decided if g.won),
        )
        self.add(
            'team-game-most-points-loss',
            'Most Points in a Loss',
            'team-game',
            (self._game_entry(g, g.score) for g in decided if g.lost),
        )
        self.add(
            'team-game-fewest-points-win',
            'Fewest Points in a Win',
            'team-game',
            (self._game_entry(g, g.score) for g in decided if g.won),
            lowest=True,
        )
        self.add(
            'team-game-bench-points',
            'Most Points Left on the Bench',
            'team-game',
            (
                self._game_entry(g, g.optimal - g.score, optimal=g.optimal)
                for g in games
                if g.optimal is not None
            ),
            note='Best possible lineup from the roster minus the starters. '
            'Only games with every bench player scored.',
        )

    def _season_rows(self) -> dict[tuple[int, str], dict]:
        """Regular-season totals per team, for completed regular seasons."""
        seasons: dict[tuple[int, str], dict] = {}
        for g in self.team_games:
            if g.bracket != REGULAR or g.season not in self.complete_seasons:
                continue
            if g.score <= 0 and g.opp_score <= 0:
                continue
            row = seasons.setdefault(
                (g.season, g.abbrev),
                {'wins': 0, 'losses': 0, 'ties': 0, 'points': 0.0, 'games': 0, 'hundreds': 0},
            )
            row['points'] += g.score
            row['games'] += 1
            row['hundreds'] += g.score >= 100
            if g.won:
                row['wins'] += 1
            elif g.lost:
                row['losses'] += 1
            elif g.decided:
                row['ties'] += 1
        return seasons

    def team_season_records(self) -> None:
        rows = []
        for (season, abbrev), row in self._season_rows().items():
            games = row['wins'] + row['losses'] + row['ties']
            if not games:
                continue
            record = f'{row["wins"]}-{row["losses"]}' + (f'-{row["ties"]}' if row['ties'] else '')
            rows.append(
                {
                    'season': season,
                    **self._team_fields(abbrev, season),
                    'record': record,
                    'points': row['points'],
                    'ppg': row['points'] / row['games'],
                    'win_pct': (row['wins'] + row['ties'] / 2) / games,
                    'hundreds': row['hundreds'],
                }
            )

        def with_value(key: str, digits: int | None = None):
            for row in rows:
                value = row[key] if digits is None else round(row[key], digits)
                yield {**row, 'value': value}

        self.add(
            'team-season-most-points',
            'Most Points in a Season',
            'team-season',
            with_value('points'),
        )
        self.add(
            'team-season-best-ppg',
            'Best Points per Game (Season)',
            'team-season',
            with_value('ppg', 1),
            unit='ppg',
        )
        self.add(
            'team-season-worst-ppg',
            'Worst Points per Game (Season)',
            'team-season',
            with_value('ppg', 1),
            unit='ppg',
            lowest=True,
        )
        self.add(
            'team-season-best-record',
            'Best Regular-Season Record',
            'team-season',
            with_value('win_pct', 3),
            unit='win_pct',
        )
        self.add(
            'team-season-worst-record',
            'Worst Regular-Season Record',
            'team-season',
            with_value('win_pct', 3),
            unit='win_pct',
            lowest=True,
        )
        self.add(
            'team-season-most-hundreds',
            'Most 100-Point Games in a Season',
            'team-season',
            with_value('hundreds'),
            unit='games',
        )
        self.streak_records()

    def streak_records(self) -> None:
        """Longest win and losing streaks by owner, carrying across seasons."""
        by_owner: dict[str, list[TeamGame]] = defaultdict(list)
        for g in self.team_games:
            if g.decided and g.bracket != CONSOLATION and (g.score > 0 or g.opp_score > 0):
                by_owner[hof._owner_identity_code(g.abbrev)].append(g)

        streaks = {'won': [], 'lost': []}
        for games in by_owner.values():
            games.sort(key=lambda g: g.order)
            for outcome in streaks:
                run: list[TeamGame] = []
                for g in [*games, None]:
                    if g is not None and getattr(g, outcome):
                        run.append(g)
                        continue
                    if len(run) >= 2:
                        first, last = run[0], run[-1]
                        streaks[outcome].append(
                            {
                                'value': len(run),
                                'season': last.season,
                                'week': last.week,
                                'week_label': last.week_label,
                                **self._team_fields(last.abbrev, last.season, last.week),
                                'start': {
                                    'season': first.season,
                                    'week': first.week,
                                    'week_label': first.week_label,
                                    'team': first.abbrev,
                                },
                            }
                        )
                    run = []
        self.add(
            'team-longest-win-streak',
            'Longest Winning Streak',
            'team-season',
            streaks['won'],
            unit='games',
            note='Regular season and playoffs, carrying across seasons.',
        )
        self.add(
            'team-longest-losing-streak',
            'Longest Losing Streak',
            'team-season',
            streaks['lost'],
            unit='games',
            note='Regular season and playoffs, carrying across seasons.',
        )

    def playoff_records(self) -> None:
        games = [g for g in self.scored if g.bracket == PLAYOFFS]
        self.add(
            'playoffs-most-points',
            'Highest Playoff Score',
            'playoffs',
            (self._game_entry(g, g.score) for g in games),
        )
        self.add(
            'playoffs-biggest-win',
            'Biggest Playoff Win',
            'playoffs',
            (self._game_entry(g, g.margin) for g in games if g.single_game and g.won),
        )
        self.add(
            'playoffs-closest-game',
            'Closest Playoff Game',
            'playoffs',
            (self._game_entry(g, g.margin) for g in games if g.single_game and g.won),
            lowest=True,
        )
        self.add(
            'playoffs-title-game-points',
            'Highest Championship Game Score',
            'playoffs',
            (self._game_entry(g, g.score) for g in games if g.title_game),
        )

    # ------------------------------------------------------------------ #
    # Player records
    # ------------------------------------------------------------------ #

    def player_game_records(self) -> None:
        started = [p for p in self.player_games if p.starter]
        offense = {'QB', 'RB', 'WR', 'TE'}
        self.add(
            'player-game-most-points',
            'Most Points in a Game',
            'player-game',
            (self._player_entry(p, p.score) for p in started),
        )
        self.add(
            'player-game-most-points-non-qb',
            'Most Points in a Game (Non-QB)',
            'player-game',
            (self._player_entry(p, p.score) for p in started if p.position != 'QB'),
        )
        self.add(
            'player-game-playoff-points',
            'Most Points in a Playoff Game',
            'player-game',
            (self._player_entry(p, p.score) for p in started if p.bracket == PLAYOFFS),
        )
        self.add(
            'player-game-bench-points',
            'Most Points Left on the Bench',
            'player-game',
            (self._player_entry(p, p.score) for p in self.player_games if not p.starter),
            note='A single benched player.',
        )
        self.add(
            'player-game-fewest-points',
            'Fewest Points (Offensive Starter)',
            'player-game',
            (self._player_entry(p, p.score) for p in started if p.position in offense),
            lowest=True,
        )
        self.add(
            'player-game-fewest-points-k',
            'Fewest Points (Kicker)',
            'player-game',
            (self._player_entry(p, p.score) for p in started if p.position == 'K'),
            lowest=True,
        )
        shame = [p for p in started if p.position == 'D/ST' and p.score <= -6]
        self.add(
            'player-game-defense-shame',
            'Defensive Hall of Shame',
            'player-game',
            (self._player_entry(p, p.score) for p in shame),
            lowest=True,
            limit=len(shame),
            note='Defenses that started and scored -6.',
        )
        for position in POSITIONS:
            self.add(
                f'player-game-most-points-{_slug(position)}',
                f'Most Points in a Game ({position})',
                'player-game',
                (self._player_entry(p, p.score) for p in started if p.position == position),
                position=position,
            )

    def _player_totals(self, games: Iterable[PlayerGame]) -> list[dict]:
        totals: dict[str, dict] = {}
        for p in sorted(games, key=lambda p: p.order):
            key = self.profile_key_for(p.player_key)
            row = totals.setdefault(
                key,
                {
                    'player': p.name,
                    'profile_key': key,
                    'position': p.position,
                    'points': 0.0,
                    'starts': 0,
                    'thirties': 0,
                    'franchise_starts': defaultdict(int),
                    'teams': [],
                },
            )
            row['player'] = p.name
            row['points'] += p.score
            row['starts'] += 1
            row['thirties'] += p.score >= 30
            for franchise in p.franchises:
                row['franchise_starts'][franchise] += 1
            if p.abbrev not in row['teams']:
                row['teams'].append(p.abbrev)
            row['season'], row['week'], row['week_label'] = p.season, p.week, p.week_label
            row['last_team'] = p.abbrev
        return list(totals.values())

    def _total_entry(self, row: dict, value: float, **extra) -> dict:
        return {
            'value': value,
            'player': row['player'],
            'profile_key': row['profile_key'],
            'position': row['position'],
            'season': row.get('season'),
            **self._team_fields(row['last_team'], row['season']),
            'starts': row['starts'],
            **extra,
        }

    def player_season_records(self) -> None:
        started = [p for p in self.player_games if p.starter]
        by_season: dict[int, list[PlayerGame]] = defaultdict(list)
        for p in started:
            by_season[p.season].append(p)
        rows = []
        for games in by_season.values():
            for row in self._player_totals(games):
                rows.append(row)
        note = 'Points scored while in a starting lineup, playoffs included.'
        self.add(
            'player-season-most-points',
            'Most Points in a Season',
            'player-season',
            (self._total_entry(r, r['points'], teams=r['teams']) for r in rows),
            note=note,
        )
        for position in POSITIONS:
            self.add(
                f'player-season-most-points-{_slug(position)}',
                f'Most Points in a Season ({position})',
                'player-season',
                (
                    self._total_entry(r, r['points'], teams=r['teams'])
                    for r in rows
                    if r['position'] == position
                ),
                position=position,
                note=note,
            )

    def player_career_records(self) -> None:
        started = self._player_totals(p for p in self.player_games if p.starter)
        note = 'Points scored while in a starting lineup, playoffs included.'
        self.add(
            'player-career-most-points',
            'Most Career Points',
            'player-career',
            (self._total_entry(r, r['points']) for r in started),
            note=note,
        )
        for position in POSITIONS:
            self.add(
                f'player-career-most-points-{_slug(position)}',
                f'Most Career Points ({position})',
                'player-career',
                (self._total_entry(r, r['points']) for r in started if r['position'] == position),
                position=position,
                note=note,
            )
        self.add(
            'player-career-most-starts',
            'Most Career Starts',
            'player-career',
            (self._total_entry(r, r['starts']) for r in started),
            unit='starts',
        )
        self.add(
            'player-career-thirty-point-games',
            'Most 30-Point Games',
            'player-career',
            (self._total_entry(r, r['thirties']) for r in started if r['thirties']),
            unit='games',
        )
        self.add(
            'player-career-starts-one-franchise',
            'Most Starts for One Franchise',
            'player-career',
            (
                self._total_entry(r, count, franchise=franchise)
                for r in started
                for franchise, count in [
                    max(r['franchise_starts'].items(), key=lambda item: item[1])
                ]
            ),
            unit='starts',
        )

        rostered: dict[str, dict] = {}
        for p in sorted(self.player_games, key=lambda p: p.order):
            key = self.profile_key_for(p.player_key)
            row = rostered.setdefault(
                key,
                {'player': p.name, 'profile_key': key, 'position': p.position, 'franchises': []},
            )
            for franchise in p.franchises:
                if franchise not in row['franchises']:
                    row['franchises'].append(franchise)
            row.update(season=p.season, week=p.week, last_team=p.abbrev, player=p.name)
        self.add(
            'player-career-most-franchises',
            'Most Franchises Played For',
            'player-career',
            (
                {
                    'value': len(r['franchises']),
                    'player': r['player'],
                    'profile_key': r['profile_key'],
                    'position': r['position'],
                    'season': r['season'],
                    'franchises': r['franchises'],
                    **self._team_fields(r['last_team'], r['season']),
                }
                for r in rostered.values()
            ),
            unit='franchises',
            note='Any franchise that rostered the player for a game.',
        )

    # ------------------------------------------------------------------ #
    # League records
    # ------------------------------------------------------------------ #

    def league_records(self) -> None:
        weeks: dict[tuple[int, int], dict] = {}
        for g in self.team_games:
            week = weeks.setdefault(
                g.order,
                {
                    'value': 0.0,
                    'season': g.season,
                    'week': g.week,
                    'week_label': g.week_label,
                    'teams': 0,
                    'scored': True,
                },
            )
            week['value'] += g.score
            week['teams'] += 1
            week['scored'] &= g.score > 0
        # Only weeks the whole league played: playoff weeks where just the
        # finalists play would otherwise read as the lowest-scoring ever.
        league_size: dict[int, int] = defaultdict(int)
        for w in weeks.values():
            league_size[w['season']] = max(league_size[w['season']], w['teams'])
        totals = [
            {k: v for k, v in w.items() if k != 'scored'}
            for w in weeks.values()
            if w['scored'] and w['teams'] == league_size[w['season']]
        ]
        self.add(
            'league-highest-week',
            'Highest-Scoring Week (League Total)',
            'league',
            totals,
            note='Weeks every team played.',
        )
        self.add(
            'league-lowest-week',
            'Lowest-Scoring Week (League Total)',
            'league',
            totals,
            lowest=True,
            note='Weeks every team played.',
        )

        singles = [g for g in self.scored if g.single_game and g.decided and not g.lost]
        # Each game once: from the winner's side, or the first-listed side of a tie.
        seen: set[tuple] = set()
        once = []
        for g in singles:
            key = (g.season, g.week, *sorted((g.abbrev, g.opp_abbrev)))
            if key not in seen:
                seen.add(key)
                once.append(g)
        self.add(
            'league-closest-game',
            'Closest Games',
            'league',
            (self._game_entry(g, g.margin) for g in once),
            lowest=True,
        )
        self.add(
            'league-highest-combined',
            'Highest Combined Score',
            'league',
            (self._game_entry(g, g.score + g.opp_score) for g in once),
        )

    def fastest_cycle_records(self) -> None:
        """Each franchise's fewest games needed to beat every other franchise."""
        from qpfl.weekly_facts import fastest_cycles

        cycles = fastest_cycles(self.team_games, self.franchises)
        self.add(
            'team-fastest-cycle',
            'Fastest to Beat Every Team',
            'team-season',
            (
                {
                    'value': cycle.games,
                    'season': cycle.end.season,
                    'week': cycle.end.week,
                    'week_label': cycle.end.week_label,
                    # Named as the team that completed it was that week.
                    **self._team_fields(cycle.end.abbrev, cycle.end.season, cycle.end.week),
                    'franchise': cycle.franchise,
                    'start': {
                        'season': cycle.start.season,
                        'week': cycle.start.week,
                        'week_label': cycle.start.week_label,
                        'team': cycle.start.abbrev,
                    },
                }
                for cycle in cycles
            ),
            unit='games',
            lowest=True,
            limit=len(cycles),
            note='Fewest games to beat every current franchise, playoffs and two-week '
            'matchups included.',
        )

    def build(self) -> list[dict]:
        self.team_game_records()
        self.team_season_records()
        self.fastest_cycle_records()
        self.playoff_records()
        self.player_game_records()
        self.player_season_records()
        self.player_career_records()
        self.league_records()
        return self.groups


def _slug(position: str) -> str:
    return position.lower().replace('/', '')


def profile_key_lookup(player_career_stats: dict) -> Callable[[str], str]:
    """Map a game's player identity key to its career profile's key, following
    the aliases the profiles were merged from."""
    lookup: dict[str, str] = {}
    for profile in player_career_stats.values():
        key = profile.get('profile_key')
        if not key:
            continue
        lookup.setdefault(key, key)
        for alias in profile.get('aliases', []):
            lookup.setdefault(hof.player_identity_key(alias, profile.get('position')), key)
    return lambda key: lookup.get(key, key)


def build_record_book(
    all_seasons: list[dict],
    owner_label: Callable[[str, int], str],
    player_career_stats: dict | None = None,
    franchises: Iterable[str] = (),
) -> dict:
    book = RecordBook(
        all_seasons,
        owner_label,
        profile_key_lookup(player_career_stats) if player_career_stats else None,
        franchises,
    )
    return {
        'categories': [{'id': cid, 'title': title} for cid, title in CATEGORIES],
        'groups': book.build(),
    }


def all_qpfl_record_groups(
    selections: list[dict], owner_label: Callable[[str, int], str]
) -> list[dict]:
    """Career All-QPFL selection records, from the player honors' tally
    (scripts/hof_players.py), in the record book's group shape."""

    def entry(row: dict, value: int, years: list[int]) -> dict:
        return {
            'value': value,
            'player': row['player'],
            'profile_key': row['profile_key'],
            'position': row['position'],
            'season': row['season'],
            'years': sorted(years),
            'team': row['team'],
            'owner_code': hof._owner_identity_code(row['team']),
            'owner': owner_label(row['team'], row['season']),
        }

    groups = []
    for group_id, title, rows, note in (
        (
            'player-career-all-qpfl-first-team',
            'Most First-Team All-QPFL Selections',
            [
                entry(r, len(r['first_team']), r['first_team'])
                for r in selections
                if r['first_team']
            ],
            "The season's best starting lineup by points scored, playoffs included.",
        ),
        (
            'player-career-all-qpfl',
            'Most All-QPFL Selections',
            [
                entry(
                    r,
                    len(r['first_team']) + len(r['second_team']),
                    r['first_team'] + r['second_team'],
                )
                for r in selections
            ],
            'First and second team together.',
        ),
    ):
        ranked, tied = _ranked(rows)
        if not ranked:
            continue
        groups.append(
            _clean(
                {
                    'id': group_id,
                    'title': title,
                    'category': 'player-career',
                    'unit': 'selections',
                    'note': note,
                    'entries': [_clean(e) for e in ranked],
                    'more_tied': tied or None,
                }
            )
        )
    return groups
