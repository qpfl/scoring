# Team avatars

Square PNG logos for each team, named by the team's abbreviation slug
(non-alphanumeric chars replaced with `_`, e.g. `S/T` → `S_T.png`).

These are uploaded by managers from **Manage Rosters → Set Lineup → Team Avatar**,
which commits the image here via `api/team-avatar.py`. The frontend (`teamAvatar()`
in `web/app.js`) requests `images/avatars/{slug}.png` and falls back to a colored
initials circle when the file is absent, so a team without an uploaded avatar still
renders cleanly.

Keep `avatar_slug()` (Python) and `avatarSlug()` (JS) in sync so filenames match.
