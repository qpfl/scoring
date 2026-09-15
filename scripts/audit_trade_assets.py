#!/usr/bin/env python3
"""
Audit how many trade pick assets fail to parse under the transactions-page
pick parser.

The transactions page (web/app.js: parsePickSlug / parsePickPhrase) resolves
draft-pick assets in trades to the player they turned into, and follows
re-trades across multiple hops. Structured 2026 trades use a canonical slug
("2026-R1-CWR"); the 70 legacy trades (2020-2025) are free-text `message`
blobs with inconsistent pick phrasing ("GSA 2027 2nd rounder", "3.03", ...).

This script mirrors that parsing logic in Python and prints every asset
string that fails to parse as a pick, grouped by season, so the free-text
`message` strings in transactions.json can be hand-edited into a parseable
form rather than silently producing a wrong trade verdict.

Keep the parsing rules (ORDINAL_ROUND_WORDS, the pick-slug regex, the
type-keyword rules) in sync with web/app.js's parsePickSlug/parsePickPhrase.

Usage:
    python scripts/audit_trade_assets.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TRANSACTIONS_PATH = REPO_ROOT / "web" / "data" / "shared" / "transactions.json"

ORDINAL_ROUND_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

PICK_SLUG_RE = re.compile(r"^(\d{4})-(?:([a-zA-Z]+(?:_[a-zA-Z]+)?)-)?R(\d+)-(.+)$")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
ORDINAL_DIGIT_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b", re.IGNORECASE)
ORDINAL_WORD_RE = re.compile(
    r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b"
)
OWNER_TOKEN_RE = re.compile(r"^([A-Za-z/.]+)\b")

# Heuristic for "this looks like it was meant to be a pick, but didn't parse"
# vs. "this is just a player name" — mirrors the guard in assetOutcome().
LOOKS_LIKE_PICK_RE = re.compile(r"\b(pick|taxi|round|rounder)\b", re.IGNORECASE)


def parse_pick_slug(text: str):
    match = PICK_SLUG_RE.match(text.strip())
    if not match:
        return None
    year_str, type_raw, round_str, owner_raw = match.groups()
    return {
        "year": int(year_str),
        "type": (type_raw or "offseason").lower(),
        "round": int(round_str),
        "owner": owner_raw.strip(),
        "raw": text,
    }


def parse_pick_phrase(text: str):
    text = text.strip()
    year_match = YEAR_RE.search(text)
    if not year_match:
        return None
    year = int(year_match.group(1))

    round_num = None
    ordinal_digit = ORDINAL_DIGIT_RE.search(text)
    if ordinal_digit:
        round_num = int(ordinal_digit.group(1))
    else:
        ordinal_word = ORDINAL_WORD_RE.search(text.lower())
        if ordinal_word:
            round_num = ORDINAL_ROUND_WORDS[ordinal_word.group(1)]
    if not round_num:
        return None

    lower = text.lower()
    has_waiver = bool(re.search(r"\bwaiver\b", lower))
    has_taxi = bool(re.search(r"\btaxi\b", lower))
    has_midseason = bool(re.search(r"\bmid[\s-]?season\b", lower))
    if has_waiver and has_taxi:
        pick_type = "waiver_taxi"
    elif has_midseason and has_taxi:
        pick_type = "midseason_taxi"
    elif has_taxi:
        pick_type = "offseason_taxi"
    elif has_waiver:
        pick_type = "waiver"
    elif has_midseason:
        pick_type = "midseason"
    else:
        pick_type = "offseason"

    owner_match = OWNER_TOKEN_RE.match(text)
    if not owner_match:
        return None
    owner = owner_match.group(1).strip()

    return {"year": year, "type": pick_type, "round": round_num, "owner": owner, "raw": text}


def resolve_pick_asset(item: str):
    return parse_pick_slug(item) or parse_pick_phrase(item)


def is_date(part: str) -> bool:
    return bool(re.match(r"^\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})$", part))


def looks_like_team_name(part: str) -> bool:
    if not part or len(part) > 30:
        return False
    if is_date(part):
        return False
    if re.match(r"^\d+\.\d+$", part):
        return False
    if re.search(r"\d+\.\d+", part):
        return False
    non_numeric_dot = re.sub(r"[0-9.]", "", part)
    if not non_numeric_dot:
        return False
    if re.search(r"\b(taxi|pick)\b", part, re.IGNORECASE):
        return False
    if re.search(r"\b(?:RB|WR|TE|QB|K|D/ST|DST)\b|202[0-9]|\b(?:round|1st|2nd|3rd|4th)\b|[()]", part, re.IGNORECASE):
        return False
    return len(part.split()) <= 3


def parse_old_trade_message(message: str):
    """Python port of parseOldTradeMessage in web/app.js — team name + item split only."""
    if not message or "|" not in message:
        return None
    parts = [p.strip() for p in message.split("|")]
    teams = []
    current_team = None
    in_corresponding_moves = False
    has_explicit_headers = any(
        re.match(r"^to\s+.+", p, re.IGNORECASE) or re.search(r"\s+gets?:?$", p, re.IGNORECASE)
        for p in parts
    )

    def explicit_team_name(part):
        if not re.match(r"^to\s+.+", part, re.IGNORECASE) and not re.search(r"\s+gets?:?$", part, re.IGNORECASE):
            return None
        cleaned = re.sub(r"^to\s+", "", part, flags=re.IGNORECASE)
        cleaned = re.sub(r":$", "", cleaned)
        cleaned = re.sub(r"\s+gets?$", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    for part in parts:
        if not part:
            continue
        if re.match(r"^(in )?corresponding( moves?)?:?$", part, re.IGNORECASE):
            in_corresponding_moves = True
            current_team = None
            continue
        if is_date(part) or re.match(r"^approximate week$", part, re.IGNORECASE):
            continue
        name = explicit_team_name(part)
        if name:
            current_team = {"name": name, "items": []}
            teams.append(current_team)
            in_corresponding_moves = False
            continue
        if in_corresponding_moves:
            continue
        if not has_explicit_headers and (current_team is None or looks_like_team_name(part)):
            if current_team is None or len(teams) < 2:
                current_team = {"name": part, "items": []}
                teams.append(current_team)
                continue
        if current_team is not None:
            current_team["items"].append(part)

    return teams


def iter_trade_items(tx: dict):
    """Yield every asset string that is a trade line item for this transaction."""
    is_new_trade = tx.get("type") == "trade" and tx.get("proposer") and tx.get("partner")
    if is_new_trade:
        for side in (tx.get("proposer_gives") or {}, tx.get("proposer_receives") or {}):
            for item in side.get("picks") or []:
                yield item
        return

    team = tx.get("team") or ""
    if "trade" not in team.lower():
        return
    message = tx.get("message") or ""
    teams = parse_old_trade_message(message)
    if not teams:
        return
    for side in teams:
        for item in side["items"]:
            yield item


def main():
    if not TRANSACTIONS_PATH.exists():
        print(f"Not found: {TRANSACTIONS_PATH}", file=sys.stderr)
        return 1

    payload = json.loads(TRANSACTIONS_PATH.read_text())
    transactions = payload.get("transactions", payload) if isinstance(payload, dict) else payload

    unparsed_by_season = defaultdict(list)
    total_trades = 0
    total_pick_like = 0

    for tx in transactions:
        is_trade = (tx.get("type") == "trade" and tx.get("proposer") and tx.get("partner")) or (
            "trade" in str(tx.get("team") or "").lower()
        )
        if not is_trade:
            continue
        total_trades += 1
        season = tx.get("season", "unknown")
        for item in iter_trade_items(tx):
            if not isinstance(item, str):
                continue
            if resolve_pick_asset(item):
                total_pick_like += 1
                continue
            if LOOKS_LIKE_PICK_RE.search(item) and re.search(r"\d", item):
                unparsed_by_season[season].append(item)

    print(f"Scanned {total_trades} trades, {total_pick_like} pick assets parsed cleanly.\n")

    if not unparsed_by_season:
        print("No unparsed pick-like assets found.")
        return 0

    total_unparsed = sum(len(v) for v in unparsed_by_season.values())
    print(f"{total_unparsed} unparsed pick-like asset string(s), by season:\n")
    for season in sorted(unparsed_by_season, key=lambda s: str(s)):
        items = unparsed_by_season[season]
        print(f"  {season} ({len(items)}):")
        for item in items:
            print(f"    - {item!r}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
