#!/usr/bin/env python3
"""
Lightweight export script for current season updates.

This script is optimized for fast, frequent updates during the season.
It only updates scores and standings for the current season from JSON data.

For full exports (including historical data), use export_for_web.py.
"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nflreadpy as nfl

# qpfl lives one level up from scripts/; make it importable when run as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl import (  # noqa: E402
    avatars,
    build_availability_lookup,
    build_fantasy_team_from_json,
    calculate_week_projections,
    load_coach_overrides,
    load_projection_depth_chart_rows,
    load_projection_roster_rows,
    load_projection_schedule_rows,
    name_battles,
    team_names,
)
from qpfl.availability import COACH_OVERRIDES_FILENAME  # noqa: E402
from qpfl.injuries import load_injury_statuses  # noqa: E402
from qpfl.json_scorer import update_standings_json  # noqa: E402
from qpfl.models import PlayerScore  # noqa: E402
from qpfl.projections import player_projection_key  # noqa: E402
from qpfl.schedule import (  # noqa: E402
    get_playoff_schedule,
    get_regular_season_schedule,
    schedule_path_for_season,
    week16_results_from_output,
)

_CO_OWNER_LABELS = {
    'CWR': {'since': 2026, 'primary_suffix': 'Reardon', 'labels': ('Jack Reardon',)},
}


def add_co_owner_labels(label: str, abbrev: str, season: int) -> str:
    """Add full co-owner names to transaction labels from their start season."""
    config = _CO_OWNER_LABELS.get(abbrev)
    if not config or season < config['since']:
        return label
    suffix = config['primary_suffix']
    primary = label if label.endswith(suffix) else f'{label} {suffix}'
    return ' & '.join((primary, *config['labels']))


def get_current_nfl_week(season: int | None = None, fallback: int = 1) -> int:
    """Get the current NFL week without capping the provider's value.

    Only trust the provider's week when it is reporting the season being
    exported. Between seasons it keeps reporting the tail of the previous one
    — week 22 of 2025 in early September 2026 — and carrying that number into
    this season's payload puts current_week outside the 1-17 range, which
    zeroes lineup_week and closes lineup submission for the whole league.

    `fallback` should be the last known-good current_week (the previous
    export's committed value), not a bare 1: a transient provider failure in,
    say, Week 10 must not export current_week=1 mid-season and silently
    repoint lineup editing at Week 1 - see docs/ROADMAP_2026.md P3.1 / the
    in-season reliability plan, phase 2.2. 1 remains correct as the default
    for a season with no prior export (a new season, or Week 1 itself).
    """
    try:
        if season is not None and nfl.get_current_season() != season:
            return fallback
        return nfl.get_current_week()
    except Exception:
        return fallback


def build_week_kickoffs(
    season: int,
    week: int,
    schedule_rows: list[dict] | None = None,
) -> dict[str, str]:
    """Map each NFL team playing in `week` to its kickoff time (UTC ISO 8601).

    Published into web/data.json so the lineup API can enforce a server-side
    lineup lock at kickoff (a player whose game has started can't be added to or
    dropped from a starting lineup). Fails open — any problem returns {} so the
    lock is simply inert rather than blocking the export or wrongly locking
    lineups.
    """
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        eastern = ZoneInfo('America/New_York')
        rows = (
            schedule_rows
            if schedule_rows is not None
            else list(nfl.load_schedules(seasons=season).iter_rows(named=True))
        )
        kickoffs: dict[str, str] = {}
        for row in rows:
            row_season = row.get('season')
            if row_season is not None and row_season != season:
                continue
            if row.get('game_type') != 'REG' or row.get('week') != week:
                continue
            gameday = row.get('gameday')
            gametime = row.get('gametime')
            if not gameday or not gametime:
                continue
            try:
                # nflverse gametime is Eastern, 24h "HH:MM".
                local = _dt.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M').replace(
                    tzinfo=eastern
                )
            except ValueError:
                continue
            iso = local.astimezone(timezone.utc).isoformat()
            for team in (row.get('home_team'), row.get('away_team')):
                if team:
                    kickoffs[str(team)] = iso
        return kickoffs
    except Exception as e:  # pragma: no cover - depends on live nflverse data
        print(f'  Could not build kickoff times (lineup lock will be inert): {e}')
        return {}


def build_full_season_schedule_maps(
    season: int,
    schedule_rows: list[dict],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, dict]]]:
    """Build kickoff and opponent maps for every week of `season`, keyed by week then team.

    Regenerated from the live schedule on every export (unlike a player's own
    `nfl_opponent`/`kickoff` fields, which only ever reflect the active lineup week) so
    browsing a different week never shows stale or wrong-season matchup data.
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo('America/New_York')
    game_times: dict[str, dict[str, str]] = {}
    game_opponents: dict[str, dict[str, dict]] = {}
    for row in schedule_rows:
        if row.get('season') != season or row.get('game_type') not in (None, 'REG'):
            continue
        week = row.get('week')
        home = row.get('home_team')
        away = row.get('away_team')
        if not isinstance(week, int) or not home or not away:
            continue
        week_key = str(week)

        gameday = row.get('gameday')
        gametime = row.get('gametime')
        if gameday and gametime:
            try:
                local = _dt.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M').replace(
                    tzinfo=eastern
                )
                iso = local.astimezone(timezone.utc).isoformat()
                game_times.setdefault(week_key, {})[home] = iso
                game_times.setdefault(week_key, {})[away] = iso
            except ValueError:
                pass

        game_opponents.setdefault(week_key, {})[home] = {'opponent': away, 'is_home': True}
        game_opponents.setdefault(week_key, {})[away] = {'opponent': home, 'is_home': False}

    return game_times, game_opponents


def enrich_live_roster_context(
    data: dict,
    season: int,
    week: int,
    history_root: Path,
    schedule_rows: list[dict] | None = None,
    injury_cache_path: Path | None = None,
    roster_rows: list[dict] | None = None,
    depth_chart_rows: list[dict] | None = None,
    coach_overrides_path: Path | None = None,
    now: datetime | None = None,
    previous_kickoffs: dict[str, str] | None = None,
    previous_game_times: dict | None = None,
    previous_game_opponents: dict | None = None,
) -> dict[str, str]:
    """Attach the active week's opponent, kickoff, and projection to live rosters.

    `previous_kickoffs`/`previous_game_times`/`previous_game_opponents` should
    be this season's currently-committed live.json values. Kickoff times for
    the active week are effectively immutable once published, so on a
    transient schedule-load failure, carrying the stale-but-present previous
    values forward is strictly better than dropping the keys - an absent
    `kickoffs` makes api/lineup.py fail closed and locks the whole league out
    of lineup submission on what may be a one-run blip. See
    docs/ROADMAP_2026.md P3.1 / the in-season reliability plan, phase 2.3.
    """
    if injury_cache_path is not None:
        data['injuries'] = load_injury_statuses(data.get('rosters', {}), injury_cache_path)

    try:
        rows = list(
            schedule_rows
            if schedule_rows is not None
            else load_projection_schedule_rows([season - 1, season])
        )
    except Exception as e:  # pragma: no cover - depends on live nflverse data
        print(
            f'  Could not load NFL schedule context ({e}); '
            'carrying forward the previous kickoffs/game_times/game_opponents'
        )
        data['game_times'] = dict(previous_game_times or {})
        data['game_opponents'] = dict(previous_game_opponents or {})
        return dict(previous_kickoffs or {})

    kickoffs = build_week_kickoffs(season, week, rows)
    data['game_times'], data['game_opponents'] = build_full_season_schedule_maps(season, rows)
    rosters = data.get('rosters', {})
    if not isinstance(rosters, dict) or not rosters:
        return kickoffs

    # Availability only ever removes points, so every failure here falls back to
    # "everyone plays" rather than zeroing someone on bad data.
    try:
        nfl_roster_rows = list(
            roster_rows if roster_rows is not None else load_projection_roster_rows(season)
        )
    except Exception as e:  # pragma: no cover - depends on live nflverse data
        print(f'  Could not load NFL roster statuses (projecting everyone as available): {e}')
        nfl_roster_rows = []
    try:
        nfl_depth_chart_rows = list(
            depth_chart_rows
            if depth_chart_rows is not None
            else load_projection_depth_chart_rows(season)
        )
    except Exception as e:  # pragma: no cover - depends on live nflverse data
        print(f'  Could not load NFL depth charts (skipping backup detection): {e}')
        nfl_depth_chart_rows = []
    availability = build_availability_lookup(
        nfl_roster_rows, data.get('injuries'), nfl_depth_chart_rows
    )
    coach_overrides = (
        load_coach_overrides(coach_overrides_path) if coach_overrides_path is not None else {}
    )

    try:
        teams_info: dict[str, dict[str, Any]] = {}
        for team_info in data.get('teams', []):
            if not isinstance(team_info, dict):
                continue
            abbrev = team_info.get('abbrev')
            if isinstance(abbrev, str) and abbrev:
                teams_info[abbrev] = team_info
        lineups = data.get('lineups', {})
        teams = [
            build_fantasy_team_from_json(abbrev, rosters, lineups, teams_info) for abbrev in rosters
        ]
        results = {}
        for team in teams:
            scores: dict[str, list[tuple[PlayerScore, bool]]] = {}
            for position, players in team.players.items():
                scores[position] = [
                    (
                        PlayerScore(name=name, position=position, team=nfl_team),
                        is_starter,
                    )
                    for name, nfl_team, is_starter in players
                ]
            results[team.name] = (0.0, scores)

        schedule_week = next(
            (
                item
                for item in data.get('schedule', [])
                if isinstance(item, dict) and item.get('week') == week
            ),
            {},
        )
        matchups = schedule_week.get('matchups', [])
        projections = calculate_week_projections(
            teams,
            results,
            matchups,
            season,
            week,
            history_root,
            rows,
            availability=availability,
            coach_overrides=coach_overrides,
            now=now,
        )

        for team in teams:
            for player in rosters.get(team.abbreviation, []):
                projection = projections.players.get(
                    player_projection_key(
                        team.abbreviation,
                        str(player.get('name', '')),
                        str(player.get('position', '')),
                    )
                )
                if not projection:
                    continue
                player.update(
                    {
                        'projected_points': projection.projected_points,
                        'nfl_opponent': projection.game.opponent,
                        'nfl_is_home': projection.game.is_home,
                        'kickoff': projection.game.kickoff,
                        'game_final': projection.game.final,
                        'on_bye': projection.on_bye,
                    }
                )
                if projection.unavailable_reason:
                    player['unavailable_reason'] = projection.unavailable_reason
                else:
                    player.pop('unavailable_reason', None)
    except Exception as e:
        print(f'  Could not build live roster projections: {e}')

    return kickoffs


def add_pick_numbers_to_draft_picks(picks: list, draft_orders: dict) -> list:
    """Add pick number (e.g., '1.01') to each draft pick based on draft order.

    Args:
        picks: List of draft pick dictionaries
        draft_orders: Dict of draft orders by year and type

    Returns:
        Updated list of picks with 'pick_number' field added
    """
    if not picks:
        return picks

    enriched_picks = []
    for pick in picks:
        pick_copy = pick.copy()
        year = str(pick.get('year', ''))
        draft_type = pick.get('draft_type', '')
        round_num = pick.get('round', 0)
        original_team = pick.get('original_team', '')

        # Get draft order for this year/type
        if year in draft_orders and draft_type in draft_orders[year]:
            order = draft_orders[year][draft_type]
            if original_team in order:
                position = order.index(original_team) + 1
                # Format as round.pick (e.g., 1.01, 2.10)
                pick_copy['pick_number'] = f'{round_num}.{position:02d}'

        enriched_picks.append(pick_copy)

    return enriched_picks


def generate_upcoming_drafts(picks: list, draft_orders: dict, season: int, teams: list) -> list:
    """Generate upcoming draft views showing pick order with current owners.

    Args:
        picks: List of draft pick dictionaries with pick_number
        draft_orders: Dict of draft orders by year and type
        season: Current season year
        teams: List of team dictionaries

    Returns:
        List of upcoming draft dictionaries
    """
    upcoming = []

    # Get draft types that have orders for the upcoming season
    season_str = str(season)
    if season_str not in draft_orders:
        return upcoming

    # Create a draft view for each draft type
    # Combine regular and taxi drafts into single views (e.g., offseason + offseason_taxi)
    processed_types = set()

    for draft_type, _order in draft_orders[season_str].items():
        # Skip taxi drafts - they'll be included with their main draft
        if draft_type.endswith('_taxi'):
            continue

        # Skip if already processed
        if draft_type in processed_types:
            continue
        processed_types.add(draft_type)

        # Get corresponding taxi draft type
        taxi_type = f'{draft_type}_taxi'

        # Filter picks for this year and both regular and taxi draft types
        draft_picks = [
            p
            for p in picks
            if p.get('year') == season_str and p.get('draft_type') in (draft_type, taxi_type)
        ]

        if not draft_picks:
            continue

        # Group by round, separating taxi and regular rounds
        rounds_dict = {}
        for pick in draft_picks:
            round_num = pick.get('round', 0)
            pick_draft_type = pick.get('draft_type', '')

            # Use different round keys for taxi picks
            if pick_draft_type.endswith('_taxi'):
                round_key = f'TAXI Round {round_num}'
            else:
                round_key = round_num

            if round_key not in rounds_dict:
                rounds_dict[round_key] = []
            rounds_dict[round_key].append(pick)

        # Build rounds list
        # Sort regular rounds first (numeric), then taxi rounds (strings)
        rounds = []
        regular_rounds = [k for k in rounds_dict if isinstance(k, int)]
        taxi_rounds = [k for k in rounds_dict if isinstance(k, str)]

        for round_key in sorted(regular_rounds) + sorted(taxi_rounds):
            round_picks = sorted(rounds_dict[round_key], key=lambda x: x.get('pick_number', ''))
            rounds.append({'round': round_key, 'picks': round_picks})

        # Determine draft name
        if draft_type == 'offseason':
            name = f'{season} Offseason Draft'
        elif draft_type == 'midseason':
            name = f'{season} Midseason Draft'
        elif draft_type == 'waiver':
            name = f'{season} Waiver Draft'
        else:
            name = f'{season} {draft_type.replace("_", " ").title()} Draft'

        upcoming.append({'name': name, 'year': season, 'type': draft_type, 'rounds': rounds})

    return upcoming


def load_json(path: Path) -> dict | list:
    """Load JSON file, return empty dict/list if not found."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _without_updated_at(payload):
    """Strip the one field every export always advances, so a no-op run can
    be recognized as one - see write_split_runtime_data's write_json."""
    if isinstance(payload, dict):
        return {key: value for key, value in payload.items() if key != 'updated_at'}
    return payload


def apply_avatars(data: dict, data_dir: Path, season: int) -> None:
    """Stamp each team object with the point-in-time avatar URL in effect for it.

    Avatars are versioned per ``(season, week)`` in ``data/avatars.json``; a new
    upload applies to that week and forward, so historical surfaces keep the older
    image. Current-state surfaces (teams, standings) use the latest avatar; per-week
    matchups and week team lists use the avatar in effect as of that week. Mutates
    ``data`` in place. Teams with no avatar are left unstamped so the frontend falls
    back to its initials circle. See ``qpfl/avatars.py`` and ``data/avatars.json``.
    """
    manifest = avatars.load_manifest(data_dir / 'avatars.json')
    if not manifest:
        return

    def stamp_current(team: dict) -> None:
        url = avatars.current_avatar(manifest, team.get('abbrev'))
        if url:
            team['avatar'] = url

    for team in data.get('teams', []) or []:
        stamp_current(team)
    standings = data.get('standings')
    if isinstance(standings, dict):
        standings = standings.get('standings', [])
    for row in standings or []:
        stamp_current(row)

    # Per-week matchups + week-level team lists reflect the point-in-time avatar.
    for week in data.get('weeks', []) or []:
        wknum = week.get('week')
        for matchup in week.get('matchups', []) or []:
            for side in ('team1', 'team2'):
                t = matchup.get(side)
                if isinstance(t, dict):
                    url = avatars.avatar_at(manifest, t.get('abbrev'), season, wknum)
                    if url:
                        t['avatar'] = url
        for t in week.get('teams', []) or []:
            url = avatars.avatar_at(manifest, t.get('abbrev'), season, wknum)
            if url:
                t['avatar'] = url


def apply_name_battles(data: dict, data_dir: Path, web_dir: Path, season: int) -> None:
    """Rewrite owner display names to reflect who currently holds each contested
    "name battle" name (Connor Bowl, Brother Bowl, Kuhl Cup), computed from
    head-to-head game results rather than maintained by hand.

    Current-state surfaces (teams, standings) use the current holder; per-week
    matchups use the holder as of that week; transaction labels for first-name
    battles are stamped point-in-time. Mutates ``data`` in place. See
    ``qpfl/name_battles.py`` and ``data/name_battles.json``.
    """
    config_path = data_dir / 'name_battles.json'
    if not config_path.exists():
        return
    battles = name_battles.load_config(config_path)
    if not battles:
        return

    current_weeks = data.get('weeks', []) or []

    # Load prior-season archives (newest first) to derive the season-start holder
    # and to resolve transaction labels that span multiple seasons.
    seasons_weeks: dict[int, list] = {season: current_weeks}
    prior_seasons: list[list] = []
    for year in range(season - 1, 2019, -1):
        archive = web_dir / f'data_{year}.json'
        if not archive.exists():
            continue
        try:
            adata = json.loads(archive.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        weeks = adata.get('weeks', []) or []
        seasons_weeks[year] = weeks
        prior_seasons.append(weeks)

    season_start = name_battles.compute_season_start_holders(battles, prior_seasons)
    current = name_battles.current_holders(battles, current_weeks, season_start)

    # Current-state surfaces: teams + standings reflect the current holder.
    for team in data.get('teams', []) or []:
        if team.get('owner'):
            team['owner'] = name_battles.apply_all(team['owner'], battles, current)
    for row in data.get('standings', []) or []:
        if row.get('owner'):
            row['owner'] = name_battles.apply_all(row['owner'], battles, current)

    # Per-week matchups + week-level team lists reflect the point-in-time holder.
    for week in current_weeks:
        wknum = week.get('week')
        if not isinstance(wknum, int):
            continue
        holders = name_battles.holders_for_week(battles, current_weeks, season_start, wknum)
        for matchup in week.get('matchups', []) or []:
            for side in ('team1', 'team2'):
                t = matchup.get(side)
                if t and t.get('owner'):
                    t['owner'] = name_battles.apply_all(t['owner'], battles, holders)
        for t in week.get('teams', []) or []:
            if t.get('owner'):
                t['owner'] = name_battles.apply_all(t['owner'], battles, holders)

    # Transaction labels: only first-name battles (the Connor Bowl) change the
    # owner first name the frontend renders for trades. Stamp the point-in-time
    # label so the historical log never shifts retroactively. recent_transactions
    # shares these dicts, so it picks up the labels too.
    for tx in data.get('transactions', []) or []:
        if tx.get('type') != 'trade':
            continue
        tx_season = tx.get('season', season)
        tx_week = tx.get('week')
        for field, label_field in (
            ('proposer', 'proposer_label'),
            ('partner', 'partner_label'),
        ):
            abbrev = tx.get(field)
            if not abbrev:
                continue
            label = name_battles.first_name_label_at(
                abbrev, battles, seasons_weeks, tx_season, tx_week
            )
            if label is not None:
                tx[label_field] = add_co_owner_labels(label, abbrev, tx_season)


def build_completed_standings(
    data: dict, web_dir: Path, season: int, completed_through: int
) -> list[dict]:
    """Build standings using only weeks that are known to be complete."""
    current_standings = data.get('standings', [])
    if isinstance(current_standings, dict):
        current_standings = current_standings.get('standings', [])

    identities = {}
    for team in [*current_standings, *data.get('teams', [])]:
        abbrev = team.get('abbrev')
        if abbrev:
            identities[abbrev] = {**identities.get(abbrev, {}), **team}

    def blank_row(team: dict) -> dict:
        name = team.get('name') or team.get('team_name') or team.get('abbrev', '')
        row = {
            'name': name,
            'owner': team.get('owner', ''),
            'abbrev': team.get('abbrev', ''),
            'rank_points': 0.0,
            'wins': 0,
            'losses': 0,
            'ties': 0,
            'top_half': 0,
            'points_for': 0.0,
            'points_against': 0.0,
        }
        if team.get('avatar'):
            row['avatar'] = team['avatar']
        return row

    ordered_teams = data.get('teams', []) or current_standings
    if completed_through <= 0:
        result = [blank_row(team) for team in ordered_teams if team.get('abbrev')]
    else:
        weeks_dir = web_dir / 'data' / 'seasons' / str(season) / 'weeks'
        week_paths = [
            weeks_dir / f'week_{week}.json'
            for week in range(1, completed_through + 1)
            if (weeks_dir / f'week_{week}.json').exists()
        ]
        if week_paths:
            with tempfile.TemporaryDirectory() as temp_dir:
                result = update_standings_json(
                    Path(temp_dir) / 'standings.json', week_paths, season
                )
        else:
            result = []

        present = {team.get('abbrev') for team in result}
        result.extend(
            blank_row(team)
            for team in ordered_teams
            if team.get('abbrev') and team.get('abbrev') not in present
        )

    for seed, team in enumerate(result, 1):
        identity = identities.get(team.get('abbrev'), {})
        team['name'] = identity.get('name') or identity.get('team_name') or team.get('name', '')
        team['owner'] = identity.get('owner', team.get('owner', ''))
        if identity.get('avatar'):
            team['avatar'] = identity['avatar']
        team['seed'] = seed
    return result


def write_split_runtime_data(data: dict, web_dir: Path, season: int) -> None:
    """Publish the current season's independently cacheable frontend resources."""
    split_root = web_dir / 'data'
    season_dir = split_root / 'seasons' / str(season)
    shared_dir = split_root / 'shared'
    season_dir.mkdir(parents=True, exist_ok=True)
    shared_dir.mkdir(parents=True, exist_ok=True)

    def write_json(path: Path, payload) -> None:
        # A run whose content genuinely didn't change (a schedule-only
        # commit, a re-run with no new stats) must not still produce a commit
        # and a redeploy just because `updated_at` always advances. Comparing
        # with that one volatile field stripped out is the same pattern
        # export_hall_of_fame.py already uses for the same reason. See
        # docs/ROADMAP_2026.md P3.1 / the in-season reliability plan, phase 3.3.
        if path.exists():
            existing = load_json(path)
            if _without_updated_at(existing) == _without_updated_at(payload):
                return
        with open(path, 'w') as f:
            json.dump(payload, f, separators=(',', ':'))

    completed_by_season = data.get('hall_of_fame', {}).get('completed_through', {})
    completed_through = completed_by_season.get(str(season))
    if not isinstance(completed_through, int):
        completed_through = max(0, int(data.get('current_week', 1) or 1) - 1)
    completed_through = min(15, max(0, completed_through))

    meta_path = season_dir / 'meta.json'
    meta = load_json(meta_path) if meta_path.exists() else {}
    meta.update(
        {
            'season': season,
            'current_week': data.get('current_week', 0),
            'completed_through': completed_through,
            'lineup_week': data.get('lineup_week', 0),
            'is_current': True,
            'is_historical': False,
            'is_offseason': data.get('is_offseason', False),
            'trade_deadline_week': data.get('trade_deadline_week', 12),
            'teams': data.get('teams', []),
            'schedule': data.get('schedule', []),
            'weeks_available': sorted(
                week.get('week')
                for week in data.get('weeks', [])
                if isinstance(week.get('week'), int)
            ),
            'updated_at': data.get('updated_at'),
        }
    )
    write_json(meta_path, meta)

    standings = data.get('standings', [])
    if isinstance(standings, dict):
        standings = standings.get('standings', [])
    completed_standings = build_completed_standings(
        data,
        web_dir,
        season,
        completed_through,
    )
    write_json(
        season_dir / 'standings.json',
        {
            'standings': standings,
            'completed_standings': completed_standings,
            'completed_through': completed_through,
            'updated_at': data.get('updated_at'),
        },
    )
    write_json(season_dir / 'rosters.json', data.get('rosters', {}))
    write_json(season_dir / 'draft_picks.json', data.get('draft_picks', []))

    # The matchups page reads week files directly, so persist the point-in-time
    # display rewrites (team names, name battles, avatars) that were applied to
    # `data['weeks']` in memory. The autoscorer writes these files with the
    # canonical owner names from data/teams.json, which would otherwise leave
    # e.g. "Connor Reardon" on matchups after he lost the Connor Bowl.
    weeks_dir = season_dir / 'weeks'
    for week in data.get('weeks', []) or []:
        wknum = week.get('week')
        if not isinstance(wknum, int):
            continue
        week_path = weeks_dir / f'week_{wknum}.json'
        if not week_path.exists() or load_json(week_path) == week:
            continue
        with open(week_path, 'w') as f:
            json.dump(week, f, indent=2)

    live_fields = (
        'current_week',
        'lineup_week',
        'is_offseason',
        'trade_deadline_week',
        'fa_pool',
        'game_times',
        'game_opponents',
        'kickoffs',
        'injuries',
        'lineups',
        'pending_trades',
        'trade_blocks',
        'recent_transactions',
        'team_stats',
        'upcoming_drafts',
        'updated_at',
    )
    write_json(
        season_dir / 'live.json',
        {key: data[key] for key in live_fields if key in data},
    )

    if 'transactions' in data:
        write_json(
            shared_dir / 'transactions.json',
            {
                'transactions': data.get('transactions', []),
                'updated_at': data.get('updated_at'),
            },
        )
    if 'drafts' in data:
        write_json(
            shared_dir / 'drafts.json',
            {'drafts': data.get('drafts', []), 'updated_at': data.get('updated_at')},
        )


def export_current_season(data_dir: Path, web_dir: Path, season: int = 2026) -> dict:
    """
    Export current season data from JSON sources.

    Args:
        data_dir: Path to data/ directory
        web_dir: Path to web/ directory
        season: Current season year

    Returns:
        Updated data dictionary
    """
    # Load existing data.json to preserve historical data
    data_json_path = web_dir / 'data.json'
    if data_json_path.exists():
        with open(data_json_path) as f:
            data = json.load(f)
    else:
        data = {}

    league_config_path = data_dir / 'league_config.json'
    if not league_config_path.exists():
        raise FileNotFoundError(f'Missing league configuration: {league_config_path}')
    league_config = load_json(league_config_path)
    is_offseason = league_config.get('is_offseason')
    if not isinstance(is_offseason, bool):
        raise ValueError('league_config.json is_offseason must be true or false')

    # Load shared data from JSON (no Word docs)
    shared_dir = web_dir / 'data' / 'shared'

    # Constitution (static, rarely changes)
    constitution_path = shared_dir / 'constitution.json'
    if constitution_path.exists():
        data['constitution'] = load_json(constitution_path)

    # Hall of Fame stats
    hof_path = shared_dir / 'hall_of_fame.json'
    if hof_path.exists():
        data['hall_of_fame'] = load_json(hof_path)

    # Banners
    banners_path = shared_dir / 'banners.json'
    if banners_path.exists():
        data['banners'] = load_json(banners_path)
    else:
        # Fall back to scanning images directory
        banners_dir = web_dir / 'images' / 'banners'
        if banners_dir.exists():
            data['banners'] = sorted([f.name for f in banners_dir.glob('*_banner.png')])

    # Transactions from JSON log. Admin/commissioner events (e.g. maintenance mode
    # toggles) are excluded here since they belong only in the commissioner audit
    # log, not the public transaction feed.
    tx_log_path = data_dir / 'transaction_log.json'
    if tx_log_path.exists():
        tx_data = load_json(tx_log_path)
        all_txns = [tx for tx in tx_data.get('transactions', []) if not tx.get('admin')]
        data['transactions'] = all_txns  # Already sorted newest-first
        data['recent_transactions'] = all_txns[:10]  # First 10 (newest) for homepage

    # Pending trades
    pending_trades_path = data_dir / 'pending_trades.json'
    if pending_trades_path.exists():
        trades_data = load_json(pending_trades_path)
        data['pending_trades'] = trades_data.get('trades', [])

    # Trade blocks
    trade_blocks_path = data_dir / 'trade_blocks.json'
    if trade_blocks_path.exists():
        data['trade_blocks'] = load_json(trade_blocks_path)

    # FA pool (flat list of {name, position, nfl_team, available} — see
    # api/transaction.py handle_fa_activation, the only thing that mutates it)
    fa_pool_path = data_dir / 'fa_pool.json'
    if fa_pool_path.exists():
        data['fa_pool'] = load_json(fa_pool_path)

    # Teams and rosters
    teams_path = data_dir / 'teams.json'
    if teams_path.exists():
        teams_data = load_json(teams_path)
        data['teams'] = teams_data.get('teams', [])

    rosters_path = data_dir / 'rosters.json'
    if rosters_path.exists():
        data['rosters'] = load_json(rosters_path)

    # Current season weeks from web/data/seasons/{year}/weeks/
    season_dir = web_dir / 'data' / 'seasons' / str(season)
    weeks_dir = season_dir / 'weeks'

    if weeks_dir.exists():
        weeks = []
        for week_file in sorted(weeks_dir.glob('week_*.json')):
            week_data = load_json(week_file)
            if week_data:
                weeks.append(week_data)

        # Update current season weeks in data
        # Find and replace current season or append
        if 'seasons' not in data:
            data['seasons'] = {}
        data['seasons'][str(season)] = {
            'weeks': weeks,
            'standings': load_json(season_dir / 'standings.json')
            if (season_dir / 'standings.json').exists()
            else [],
            'meta': load_json(season_dir / 'meta.json')
            if (season_dir / 'meta.json').exists()
            else {},
        }

    # For backward compatibility, also set top-level weeks/standings to current season
    if str(season) in data.get('seasons', {}):
        season_data = data['seasons'][str(season)]
        data['weeks'] = season_data.get('weeks', [])
        data['standings'] = season_data.get('standings', [])
        if isinstance(data['standings'], dict):
            data['standings'] = data['standings'].get('standings', [])

    # The 'seasons' map is internal to the exporter (used to derive top-level
    # weeks/standings). The frontend only reads top-level fields, so drop it
    # to avoid shipping ~870 KB of redundant payload.
    data.pop('seasons', None)

    # The offseason homepage now lazy-loads the previous season from its own
    # data_{prev}.json file, so make sure any copy carried over from an older
    # data.json (this script seeds from the existing file) is dropped.
    data.pop('previous_season', None)

    # Calculate team_stats from current season weeks
    # If no weeks yet (new season), team_stats should be empty
    weeks = data.get('weeks', [])
    standings = data.get('standings', [])
    if weeks and standings:
        # Import calculate_team_stats from export_for_web.py
        import sys

        script_dir = Path(__file__).parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from export_for_web import calculate_team_stats

        data['team_stats'] = calculate_team_stats(weeks, standings)
    else:
        # No weeks yet - clear team_stats so previous season data doesn't show
        data['team_stats'] = {}

    # Draft picks - prefer data/draft_picks.json (single source of truth)
    draft_picks_path = data_dir / 'draft_picks.json'
    if draft_picks_path.exists():
        picks_data = load_json(draft_picks_path)
        data['draft_picks'] = picks_data.get('picks', {})
    else:
        # Fall back to season-specific file
        season_picks_path = season_dir / 'draft_picks.json'
        if season_picks_path.exists():
            data['draft_picks'] = load_json(season_picks_path)

    # Load draft orders and add pick numbers to draft picks
    draft_orders_path = data_dir / 'draft_orders.json'
    if draft_orders_path.exists():
        draft_orders = load_json(draft_orders_path)
        if data.get('draft_picks'):
            data['draft_picks'] = add_pick_numbers_to_draft_picks(data['draft_picks'], draft_orders)
            # Generate upcoming draft views with pick order
            data['upcoming_drafts'] = generate_upcoming_drafts(
                data['draft_picks'], draft_orders, season, data.get('teams', [])
            )

    # Drafts history
    drafts_path = data_dir / 'drafts.json'
    if drafts_path.exists():
        drafts_data = load_json(drafts_path)
        data['drafts'] = drafts_data.get('drafts', [])

    weeks = data.get('weeks', [])
    max_week = max((w.get('week', 0) for w in weeks), default=0) if weeks else 0

    # Each season owns its regular-season schedule. An empty/missing file means
    # the schedule has not been set for this season yet.
    season_dir = web_dir / 'data' / 'seasons' / str(season)
    meta_path = season_dir / 'meta.json'

    # The commissioner-controlled league setting is the only source of truth
    # for whether the current season is in offseason mode.
    #
    # A transient provider failure must fall back to the last known-good
    # current_week (this season's previously committed meta.json), not a bare
    # 1 - see get_current_nfl_week's docstring / docs/ROADMAP_2026.md P3.1.
    previous_current_week = None
    if meta_path.exists():
        previous_meta = load_json(meta_path)
        if isinstance(previous_meta, dict):
            candidate = previous_meta.get('current_week')
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                previous_current_week = candidate
    nfl_week = get_current_nfl_week(season, fallback=previous_current_week or max(max_week, 1))
    schedule_txt_path = schedule_path_for_season(data_dir, season)
    regular_season_schedule = []
    if schedule_txt_path.exists():
        regular_season_schedule = get_regular_season_schedule(schedule_txt_path)
        # Drop trailing weeks with no matchups (unfilled placeholder rows).
        while regular_season_schedule and not regular_season_schedule[-1]['matchups']:
            regular_season_schedule.pop()

    has_schedule = len(regular_season_schedule) > 0
    data['schedule'] = regular_season_schedule

    # meta.json's schedule is written once, from this final `data['schedule']`,
    # by write_split_runtime_data() at the end of this function - writing it
    # here too was redundant (nothing reads meta.json from disk in between)
    # and, worse, made every run look like it changed something: an earlier
    # version of this write ran before apply_avatars()/apply_name_battles()
    # finished mutating `data`, so it always left a stale intermediate
    # version on disk that write_split_runtime_data's no-op guard would then
    # compare against and always find different. See docs/ROADMAP_2026.md
    # P3.1 / the in-season reliability plan, phase 3.3.
    if has_schedule and (nfl_week >= 15 or max_week >= 15):
        standings_path = season_dir / 'standings.json'
        standings = []
        if standings_path.exists():
            standings_data = load_json(standings_path)
            standings = (
                standings_data.get('standings', [])
                if isinstance(standings_data, dict)
                else standings_data
            )
        if standings:
            # Week 17's finals come from the Week 16 results once they're final.
            week16_path = season_dir / 'weeks' / 'week_16.json'
            week16 = week16_results_from_output(
                load_json(week16_path) if week16_path.exists() else None
            )
            data['schedule'] = regular_season_schedule + get_playoff_schedule(
                standings, season, week16
            )

    if is_offseason:
        data['current_week'] = 0
        data['is_offseason'] = True

        # Generate placeholder standings from previous season order or teams list
        if not data.get('standings') or len(data.get('standings', [])) == 0:
            # Use previous season standings order if available
            prev_data_path = web_dir / f'data_{season - 1}.json'
            if prev_data_path.exists():
                prev_data = load_json(prev_data_path)
                prev_standings = prev_data.get('standings', [])
                if isinstance(prev_standings, dict):
                    prev_standings = prev_standings.get('standings', [])
                # Create placeholder standings with 0 stats
                # Look up current team names by abbrev
                teams_by_abbrev = {t.get('abbrev'): t for t in data.get('teams', [])}
                data['standings'] = [
                    {
                        'abbrev': t.get('abbrev'),
                        'team_name': teams_by_abbrev.get(t.get('abbrev'), {}).get(
                            'name', t.get('name', t.get('abbrev'))
                        ),
                        'name': teams_by_abbrev.get(t.get('abbrev'), {}).get(
                            'name', t.get('name', t.get('abbrev'))
                        ),
                        'owner': teams_by_abbrev.get(t.get('abbrev'), {}).get(
                            'owner', t.get('owner', '')
                        ),
                        'rank_points': 0,
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'points_for': 0,
                        'points_against': 0,
                    }
                    for t in prev_standings
                ]
            elif data.get('teams'):
                # No previous season, use current teams
                data['standings'] = [
                    {
                        'abbrev': t.get('abbrev'),
                        'team_name': t.get('name'),
                        'name': t.get('name'),
                        'owner': t.get('owner', ''),
                        'rank_points': 0,
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'points_for': 0,
                        'points_against': 0,
                    }
                    for t in data['teams']
                ]

        # For offseason, don't create placeholder weeks - let the frontend handle it
        # The frontend will show a "Coming Soon" message for matchups
    else:
        data['current_week'] = nfl_week
        data['is_offseason'] = False

    if data['is_offseason'] and max_week < 17:
        data['lineup_week'] = 1
    elif not data['is_offseason'] and 1 <= data['current_week'] <= 17:
        data['lineup_week'] = data['current_week']
    else:
        data['lineup_week'] = 0

    current_lineup_week = data['lineup_week']
    if 1 <= current_lineup_week <= 17:
        # Lineup availability remains independent from the homepage mode so
        # managers can submit Week 1 before the commissioner flips the switch.
        lineup_path = data_dir / 'lineups' / str(season) / f'week_{current_lineup_week}.json'
        lineup_data = load_json(lineup_path)
        data['lineups'] = lineup_data.get('lineups', {}) if isinstance(lineup_data, dict) else {}
        previous_live_path = season_dir / 'live.json'
        previous_live = load_json(previous_live_path) if previous_live_path.exists() else {}
        if not isinstance(previous_live, dict):
            previous_live = {}
        data['kickoffs'] = enrich_live_roster_context(
            data,
            season,
            current_lineup_week,
            web_dir / 'data' / 'seasons',
            injury_cache_path=data_dir / 'injury_statuses.json',
            coach_overrides_path=data_dir / COACH_OVERRIDES_FILENAME,
            previous_kickoffs=previous_live.get('kickoffs'),
            previous_game_times=previous_live.get('game_times'),
            previous_game_opponents=previous_live.get('game_opponents'),
        )
    else:
        data['kickoffs'] = {}
        data['injuries'] = {}
        data['lineups'] = {}

    data['season'] = season
    data['is_historical'] = False  # Current season is never historical
    data['updated_at'] = datetime.now(timezone.utc).isoformat()

    team_names_path = data_dir / 'team_names.json'
    team_name_history = load_json(team_names_path) if team_names_path.exists() else {}
    team_names.apply_team_names(
        data,
        team_name_history,
        season,
        data['current_week'],
    )

    # Apply the automated "name battle" changeover (Connor Bowl, etc.) so display
    # names reflect who currently holds each contested name. Done last, after all
    # teams/standings/weeks/transactions are populated.
    apply_name_battles(data, data_dir, web_dir, season)

    # meta.json's teams (this file becomes the historical season source when
    # the year is archived) are written once, from the final `data['teams']`,
    # by write_split_runtime_data() below - see the matching note above the
    # schedule write this mirrors.

    # Stamp point-in-time team avatars so a new logo applies from its upload week
    # forward and never rewrites past weeks. See apply_avatars / qpfl/avatars.py.
    apply_avatars(data, data_dir, season)

    write_split_runtime_data(data, web_dir, season)

    return data


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Export current season data')
    parser.add_argument('--season', '-s', type=int, default=2026, help='Season year')
    parser.add_argument('--data-dir', '-d', default='data', help='Data directory')
    parser.add_argument('--web-dir', '-w', default='web', help='Web directory')
    parser.add_argument('--output', '-o', default=None, help='Output path (default: web/data.json)')
    args = parser.parse_args()

    project_dir = Path(__file__).parent.parent
    data_dir = project_dir / args.data_dir
    web_dir = project_dir / args.web_dir
    output_path = Path(args.output) if args.output else web_dir / 'data.json'

    print(f'Exporting season {args.season}...')

    data = export_current_season(data_dir, web_dir, args.season)

    # Same no-op guard as write_split_runtime_data's write_json, for the same
    # reason: a run whose content genuinely didn't change must not still
    # produce a commit and a redeploy just because `updated_at` always
    # advances.
    existing = load_json(output_path) if output_path.exists() else None
    if _without_updated_at(existing) != _without_updated_at(data):
        with open(output_path, 'w') as f:
            json.dump(data, f, separators=(',', ':'))

    print(f'Exported to {output_path}')
    print(f'  Weeks: {len(data.get("weeks", []))}')
    print(f'  Standings: {len(data.get("standings", []))}')
    print(f'  Current week: {data.get("current_week")}')


if __name__ == '__main__':
    main()
