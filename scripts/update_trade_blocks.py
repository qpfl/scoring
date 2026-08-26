#!/usr/bin/env python3
"""Update trade blocks in both legacy and split frontend data."""

import json
from pathlib import Path


def main():
    project_dir = Path(__file__).parent.parent
    trade_blocks_path = project_dir / 'data' / 'trade_blocks.json'
    data_json_path = project_dir / 'web' / 'data.json'
    index_path = project_dir / 'web' / 'data' / 'index.json'

    # Load trade blocks
    if not trade_blocks_path.exists():
        print('No trade_blocks.json found')
        return

    with open(trade_blocks_path) as f:
        trade_blocks = json.load(f)

    # Load current data.json
    if not data_json_path.exists():
        print('No data.json found - run full export first')
        return

    with open(data_json_path) as f:
        data = json.load(f)

    # Check if trade_blocks have actually changed
    current_blocks = data.get('trade_blocks', {})
    live_path = None
    live_data = {}
    if index_path.exists():
        with open(index_path) as f:
            current_season = json.load(f).get('current_season')
        if current_season:
            live_path = project_dir / 'web' / 'data' / 'seasons' / str(current_season) / 'live.json'
            if live_path.exists():
                with open(live_path) as f:
                    live_data = json.load(f)

    if current_blocks == trade_blocks and live_data.get('trade_blocks') == trade_blocks:
        print('Trade blocks unchanged, no update needed')
        return

    # Update trade_blocks
    data['trade_blocks'] = trade_blocks

    # Write back
    with open(data_json_path, 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    if live_path:
        live_data['trade_blocks'] = trade_blocks
        live_path.parent.mkdir(parents=True, exist_ok=True)
        with open(live_path, 'w') as f:
            json.dump(live_data, f, separators=(',', ':'))

    print('Updated trade blocks in legacy and split web data')
    print(
        f'Teams with trade blocks: {[k for k, v in trade_blocks.items() if v.get("seeking") or v.get("trading_away") or v.get("players_available")]}'
    )


if __name__ == '__main__':
    main()
