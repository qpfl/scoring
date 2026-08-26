import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HELPER = PROJECT_ROOT / 'scripts' / 'git_push_with_retry.sh'


def _fake_commands(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'git.log'
    sleeps = tmp_path / 'sleep.log'
    fake_git = bin_dir / 'git'
    fake_git.write_text(
        """#!/bin/sh
echo "$*" >> "$FAKE_GIT_LOG"
if [ "$1" = "pull" ] && [ "$FAKE_GIT_MODE" = "pull-fails" ]; then
    exit 1
fi
if [ "$1" = "push" ]; then
    count_file="$FAKE_GIT_STATE/push-count"
    count=0
    [ ! -f "$count_file" ] || count=$(cat "$count_file")
    count=$((count + 1))
    echo "$count" > "$count_file"
    if [ "$FAKE_GIT_MODE" = "always-fails" ]; then
        exit 1
    fi
    [ "$count" -ge "${FAKE_GIT_SUCCEED_ON:-1}" ] || exit 1
fi
exit 0
""",
        encoding='utf-8',
    )
    fake_git.chmod(0o755)
    fake_sleep = bin_dir / 'sleep'
    fake_sleep.write_text('#!/bin/sh\necho "$1" >> "$FAKE_SLEEP_LOG"\n', encoding='utf-8')
    fake_sleep.chmod(0o755)
    env = {
        **os.environ,
        'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
        'FAKE_GIT_LOG': str(log),
        'FAKE_GIT_STATE': str(tmp_path),
        'FAKE_SLEEP_LOG': str(sleeps),
    }
    return env, log, sleeps


def test_push_succeeds_on_third_attempt(tmp_path):
    env, log, sleeps = _fake_commands(tmp_path)
    env.update(FAKE_GIT_MODE='eventually-succeeds', FAKE_GIT_SUCCEED_ON='3')

    result = subprocess.run(
        ['bash', str(HELPER), 'upstream', 'release', '5'],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    commands = log.read_text(encoding='utf-8').splitlines()
    assert commands.count('pull --rebase upstream release') == 3
    assert commands.count('push upstream HEAD:release') == 3
    assert sleeps.read_text(encoding='utf-8').splitlines() == ['2', '4']


def test_exhausted_pushes_fail_without_a_final_sleep(tmp_path):
    env, log, sleeps = _fake_commands(tmp_path)
    env['FAKE_GIT_MODE'] = 'always-fails'

    result = subprocess.run(
        ['bash', str(HELPER), 'origin', 'main', '3'],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert log.read_text(encoding='utf-8').splitlines().count('push origin HEAD:main') == 3
    assert sleeps.read_text(encoding='utf-8').splitlines() == ['2', '4']


def test_pull_failure_stops_before_push(tmp_path):
    env, log, sleeps = _fake_commands(tmp_path)
    env['FAKE_GIT_MODE'] = 'pull-fails'

    result = subprocess.run(
        ['bash', str(HELPER), 'origin', 'main', '5'],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert log.read_text(encoding='utf-8').splitlines() == ['pull --rebase origin main']
    assert not sleeps.exists()


def test_workflows_use_the_shared_helper():
    workflows = PROJECT_ROOT / '.github' / 'workflows'
    targeted = (
        'score.yml',
        'season-transition.yml',
        'update-player-teams.yml',
        'expire-trades.yml',
        'lineup-reminders.yml',
        'trade_blocks.yml',
    )

    for name in targeted:
        source = (workflows / name).read_text(encoding='utf-8')
        assert 'scripts/git_push_with_retry.sh origin main 5' in source
        assert 'if git push; then break' not in source
