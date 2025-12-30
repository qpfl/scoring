#!/usr/bin/env python3
"""
Lightweight script to update only trade_blocks in data.json.
This avoids running the full export when only trade blocks have changed.
"""

import json
from pathlib import Path


def main():
    project_dir = Path(__file__).parent.parent
    trade_blocks_path = project_dir / "data" / "trade_blocks.json"
    data_json_path = project_dir / "web" / "data.json"
    
    # Load trade blocks
    if not trade_blocks_path.exists():
        print("No trade_blocks.json found")
        return
    
    with open(trade_blocks_path) as f:
        trade_blocks = json.load(f)
    
    # Load current data.json
    if not data_json_path.exists():
        print("No data.json found - run full export first")
        return
    
    with open(data_json_path) as f:
        data = json.load(f)
    
    # Check if trade_blocks have actually changed
    current_blocks = data.get("trade_blocks", {})
    if current_blocks == trade_blocks:
        print("Trade blocks unchanged, no update needed")
        return
    
    # Update trade_blocks
    data["trade_blocks"] = trade_blocks
    
    # Write back
    with open(data_json_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"Updated trade_blocks in data.json")
    print(f"Teams with trade blocks: {[k for k, v in trade_blocks.items() if v.get('seeking') or v.get('trading_away') or v.get('players_available')]}")


if __name__ == "__main__":
    main()

