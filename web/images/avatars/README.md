# Team avatars

Square PNG logos for each team, **versioned per `(season, week)`** so a new upload
takes effect from its week forward and never rewrites past weeks. Files live under
a per-team folder named by the team's abbreviation slug (non-alphanumeric chars
replaced with `_`, e.g. `S/T` → `S_T`):

```
S_T/2026-w3.png      # uploaded while season 2026, week 3 was current
GSA/2026-w1.png
```

Managers upload from **Manage Rosters → Set Lineup → Team Avatar**, which commits
the image here via `api/team-avatar.py` along with an entry in
[`data/avatars.json`](../../../data/avatars.json):

```json
{ "GSA": [ {"season": 2026, "week": 1, "file": "GSA/2026-w1.png"} ] }
```

At export, `apply_avatars()` in `scripts/export_current.py` (via `qpfl/avatars.py`)
resolves the avatar in effect for each surface and stamps an `avatar` URL onto every
team object: current-state surfaces (teams, standings) get the latest version;
per-week matchups get the version in effect as of that week. The frontend
(`teamAvatar()` in `web/app.js`) renders that stamped URL and falls back to a colored
initials circle when a team has no avatar yet, so teams without an uploaded avatar
still render cleanly.

Keep `avatar_slug()` (Python, in `api/team-avatar.py`) in sync with the `file` paths
recorded in the manifest.
