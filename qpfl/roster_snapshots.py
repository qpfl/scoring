"""Frozen per-week rosters, so later roster moves can't rewrite a scored week.

The transaction API (api/roster_timing.py) freezes a started week's roster the
first time a roster move lands during it; a move whose players had already
played only changes ``rosters.json``, so it takes effect the following week.
Scoring a week reads its frozen roster when there is one. Once a week's games
are all final and nothing froze it, the scorer freezes it from
``rosters.json`` (which no move has touched since kickoff), so a later
``--force`` rescore still sees the roster the week was played with.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def roster_snapshot_path(data_dir: str | Path, season: int, week: int) -> Path:
    return Path(data_dir) / 'roster_snapshots' / str(season) / f'week_{week}.json'


def unwrap_roster_snapshot(content: Any) -> Any:
    """Return the rosters inside a snapshot file, or the content unchanged if it
    is a plain rosters.json mapping."""
    if (
        isinstance(content, dict)
        and isinstance(content.get('rosters'), dict)
        and isinstance(content.get('week'), int)
    ):
        return content['rosters']
    return content


def write_roster_snapshot(
    path: str | Path,
    season: int,
    week: int,
    rosters: dict[str, list[dict[str, Any]]],
    frozen_at: str,
) -> bool:
    """Freeze ``rosters`` for a week unless it is already frozen. Returns True if written."""
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'season': season, 'week': week, 'frozen_at': frozen_at, 'rosters': rosters}
    # Compact, like the API's Git-blob writes, so either writer produces the same bytes.
    path.write_text(json.dumps(payload, separators=(',', ':')))
    return True
