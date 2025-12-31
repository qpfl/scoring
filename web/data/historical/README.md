# Historical Data - DO NOT MODIFY

This directory contains **immutable** historical season data exported from the official Excel files.

## ⚠️ NEVER MODIFY THESE FILES DIRECTLY

These files contain official scores, standings, and matchup data from completed seasons.
Any modifications will corrupt historical records.

## If you need to fix historical data:

1. **Update the source Excel file** in `previous_seasons/`
2. **Re-export** using: `python scripts/export_historical.py <year>`
3. **Fix the main data files** using: `python scripts/fix_historical_scores.py <year>`

## Files in this directory:

- `YYYY.json` - Raw export from Excel for season YYYY
- Used to verify and fix `web/data_YYYY.json` files

## Why this matters:

Previous issues with ad-hoc modifications to `data.json` files caused:
- Incorrect championship scores
- Wrong standings
- Data corruption in unrelated sections

This structure ensures historical data integrity by:
1. Keeping source Excel files as the authority
2. Using scripts to export/verify data
3. CI checks that block unauthorized modifications

