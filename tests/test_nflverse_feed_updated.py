import json

from scripts import nflverse_feed_updated as watch


def _release(name: str, updated_at: str | None) -> dict:
    return {'assets': [{'name': name, 'updated_at': updated_at}]}


def _releases(season: int, stamps: dict[str, str]) -> dict[str, dict]:
    return {
        tag: _release(template.format(season=season), stamps[tag])
        for tag, template in watch.WATCHED_ASSETS
        if tag in stamps
    }


def test_parse_timestamp_reconciles_github_z_with_our_offset_form():
    """GitHub writes Z, our week files write +00:00 with microseconds."""
    github = watch.parse_timestamp('2026-09-14T04:24:41Z')
    ours = watch.parse_timestamp('2026-09-14T04:33:32.217579+00:00')
    assert github is not None and ours is not None
    assert github < ours


def test_parse_timestamp_rejects_unusable_values():
    assert watch.parse_timestamp(None) is None
    assert watch.parse_timestamp('') is None
    assert watch.parse_timestamp('not a timestamp') is None


def test_feed_updated_at_takes_the_newest_watched_asset():
    releases = _releases(
        2026,
        {
            'stats_player': '2026-09-14T04:24:41Z',
            'stats_team': '2026-09-14T04:24:43Z',
            'pbp': '2026-09-14T04:23:14Z',
        },
    )
    newest = watch.feed_updated_at(releases, 2026)
    assert newest == watch.parse_timestamp('2026-09-14T04:24:43Z')


def test_feed_updated_at_ignores_other_seasons_assets():
    """The release holds every season; only the current one's asset counts."""
    releases = {'stats_player': _release('stats_player_week_2025.parquet', '2026-09-14T04:24:41Z')}
    assert watch.feed_updated_at(releases, 2026) is None


def test_latest_scored_at_takes_the_newest_week_file(tmp_path):
    for week, stamp in ((1, '2026-09-14T04:33:32.217579+00:00'), (2, '2026-09-09T12:00:00+00:00')):
        (tmp_path / f'week_{week}.json').write_text(json.dumps({'week': week, 'scored_at': stamp}))
    assert watch.latest_scored_at(tmp_path) == watch.parse_timestamp(
        '2026-09-14T04:33:32.217579+00:00'
    )


def test_latest_scored_at_skips_unreadable_weeks_instead_of_failing(tmp_path):
    """One corrupt week file must not wedge the poll for the whole season."""
    (tmp_path / 'week_1.json').write_text('{ not json')
    (tmp_path / 'week_2.json').write_text(json.dumps({'scored_at': '2026-09-09T12:00:00+00:00'}))
    assert watch.latest_scored_at(tmp_path) == watch.parse_timestamp('2026-09-09T12:00:00+00:00')


def test_latest_scored_at_returns_none_for_a_missing_directory(tmp_path):
    assert watch.latest_scored_at(tmp_path / 'nope') is None


def test_rescore_when_the_feed_is_newer_than_our_last_run():
    """The case that motivated this: stats landed after we scored."""
    assert watch.should_rescore(
        watch.parse_timestamp('2026-09-14T04:24:43Z'),
        watch.parse_timestamp('2026-09-14T00:17:27+00:00'),
    )


def test_no_rescore_when_we_already_scored_the_current_feed():
    assert not watch.should_rescore(
        watch.parse_timestamp('2026-09-14T04:24:43Z'),
        watch.parse_timestamp('2026-09-14T04:33:32+00:00'),
    )


def test_unknowns_fail_toward_scoring():
    """A stale site is worse than a redundant run, which commits nothing."""
    assert watch.should_rescore(None, watch.parse_timestamp('2026-09-14T04:33:32+00:00'))
    assert watch.should_rescore(watch.parse_timestamp('2026-09-14T04:24:43Z'), None)
    assert watch.should_rescore(None, None)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self, *args):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_last_successful_score_run_skips_unsuccessful_runs_without_status_filter(monkeypatch):
    """?status=success served a run two weeks stale, so we filter client-side."""
    seen_urls = []
    runs = [
        {'id': 3, 'status': 'in_progress', 'conclusion': None},
        {'id': 2, 'status': 'completed', 'conclusion': 'failure'},
        {'id': 1, 'status': 'completed', 'conclusion': 'success'},
    ]

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        return _FakeResponse({'workflow_runs': runs})

    monkeypatch.setattr(watch.urllib.request, 'urlopen', fake_urlopen)
    assert watch.last_successful_score_run('qpfl/scoring', None)['id'] == 1
    assert 'status=' not in seen_urls[0]


def test_last_successful_score_run_none_when_no_recent_success(monkeypatch):
    monkeypatch.setattr(
        watch.urllib.request,
        'urlopen',
        lambda request, timeout: _FakeResponse(
            {'workflow_runs': [{'id': 1, 'conclusion': 'failure'}]}
        ),
    )
    assert watch.last_successful_score_run('qpfl/scoring', None) is None
