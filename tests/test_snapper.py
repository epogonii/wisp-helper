# SPDX-License-Identifier: GPL-2.0-or-later

import json

import pytest

from wisp_helper import errors, snapper

ADDED = {'ALLOW_USERS': 'ann', 'SYNC_ACL': 'yes'}


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


def test_failed(fake):
    fake('echo noise; echo "Unknown config." >&2; exit 1')
    with pytest.raises(errors.Failed, match=r'^Unknown config\.$'):
        snapper.get_config('srv')


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
