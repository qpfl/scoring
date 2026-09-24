#!/usr/bin/env python3
"""Decide whether nflverse has published data newer than our last scoring run.

nflverse offers no webhook or dispatch we can subscribe to, so "score when the
feed updates" has to be a poll. The cheap signal is the GitHub release asset's
updated_at: nflverse-data re-uploads the season's parquet every time it
rebuilds, and scoring reads exactly those assets. Comparing that against when
the last successful score.yml run started answers "is there anything we have
not already scored?" without downloading a byte of stats or keeping any extra
state - GitHub's run history records when we last scored.

Prints 'true' or 'false' and, under Actions, writes updated=<value> to
GITHUB_OUTPUT so a workflow can gate a dispatch on it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_API_ROOT = 'https://api.github.com/repos/nflverse/nflverse-data/releases/tags'

# The releases scoring actually reads: skill players and kickers come from the
# player stats, D/ST and OL from the team stats, and sacks and turnover
# touchdowns from play-by-play. They are built by one pipeline and land within
# a couple of minutes of each other, so the newest of the three is the moment
# the week's data became complete.
WATCHED_ASSETS: tuple[tuple[str, str], ...] = (
    ('stats_player', 'stats_player_week_{season}.parquet'),
    ('stats_team', 'stats_team_week_{season}.parquet'),
    ('pbp', 'play_by_play_{season}.parquet'),
)


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 stamp to an aware UTC datetime, or None if unusable.

    GitHub spells UTC as a trailing Z; our own scored_at carries an explicit
    +00:00 offset and microseconds. Both have to end up comparable.
    """
    if not value:
        return None
    text = str(value).strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_scored_at(weeks_dir: Path) -> datetime | None:
    """Newest scored_at across the season's week files.

    The last time the autoscorer wrote anything. Only a fallback for when the
    run history can't be read: a rescore whose output didn't change leaves
    scored_at alone. A missing or unreadable file is skipped rather than
    fatal - one bad week should not wedge the poll.
    """
    if not weeks_dir.is_dir():
        return None
    stamps = []
    for path in sorted(weeks_dir.glob('week_*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        stamp = parse_timestamp(data.get('scored_at'))
        if stamp is not None:
            stamps.append(stamp)
    return max(stamps, default=None)


def asset_updated_at(release: dict, asset_name: str) -> datetime | None:
    """updated_at of one named asset in a release payload."""
    for asset in release.get('assets', []) or []:
        if isinstance(asset, dict) and asset.get('name') == asset_name:
            return parse_timestamp(asset.get('updated_at'))
    return None


def feed_updated_at(releases: dict[str, dict], season: int) -> datetime | None:
    """Newest updated_at across every watched asset."""
    stamps = []
    for tag, template in WATCHED_ASSETS:
        release = releases.get(tag)
        if not release:
            continue
        stamp = asset_updated_at(release, template.format(season=season))
        if stamp is not None:
            stamps.append(stamp)
    return max(stamps, default=None)


def should_rescore(feed: datetime | None, scored: datetime | None) -> bool:
    """Whether the feed has moved since we last scored.

    Unknowns fail toward scoring: if we cannot read the feed's timestamp the
    caller has already failed for other reasons, and if we have never scored
    there is by definition something to do. A stale site is the outcome worth
    avoiding; a redundant run costs nothing and commits nothing.
    """
    if feed is None:
        return True
    if scored is None:
        return True
    return feed > scored


def last_successful_score_run(repository: str | None, token: str | None) -> dict | None:
    """The most recent successful score.yml run, or None if it can't be read.

    Every successful run scores (push runs included), so a run that *started*
    after the feed's last update has already consumed it. Reading the run
    history rather than our own week files matters because scoring skips
    rewriting a week whose content didn't change, so scored_at stops moving
    on quiet days even while every run succeeds.
    """
    if not repository:
        return None
    request = urllib.request.Request(
        f'https://api.github.com/repos/{repository}/actions/workflows/score.yml/runs'
        '?status=success&per_page=1',
        headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'qpfl-scoring-nflverse-watch',
            **({'Authorization': f'Bearer {token}'} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            runs = json.load(response).get('workflow_runs') or []
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, AttributeError) as err:
        print(f'Could not read score.yml run history: {err}', file=sys.stderr)
        return None
    return runs[0] if runs and isinstance(runs[0], dict) else None


def fetch_release(tag: str, token: str | None = None) -> dict:
    """Fetch one nflverse-data release payload."""
    request = urllib.request.Request(
        f'{_API_ROOT}/{tag}',
        headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'qpfl-scoring-nflverse-watch',
            **({'Authorization': f'Bearer {token}'} if token else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_releases(token: str | None = None) -> dict[str, dict]:
    """Fetch every watched release, skipping any that error out."""
    releases: dict[str, dict] = {}
    for tag, _template in WATCHED_ASSETS:
        try:
            releases[tag] = fetch_release(tag, token)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            print(f'Could not read nflverse release {tag}: {err}', file=sys.stderr)
    return releases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument(
        '--weeks-dir',
        type=Path,
        default=None,
        help='Defaults to web/data/seasons/<season>/weeks',
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    weeks_dir = (
        args.weeks_dir or project_root / 'web' / 'data' / 'seasons' / str(args.season) / 'weeks'
    )

    token = os.environ.get('GITHUB_TOKEN')
    releases = fetch_releases(token)
    feed = feed_updated_at(releases, args.season)
    last_run = last_successful_score_run(os.environ.get('GITHUB_REPOSITORY'), token)
    last_run_started = parse_timestamp(last_run.get('run_started_at')) if last_run else None
    scored = last_run_started or latest_scored_at(weeks_dir)
    updated = should_rescore(feed, scored)

    source = 'last successful score run started' if last_run_started else 'last scored_at'
    print(f'nflverse feed updated_at: {feed.isoformat() if feed else "unknown"}')
    print(f'{source}: {scored.isoformat() if scored else "never"}')
    print(f'rescore needed:           {updated}')

    output_path = os.environ.get('GITHUB_OUTPUT')
    if output_path:
        with open(output_path, 'a', encoding='utf-8') as handle:
            handle.write(f'updated={str(updated).lower()}\n')


if __name__ == '__main__':
    main()
