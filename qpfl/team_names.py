"""Season-aware team-name history helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

LEGACY_TEAM_NAME_SEASON = 2025


def normalize_team_name_history(
    raw: Any, *, default_season: int = LEGACY_TEAM_NAME_SEASON
) -> dict[str, list[dict[str, Any]]]:
    """Convert legacy string and seasonless entries to the canonical shape."""
    if not isinstance(raw, dict):
        return {}
    source = raw.get('team_names', raw)
    if not isinstance(source, dict):
        return {}

    normalized: dict[str, list[dict[str, Any]]] = {}
    for team, value in source.items():
        entries = [value] if isinstance(value, (str, dict)) else value
        if not isinstance(entries, list):
            continue
        team_entries = []
        for entry in entries:
            if isinstance(entry, str):
                entry = {
                    'season': default_season,
                    'effective_week': 0,
                    'name': entry,
                }
            if not isinstance(entry, dict):
                continue
            candidate = deepcopy(entry)
            candidate.setdefault('season', default_season)
            candidate.setdefault('effective_week', 0)
            team_entries.append(candidate)
        normalized[str(team)] = sorted(
            team_entries,
            key=lambda entry: (
                entry.get('season', default_season),
                entry.get('effective_week', 0),
            ),
        )
    return normalized


def resolve_team_name(
    history: dict[str, Any],
    abbrev: str,
    season: int,
    week: int,
    default_name: str,
    *,
    legacy_season: int = LEGACY_TEAM_NAME_SEASON,
) -> str:
    """Resolve the newest name effective on or before ``(season, week)``."""
    normalized = normalize_team_name_history(history, default_season=legacy_season)
    eligible = [
        entry
        for entry in normalized.get(abbrev, [])
        if (entry.get('season'), entry.get('effective_week')) <= (season, week)
        and isinstance(entry.get('name'), str)
    ]
    if not eligible:
        return default_name
    latest = max(eligible, key=lambda entry: (entry['season'], entry['effective_week']))
    name = latest.get('name')
    return name if isinstance(name, str) else default_name


def apply_team_names(
    data: dict[str, Any],
    history: dict[str, Any],
    season: int,
    current_week: int,
) -> None:
    """Apply current and point-in-time names to an exported payload in place."""
    base_names = {
        team.get('abbrev'): team.get('name', team.get('abbrev', ''))
        for team in data.get('teams', []) or []
        if team.get('abbrev')
    }

    def name_at(team: dict[str, Any], week: int) -> None:
        abbrev = team.get('abbrev')
        if not abbrev:
            return
        default = base_names.get(abbrev, team.get('name', abbrev))
        name = resolve_team_name(history, abbrev, season, week, default)
        team['name'] = name
        if 'team_name' in team:
            team['team_name'] = name

    for team in data.get('teams', []) or []:
        name_at(team, current_week)
    standings = data.get('standings', []) or []
    if isinstance(standings, dict):
        standings = standings.get('standings', [])
    for team in standings:
        name_at(team, current_week)

    for week_data in data.get('weeks', []) or []:
        week = week_data.get('week')
        if not isinstance(week, int):
            continue
        for team in week_data.get('teams', []) or []:
            name_at(team, week)
        for matchup in week_data.get('matchups', []) or []:
            for side in ('team1', 'team2'):
                team = matchup.get(side)
                if isinstance(team, dict):
                    name_at(team, week)
