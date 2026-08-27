from copy import deepcopy

from api import github_store


def _install_store(monkeypatch, state):
    heads = iter(['head-1', 'head-2', 'head-3'])
    updates = []
    monkeypatch.setattr(github_store, '_get_head', lambda: next(heads))
    monkeypatch.setattr(
        github_store,
        '_read_json_at',
        lambda path, _head, default: deepcopy(state.get(path, default)),
    )
    monkeypatch.setattr(github_store, '_create_blob', lambda content: deepcopy(content))
    monkeypatch.setattr(
        github_store,
        '_create_tree',
        lambda head, blobs: {'head': head, 'blobs': deepcopy(blobs)},
    )
    monkeypatch.setattr(
        github_store,
        '_create_commit',
        lambda message, tree, head: {'message': message, 'tree': tree, 'head': head},
    )

    def update_ref(commit):
        updates.append(commit)
        state.update(deepcopy(commit['tree']['blobs']))

    monkeypatch.setattr(github_store, '_update_ref', update_ref)
    return updates


def test_bundle_updates_multiple_files_in_one_ref_change(monkeypatch):
    state = {'a.json': {'value': 1}, 'b.json': {'value': 2}}
    updates = _install_store(monkeypatch, state)

    def mutate(snapshot):
        snapshot['a.json']['value'] += 1
        snapshot['b.json']['value'] += 1
        snapshot['b.json']['operation_id'] = 'op-1'
        return snapshot, 'done'

    ok, result = github_store.update_json_bundle(
        {'a.json': {}, 'b.json': {}}, mutate, 'atomic change', 'op-1'
    )

    assert ok is True
    assert result == 'done'
    assert len(updates) == 1
    assert state['a.json']['value'] == 2
    assert state['b.json']['value'] == 3


def test_ref_conflict_reruns_mutation_from_fresh_state(monkeypatch):
    state = {'a.json': {'items': []}}
    updates = _install_store(monkeypatch, state)
    calls = 0

    def update_ref(commit):
        nonlocal calls
        calls += 1
        if calls == 1:
            state['a.json']['items'].append('concurrent')
            raise github_store.RefConflictError('changed')
        updates.append(commit)
        state.update(deepcopy(commit['tree']['blobs']))

    monkeypatch.setattr(github_store, '_update_ref', update_ref)

    def mutate(snapshot):
        snapshot['a.json']['items'].append('ours')
        snapshot['a.json']['operation_id'] = 'op-2'
        return snapshot, None

    ok, _ = github_store.update_json_bundle({'a.json': {}}, mutate, 'retry', 'op-2')

    assert ok is True
    assert state['a.json']['items'] == ['concurrent', 'ours']
    assert calls == 2


def test_ref_conflict_rediscovers_json_directory_files(monkeypatch):
    directory = 'data/lineups/2026'
    state = {
        'trade.json': {'status': 'pending'},
        f'{directory}/week_1.json': {'cleaned': False},
    }
    updates = _install_store(monkeypatch, state)
    monkeypatch.setattr(
        github_store,
        '_list_json_paths_at',
        lambda path, _head: sorted(
            file_path
            for file_path in state
            if file_path.startswith(f'{path}/') and file_path.endswith('.json')
        ),
    )
    calls = 0

    def update_ref(commit):
        nonlocal calls
        calls += 1
        if calls == 1:
            state[f'{directory}/week_2.json'] = {'cleaned': False}
            raise github_store.RefConflictError('changed')
        updates.append(commit)
        state.update(deepcopy(commit['tree']['blobs']))

    monkeypatch.setattr(github_store, '_update_ref', update_ref)

    def mutate(snapshot):
        snapshot['trade.json'] = {'status': 'accepted', 'operation_id': 'op-directory'}
        for path, content in snapshot.items():
            if path.startswith(f'{directory}/'):
                content['cleaned'] = True
        return snapshot, None

    ok, _ = github_store.update_json_bundle(
        {'trade.json': {}},
        mutate,
        'retry dynamic files',
        'op-directory',
        json_directories_with_defaults={directory: None},
    )

    assert ok is True
    assert state[f'{directory}/week_1.json']['cleaned'] is True
    assert state[f'{directory}/week_2.json']['cleaned'] is True
    assert calls == 2


def test_best_effort_json_directory_does_not_block_fixed_updates(monkeypatch):
    directory = 'data/lineups/2026'
    good_path = f'{directory}/week_1.json'
    bad_path = f'{directory}/week_2.json'
    optional_path = 'web/data.json'
    state = {
        'trade.json': {'status': 'pending'},
        good_path: {'cleaned': False},
        bad_path: {'raw': 'malformed'},
        optional_path: {'raw': 'malformed'},
    }
    _install_store(monkeypatch, state)
    monkeypatch.setattr(
        github_store,
        '_list_json_paths_at',
        lambda _directory, _head: [good_path, bad_path],
    )

    def read_json(path, _head, default):
        if path in {bad_path, optional_path}:
            raise github_store.StoreError('malformed JSON')
        return deepcopy(state.get(path, default))

    monkeypatch.setattr(github_store, '_read_json_at', read_json)
    reported_errors = {}

    def mutate(snapshot):
        snapshot['trade.json'] = {'status': 'accepted', 'operation_id': 'op-best-effort'}
        snapshot[good_path]['cleaned'] = True
        return snapshot, None

    ok, _ = github_store.update_json_bundle(
        {'trade.json': {}, optional_path: None},
        mutate,
        'accept despite bad lineup',
        'op-best-effort',
        json_directories_with_defaults={directory: None},
        best_effort_json_directories=True,
        best_effort_json_paths={optional_path},
        best_effort_errors_callback=reported_errors.update,
    )

    assert ok is True
    assert state['trade.json']['status'] == 'accepted'
    assert state[good_path]['cleaned'] is True
    assert state[bad_path] == {'raw': 'malformed'}
    assert reported_errors == {
        bad_path: 'could not read JSON file',
        optional_path: 'could not read JSON file',
    }


def test_operation_id_makes_retry_idempotent(monkeypatch):
    state = {'a.json': {'operation_id': 'already-done', 'count': 1}}
    updates = _install_store(monkeypatch, state)

    def should_not_run(_snapshot):
        raise AssertionError('mutation should have been deduplicated')

    ok, _ = github_store.update_json_bundle(
        {'a.json': {}}, should_not_run, 'duplicate', 'already-done'
    )

    assert ok is True
    assert updates == []


def test_ambiguous_ref_response_is_verified_by_operation_id(monkeypatch):
    state = {'a.json': {'events': []}}
    _install_store(monkeypatch, state)

    def update_then_disconnect(commit):
        state.update(deepcopy(commit['tree']['blobs']))
        raise OSError('connection reset after ref update')

    monkeypatch.setattr(github_store, '_update_ref', update_then_disconnect)

    def mutate(snapshot):
        snapshot['a.json']['events'].append({'operation_id': 'op-3'})
        return snapshot, 'applied'

    ok, result = github_store.update_json_bundle({'a.json': {}}, mutate, 'ambiguous', 'op-3')

    assert ok is True
    assert result == 'applied'
    assert state['a.json']['events'] == [{'operation_id': 'op-3'}]
