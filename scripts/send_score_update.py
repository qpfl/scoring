#!/usr/bin/env python3
"""Email the league a score update as each slate of the week finishes scoring.

Three sends per week, each at most once:

  thursday  the Thursday-night slate's scores are in
  sunday    the Sunday afternoon slate's scores are in
  final     every game of the week is scored - includes updated standings

The trigger is the slate, not the clock. The scorer runs many times a day (six
crons plus a dispatch from nflverse-watch whenever the feed publishes), and
"scores changed" is true on most of those runs: a game goes final the moment the
clock hits zero, but nflverse publishes its stats some minutes later, so a
slate's totals climb across several runs before they settle. Emailing on any
change would mean five or six partial-score emails a week, the first of them
showing zeros for players who had in fact just played.

So a slot goes out on the single run where its slate becomes both final and
fully published, and `data/score_notifications.json` records the send so the
runs that follow stay quiet.
"""

import argparse
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.email_delivery import (  # noqa: E402
    all_recipients,
    load_json,
    parse_now,
    send_email,
    write_state,
)

EASTERN = ZoneInfo('America/New_York')

# Slots in the order they go out; a later send supersedes any earlier one that
# never went (a week with no Thursday game, a lost state file).
SLOT_ORDER = ('thursday', 'sunday', 'final')

SLOT_LABELS = {
    'thursday': 'Thursday night scores',
    'sunday': 'Sunday scores',
    'final': 'Final scores & standings',
}

# Sunday night football belongs to the 'monday' slate: it kicks off hours after
# the afternoon slate has settled, so waiting for it would push the Sunday
# email into the early hours of Monday morning. It lands in the final email
# alongside MNF instead.
SUNDAY_EVENING_HOUR = 18

# Only report on a week whose games are recent. Without this a lost state file
# would email every completed week of the season in turn.
STALENESS_LIMIT = timedelta(days=4)

RULE = '=============================='


def eastern_stamp(now: datetime) -> str:
    return now.astimezone(EASTERN).strftime('%b %d, %Y at %-I:%M %p ET')


def _kickoff(entry: Mapping) -> datetime | None:
    value = entry.get('kickoff')
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(EASTERN)
    except ValueError:
        return None


def slate_of(entry: Mapping) -> str | None:
    """Which slate a player's game belongs to, or None when he has no game."""
    kickoff = _kickoff(entry)
    if kickoff is None:
        return None
    weekday = kickoff.weekday()  # Monday == 0
    if weekday in (2, 3):  # Wednesday and Thursday openers
        return 'thursday'
    if weekday in (4, 5) or (weekday == 6 and kickoff.hour < SUNDAY_EVENING_HOUR):
        return 'sunday'
    return 'monday'  # Sunday night, Monday night, and the rare Tuesday makeup


def _all_entries(week_data: Mapping) -> Iterable[Mapping]:
    for team in week_data.get('teams', []):
        yield from team.get('roster', [])
        yield from team.get('taxi_squad', [])


def published_nfl_teams(week_data: Mapping) -> set[str]:
    """NFL teams whose stats have actually landed in the feed.

    Mirrors ``_teams_with_published_stats`` in qpfl/projections.py: a matched
    stat row anywhere on an NFL team means the feed has caught up with that
    team's game. Head coaches are excluded because they score off the schedule
    result, so they match as soon as the game ends and before any stats exist.
    """
    return {
        entry['nfl_team']
        for entry in _all_entries(week_data)
        if entry.get('found') and entry.get('position') != 'HC' and entry.get('nfl_team')
    }


def _awaiting_stats(entry: Mapping, published: set[str]) -> bool:
    """Whether a final game's stats have yet to reach the feed for this player.

    A player who was ruled out or is on bye has a real, settled zero, and a
    matched player obviously has his stats, so neither is pending.
    """
    if entry.get('found') or entry.get('unavailable_reason') or entry.get('position') == 'HC':
        return False
    return entry.get('nfl_team') not in published


def slate_progress(week_data: Mapping) -> tuple[set[str], set[str]]:
    """Return (slates with starters in them, slates whose scores are all in)."""
    published = published_nfl_teams(week_data)
    started: set[str] = set()
    pending: set[str] = set()
    for team in week_data.get('teams', []):
        for entry in team.get('roster', []):
            if not entry.get('starter'):
                continue
            slate = slate_of(entry)
            if slate is None:  # bye week - nothing to wait for
                continue
            started.add(slate)
            if not entry.get('game_final') or _awaiting_stats(entry, published):
                pending.add(slate)
    return started, started - pending


def ready_slot(week_data: Mapping, already_sent: Iterable[str]) -> str | None:
    """The furthest slot whose scores have landed and which has not been emailed."""
    started, complete = slate_progress(week_data)
    sent = set(already_sent)
    ready = [slot for slot in ('thursday', 'sunday') if slot in complete]
    # The final email needs the whole week: every game played (games_final, off
    # the schedule) and every stat line in (nothing left pending).
    if week_data.get('games_final') and started == complete:
        ready.append('final')
    unsent = [slot for slot in ready if slot not in sent]
    return max(unsent, key=SLOT_ORDER.index) if unsent else None


def latest_kickoff(week_data: Mapping) -> datetime | None:
    kickoffs = [kickoff for kickoff in map(_kickoff, _all_entries(week_data)) if kickoff]
    return max(kickoffs) if kickoffs else None


def load_week_files(weeks_dir: Path) -> dict[int, dict]:
    weeks: dict[int, dict] = {}
    if not weeks_dir.is_dir():
        return weeks
    for path in weeks_dir.glob('week_*.json'):
        try:
            week = int(path.stem.split('_')[1])
        except (IndexError, ValueError):
            continue
        data = load_json(path)
        if isinstance(data, dict):
            weeks[week] = data
    return weeks


def pending_send(
    weeks: Mapping[int, dict],
    state_for_season: Mapping[str, Mapping],
    now: datetime,
    only_week: int | None = None,
    only_slot: str | None = None,
) -> tuple[int, str] | None:
    """Find the newest week with an email due, newest first.

    Checking the week before it too matters on Monday and Tuesday: the scorer
    has usually moved on to the new week's file by the time the old week's last
    game is published, and that week still owes the league its final email.
    """
    scored = sorted(week for week, data in weeks.items() if data.get('has_scores'))
    for week in reversed(scored[-2:]):
        if only_week is not None and week != only_week:
            continue
        last_kickoff = latest_kickoff(weeks[week])
        if last_kickoff and now - last_kickoff > STALENESS_LIMIT:
            continue
        slot = ready_slot(weeks[week], state_for_season.get(str(week), {}))
        if slot and (only_slot is None or slot == only_slot):
            return week, slot
    return None


def _score(team: Mapping) -> float:
    return float(team.get('total_score') or 0.0)


def _team_label(team: Mapping, width: int | None = None) -> str:
    """Render "Name (ABC)", trimming the name so team names of any length align."""
    abbrev = team.get('abbrev', '?')
    name = str(team.get('name', '?'))
    if width is not None:
        room = width - len(abbrev) - 3
        if len(name) > room:
            name = name[: max(room - 1, 1)].rstrip() + '…'
    return f'{name} ({abbrev})'


def format_matchups(matchups: Sequence[Mapping], is_final: bool) -> list[str]:
    lines = [RULE, 'FINAL SCORES' if is_final else 'SCOREBOARD', RULE, '']
    for matchup in matchups:
        teams = [matchup.get('team1') or {}, matchup.get('team2') or {}]
        leader = max(teams, key=_score)
        tied = _score(teams[0]) == _score(teams[1])
        for team in teams:
            mark = ''
            if not tied and team is leader:
                mark = '  WINNER' if is_final else '  (leading)'
            lines.append(f'  {_team_label(team, 46):<48}{_score(team):>7.1f}{mark}')
        if tied:
            lines.append('  (tied)')
        if not is_final:
            remaining = [
                f'{team.get("abbrev", "?")} {team.get("starters_remaining")}'
                for team in teams
                if team.get('starters_remaining')
            ]
            if remaining:
                lines.append(f'  starters yet to play: {", ".join(remaining)}')
        lines.append('')
    return lines


def format_top_performers(teams: Sequence[Mapping], limit: int = 5) -> list[str]:
    performers = [
        (float(entry.get('score') or 0.0), entry, team)
        for team in teams
        for entry in team.get('roster', [])
        if entry.get('starter')
    ]
    if not performers:
        return []
    performers.sort(key=lambda item: item[0], reverse=True)
    lines = [RULE, f'TOP {limit} STARTERS', RULE, '']
    for score, entry, team in performers[:limit]:
        position = entry.get('position', '')
        nfl_team = entry.get('nfl_team', '')
        lines.append(
            f'  {score:>6.1f}  {position} {entry.get("name", "?")} '
            f'({nfl_team}) - {team.get("abbrev", "?")}'
        )
    lines.append('')
    return lines


def format_standings(standings: Sequence[Mapping]) -> list[str]:
    if not standings:
        return []
    lines = [
        RULE,
        'STANDINGS',
        RULE,
        '',
        f'  {"#":<3}{"Team":<40}{"W-L-T":>8}{"Rank Pts":>10}{"PF":>9}{"PA":>9}',
        f'  {"-" * 79}',
    ]
    for team in sorted(standings, key=lambda team: team.get('seed') or 99):
        record = f'{team.get("wins", 0)}-{team.get("losses", 0)}-{team.get("ties", 0)}'
        lines.append(
            f'  {team.get("seed", "?"):<3}{_team_label(team, 38):<40}{record:>8}'
            f'{float(team.get("rank_points") or 0.0):>10.1f}'
            f'{float(team.get("points_for") or 0.0):>9.1f}'
            f'{float(team.get("points_against") or 0.0):>9.1f}'
        )
    lines.append('')
    return lines


def build_body(
    week: int,
    slot: str,
    week_data: Mapping,
    standings: Sequence[Mapping],
    now: datetime,
    site_url: str,
) -> str:
    is_final = slot == 'final'
    teams = week_data.get('teams', [])
    lines = [f'QPFL Week {week} - {SLOT_LABELS[slot]}', eastern_stamp(now), '']
    lines += format_matchups(week_data.get('matchups', []), is_final)
    lines += format_top_performers(teams)
    if is_final:
        lines += format_standings(standings)
    else:
        lines.append('Scores update as games finish - check the site for live totals.')
        lines.append('')
    lines.append(f'Full scoreboard: {site_url}')
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int)
    parser.add_argument('--week', type=int, help='Report on this week instead of auto-detecting')
    parser.add_argument('--slot', choices=sorted(SLOT_LABELS), help='Override the detected slot')
    parser.add_argument('--now', help='Override the current time with an ISO 8601 timestamp')
    parser.add_argument('--force', action='store_true', help='Resend even if already sent')
    parser.add_argument('--dry-run', action='store_true', help='Print the email instead of sending')
    parser.add_argument('--root', type=Path, default=_PROJECT_ROOT)
    args = parser.parse_args()

    now = parse_now(args.now)
    config = load_json(args.root / 'data' / 'league_config.json', {}) or {}
    season = args.season or int(config['current_season'])
    season_dir = args.root / 'web' / 'data' / 'seasons' / str(season)
    weeks = load_week_files(season_dir / 'weeks')

    state_path = args.root / 'data' / 'score_notifications.json'
    state = load_json(state_path, {'sent': {}}) or {'sent': {}}
    sent_by_week = state.setdefault('sent', {}).setdefault(str(season), {})

    already_sent: Mapping[str, Mapping] = {} if args.force else sent_by_week
    if args.week and args.slot:
        due: tuple[int, str] | None = (args.week, args.slot)
    else:
        due = pending_send(weeks, already_sent, now, only_week=args.week, only_slot=args.slot)

    if not due:
        print('No slate has finished scoring that has not already been emailed')
        return 0
    week, slot = due
    if week not in weeks:
        print(f'No {season} week {week} score file exists')
        return 0

    week_data = weeks[week]
    standings = (load_json(season_dir / 'standings.json', {}) or {}).get('standings', [])
    site_url = os.environ.get('QPFL_SITE_URL', 'https://qpfl-scoring.vercel.app/')
    subject = f'QPFL Week {week}: {SLOT_LABELS[slot]}'
    body = build_body(week, slot, week_data, standings, now, site_url)

    if args.dry_run:
        print(f'Subject: {subject}\nTo: {", ".join(all_recipients()) or "(nobody configured)"}\n')
        print(body)
        return 0

    if not send_email(subject, body, all_recipients()):
        return 1

    # Anything earlier than this slot is superseded: the email just sent already
    # contains those scores, so it must not go out afterwards as its own update.
    sent_for_week = sent_by_week.setdefault(str(week), {})
    for superseded in SLOT_ORDER[: SLOT_ORDER.index(slot) + 1]:
        sent_for_week.setdefault(superseded, now.isoformat())
    sent_for_week[slot] = now.isoformat()
    write_state(state_path, state)
    print(f'Sent Week {week} {slot} score update')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
