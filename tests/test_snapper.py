# SPDX-License-Identifier: GPL-2.0-or-later

import json
from pathlib import Path

import pytest

from wisp_helper import errors, snapper

ADDED = {'ALLOW_USERS': 'ann', 'SYNC_ACL': 'yes'}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    path = tmp_path / 'run'
    path.mkdir()
    monkeypatch.setattr(snapper, 'RUNTIME_DIR', str(path))
    return path


@pytest.fixture
def fake(tmp_path, monkeypatch):
    def fake(script):
        path = tmp_path / 'snapper'
        path.write_text(f'#!/bin/sh\n{script}\n')
        path.chmod(0o755)
        monkeypatch.setattr(snapper, 'SNAPPER', str(path))

    return fake


@pytest.mark.parametrize(
    'values, changes',
    [
        ({}, ADDED),
        ({'ALLOW_USERS': '', 'SYNC_ACL': 'no'}, ADDED),
        ({'ALLOW_USERS': 'ann', 'SYNC_ACL': 'no'}, ADDED),
        ({'ALLOW_USERS': 'ann bob', 'SYNC_ACL': 'yes'}, {}),
        ({'ALLOW_USERS': 'bob', 'SYNC_ACL': 'yes'}, {**ADDED, 'ALLOW_USERS': 'bob ann'}),
        (
            {'ALLOW_USERS': ' bob  anna ', 'SYNC_ACL': 'no'},
            {**ADDED, 'ALLOW_USERS': 'bob anna ann'},
        ),
    ],
)
def test_allow_user(values, changes):
    assert snapper.allow_user(values, 'ann') == changes


def test_configs(fake):
    rows = [{'config': 'root', 'subvolume': '/'}, {'config': 'home', 'subvolume': '/home'}]
    fake(f"echo '{json.dumps({'configs': rows})}'")
    assert snapper.configs() == {'root': '/', 'home': '/home'}


def test_argv(fake, tmp_path, monkeypatch):
    monkeypatch.setenv('WISP_TEST', 'leaked')
    fake(f'printf "%s\\n" "$@" "$LC_ALL" "${{WISP_TEST-}}" > "{tmp_path}/args"')
    snapper.set_config('root', {'NUMBER_LIMIT': '10', 'ALLOW_USERS': 'ann bob'})
    *args, lc_all, leaked = (tmp_path / 'args').read_text().splitlines()
    assert args == ['-c', 'root', 'set-config', 'NUMBER_LIMIT=10', 'ALLOW_USERS=ann bob']
    assert (lc_all, leaked) == ('C.UTF-8', '')


def test_config_argv(fake, tmp_path):
    fake(f'printf "%s\\n" "$@" >> "{tmp_path}/args"')
    snapper.create_config('srv', '/srv')
    snapper.delete_config('srv')
    lines = (tmp_path / 'args').read_text().splitlines()
    assert lines == ['-c', 'srv', 'create-config', '/srv', '-c', 'srv', 'delete-config']


def test_numbers(fake):
    rows = [{'number': 0}, {'number': 3}, {'number': 12}]
    fake(f"echo '{json.dumps({'home': rows})}'")
    assert snapper.numbers('home') == {0, 3, 12}


def test_undo_change(fake, tmp_path, runtime):
    # The helper deletes the list once snapper is done, so the fake keeps a copy.
    fake(f'printf "%s\\n" "$@" > "{tmp_path}/args"; /bin/cp -p "$5" "{tmp_path}/list"')
    snapper.undo_change('home', 5, 0, [b'/home/ann/a b', '/home/ann/ünal'.encode(), b'/home/\xff'])
    *args, listed, numbers = (tmp_path / 'args').read_text().splitlines()
    assert args == ['-c', 'home', 'undochange', '-i']
    assert Path(listed).parent == runtime
    assert numbers == '5..0'
    copy = tmp_path / 'list'
    assert copy.read_bytes() == '/home/ann/a b\n/home/ann/ünal\n'.encode() + b'/home/\xff\n'
    assert copy.stat().st_mode & 0o777 == 0o600
    assert list(runtime.iterdir()) == []


@pytest.mark.parametrize(
    'script, message',
    [
        ('echo "Invalid snapshots." >&2; exit 1', 'Invalid snapshots.'),
        # snapper goes on past a file it cannot put back and exits with 0.
        (
            'echo create:0 modify:2 delete:0; echo "failed to modify /etc/a" >&2;'
            ' echo "failed to modify /etc/b" >&2',
            'failed to modify /etc/a\nfailed to modify /etc/b',
        ),
    ],
)
def test_undo_change_failed(fake, runtime, script, message):
    fake(script)
    with pytest.raises(errors.Failed) as info:
        snapper.undo_change('root', 5, 0, [b'/etc/a', b'/etc/b'])
    assert str(info.value) == message
    assert list(runtime.iterdir()) == []


def test_failed(fake):
    fake('echo noise; echo "Unknown config." >&2; exit 1')
    with pytest.raises(errors.Failed, match=r'^Unknown config\.$'):
        snapper.get_config('srv')


# D-Bus takes the message only as UTF-8.
def test_failed_not_utf8(fake):
    fake("printf 'File \\047/etc/\\377\\047 not found.\\n' >&2; exit 1")
    with pytest.raises(errors.Failed) as info:
        snapper.get_config('root')
    assert str(info.value) == "File '/etc/\ufffd' not found."


def test_output_not_utf8(fake):
    fake('printf \'{"root": [{"number": 0, "description": "\\377"}]}\'')
    assert snapper.numbers('root') == {0}


def test_failed_quietly(fake):
    fake('exit 3')
    with pytest.raises(errors.Failed, match='exited with 3$'):
        snapper.get_config('root')


def test_not_json(fake):
    fake('echo "Config: root"')
    with pytest.raises(errors.Failed, match='^cannot read snapper output'):
        snapper.get_config('root')


def test_timeout():
    with pytest.raises(errors.Failed, match='did not finish'):
        snapper.run(['/bin/sleep', '5'], timeout=0.1)


def test_missing(monkeypatch):
    monkeypatch.setattr(snapper, 'SNAPPER', None)
    with pytest.raises(errors.Unsupported):
        snapper.configs()


# A timeline snapshot may slip in next to the two rollback makes.
def test_rollback(fake, tmp_path):
    before = {'root': [{'number': 0}, {'number': 5}]}
    after = {
        'root': [
            {'number': 0, 'description': ''},
            {'number': 5, 'description': 'dnf'},
            {'number': 6, 'description': 'timeline'},
            {'number': 7, 'description': 'rollback backup of #1'},
            {'number': 8, 'description': 'writable copy of #5'},
        ]
    }
    fake(
        f'case "$*" in\n'
        f"*'list --columns number') echo '{json.dumps(before)}' ;;\n"
        f"*'list --columns number,description') echo '{json.dumps(after)}' ;;\n"
        f'*) echo "$@" >> "{tmp_path}/args" ;;\n'
        'esac'
    )
    assert snapper.rollback('root', 5) == 7
    assert (tmp_path / 'args').read_text() == '-c root rollback 5\n'
