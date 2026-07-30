"""Structural validation of every file in `data/` against qpfl/schemas.py.

Run as a CLI (`uv run python -m qpfl.data_validation`) or call
`validate_data_dir()` directly. Wired into CI (`.github/workflows/test.yml`),
the post-write scoring job (`.github/workflows/score.yml`), and pre-commit.
"""

import json
import sys
from pathlib import Path

from pydantic import BaseModel, ValidationError

from qpfl import schemas
from qpfl.constants import DATA_DIR

# Relative path (under DATA_DIR) -> schema model for that file.
FILE_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    'rosters.json': schemas.RostersFile,
    'teams.json': schemas.TeamsFile,
    'pending_trades.json': schemas.PendingTradesFile,
    'transaction_log.json': schemas.TransactionLogFile,
    'draft_picks.json': schemas.DraftPicksFile,
    'drafts.json': schemas.DraftsFile,
    'fa_pool.json': schemas.FAPoolFile,
    'trade_blocks.json': schemas.TradeBlocksFile,
    'score_adjustments.json': schemas.ScoreAdjustmentsFile,
    'rule_proposals.json': schemas.RuleProposalsFile,
    'team_names.json': schemas.TeamNamesFile,
    'avatars.json': schemas.AvatarsFile,
    'draft_orders.json': schemas.DraftOrdersFile,
    'name_battles.json': schemas.NameBattlesFile,
    'league_config.json': schemas.LeagueConfig,
}


def _iter_lineup_files(data_dir: Path):
    lineups_dir = data_dir / 'lineups'
    if not lineups_dir.is_dir():
        return
    for season_dir in sorted(lineups_dir.iterdir()):
        if not season_dir.is_dir():
            continue
        yield from sorted(season_dir.glob('week_*.json'))


def validate_data_dir(data_dir: Path | str = DATA_DIR) -> list[str]:
    """Validate every known file under `data_dir`. Returns a list of error strings (empty if clean)."""
    data_dir = Path(data_dir)
    errors: list[str] = []

    for rel_path, model in FILE_SCHEMA_MAP.items():
        path = data_dir / rel_path
        if not path.exists():
            continue
        errors.extend(_validate_one(path, model))

    for lineup_path in _iter_lineup_files(data_dir):
        errors.extend(_validate_one(lineup_path, schemas.LineupWeekFile))

    return errors


def _validate_one(path: Path, model: type[BaseModel]) -> list[str]:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        return [f'{path}: invalid JSON: {e}']

    try:
        model.model_validate(raw)
    except ValidationError as e:
        return [f'{path}: schema validation failed:\n{e}']
    return []


def main() -> int:
    errors = validate_data_dir()
    if errors:
        print(f'✗ {len(errors)} data validation error(s):\n')
        for err in errors:
            print(err)
            print()
        return 1
    print(f'✓ All data files valid ({len(FILE_SCHEMA_MAP)} known files + lineups checked)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
