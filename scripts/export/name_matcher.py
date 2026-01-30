"""Player name matching and normalization."""

import json
import re
from pathlib import Path

_CANONICAL_NAMES: dict[str, str] = {}


def normalize_for_matching(name: str) -> str:
    """
    Normalize a name for fuzzy matching.

    Removes common suffixes (Jr., Sr., II, III, etc.) and converts to lowercase.

    Args:
        name: Player name to normalize

    Returns:
        Normalized name for matching
    """
    normalized = re.sub(r'\s+(Sr\.?|Jr\.?|II|III|IV|V)$', '', name.strip(), flags=re.IGNORECASE)
    return normalized.lower()


def load_canonical_names(rosters_path: Path) -> dict[str, str]:
    """
    Load canonical player names from rosters.json.

    Builds a mapping from normalized names to canonical names
    for fuzzy matching.

    Args:
        rosters_path: Path to rosters.json file

    Returns:
        Dict mapping normalized name -> canonical name
    """
    global _CANONICAL_NAMES
    if _CANONICAL_NAMES:
        return _CANONICAL_NAMES

    if not rosters_path.exists():
        return {}

    try:
        with open(rosters_path) as f:
            rosters = json.load(f)

        for _team_abbrev, players in rosters.items():
            for player in players:
                canonical_name = player.get('name', '')
                if canonical_name:
                    normalized = normalize_for_matching(canonical_name)
                    _CANONICAL_NAMES[normalized] = canonical_name
    except Exception:
        pass

    return _CANONICAL_NAMES


def match_canonical_name(name: str, rosters_path: Path = None) -> str:
    """
    Match a player name to its canonical version from rosters.json.

    Handles variations like:
    - Suffixes (Jr., Sr., II, III)
    - Initials vs full first names (J. Cook -> James Cook III)
    - Case differences

    Args:
        name: Player name to match
        rosters_path: Path to rosters.json (optional, auto-detected if None)

    Returns:
        Canonical name if match found, original name otherwise
    """
    if rosters_path is None:
        script_dir = Path(__file__).parent.parent.parent
        rosters_path = script_dir / 'data' / 'rosters.json'

    canonical_names = load_canonical_names(rosters_path)
    if not canonical_names:
        return name

    normalized = normalize_for_matching(name)

    # Try exact match on normalized name
    if normalized in canonical_names:
        return canonical_names[normalized]

    # Try matching by last name if first name/initial matches
    name_parts = normalized.split()
    if len(name_parts) >= 2:
        first_part = name_parts[0].rstrip('.')
        last_name = name_parts[-1]

        for canonical_normalized, canonical_name in canonical_names.items():
            canonical_parts = canonical_normalized.split()
            if len(canonical_parts) >= 2:
                canonical_first = canonical_parts[0]
                canonical_last = canonical_parts[-1]

                # Check if last names match and first names/initials are compatible
                if canonical_last == last_name and (
                    (len(first_part) == 1 and canonical_first.startswith(first_part))
                    or canonical_first.startswith(first_part)
                ):
                    return canonical_name

    return name
