# SPDX-License-Identifier: GPL-2.0-or-later

import pwd

import pytest

from wisp_helper import errors, validate

CONFIGS = {'root', 'home'}

ACCOUNTS = [('ann', 1000), ('bob smith', 1001), ('carl', 1002), ('carl', 1003), ('ünal', 1004)]


@pytest.fixture
def accounts(monkeypatch):
    entries = [
        pwd.struct_passwd((name, 'x', uid, uid, '', '/', '/bin/sh')) for name, uid in ACCOUNTS
    ]

    def find(field, value):
        for entry in entries:
            if getattr(entry, field) == value:
                return entry
        raise KeyError(value)

    monkeypatch.setattr(pwd, 'getpwuid', lambda uid: find('pw_uid', uid))
    monkeypatch.setattr(pwd, 'getpwnam', lambda name: find('pw_name', name))


def test_error_names():
    names = {cls.dbus_name() for cls in errors.Error.__subclasses__()}
    assert names == {
        f'io.github.epogonii.WispHelper.Error.{name}'
        for name in ('NotAuthorized', 'Invalid', 'Busy', 'Unsupported', 'Pending', 'Failed')
    }


def test_config():
    assert validate.config('root', CONFIGS) == 'root'
    with pytest.raises(errors.Invalid):
        validate.config('srv', CONFIGS)


@pytest.mark.parametrize('name', ['srv', 'var-log', 'data_2', 'home.old', 'A', 'x' * 64])
def test_new_config(name):
    assert validate.new_config(name, CONFIGS) == name


@pytest.mark.parametrize(
    'name',
    [
        '',
        'root',
        '.',
        '..',
        '.hidden',
        '-c',
        '_x',
        'a/b',
        '../etc',
        'a b',
        'a\nb',
        'a\0b',
        'snäp',
        'x' * 65,
    ],
)
def test_new_config_refused(name):
    with pytest.raises(errors.Invalid):
        validate.new_config(name, CONFIGS)


def test_user(accounts):
    assert validate.user(1000) == 'ann'
    assert validate.user(1002) == 'carl'


# root, a space, a name that leads to another UID, not ASCII, no account.
@pytest.mark.parametrize('uid', [0, 1001, 1003, 1004, 1005])
def test_user_refused(accounts, uid):
    with pytest.raises(errors.Invalid):
        validate.user(uid)


@pytest.mark.parametrize(
    'values',
    [
        {'TIMELINE_CREATE': 'yes'},
        {'NUMBER_CLEANUP': 'no', 'NUMBER_LIMIT': '50'},
        {'NUMBER_LIMIT': '2-10', 'NUMBER_LIMIT_IMPORTANT': '4-4'},
        {'TIMELINE_LIMIT_HOURLY': '0', 'TIMELINE_LIMIT_YEARLY': '5-10'},
        {'TIMELINE_LIMIT_QUARTERLY': '999999'},
    ],
)
def test_settings(values):
    assert validate.settings(values) == values


@pytest.mark.parametrize(
    'values',
    [
        {},
        {'ALLOW_USERS': 'ann'},
        {'SYNC_ACL': 'yes'},
        {'SUBVOLUME': '/'},
        {'NUMBER_LIMIT': '10', 'FSTYPE': 'btrfs'},
        {'TIMELINE_CREATE': 'true'},
        {'TIMELINE_CREATE': ''},
        {'NUMBER_LIMIT': ''},
        {'NUMBER_LIMIT': '-1'},
        {'NUMBER_LIMIT': '10-2'},
        {'NUMBER_LIMIT': '1-2-3'},
        {'NUMBER_LIMIT': '1000000'},
        {'NUMBER_LIMIT': ' 10'},
        {'NUMBER_LIMIT': '10\n'},
        {'NUMBER_LIMIT': '\u0661\u0660'},
        {'NUMBER_LIMIT': '10"\nALLOW_USERS="ann'},
    ],
)
def test_settings_refused(values):
    with pytest.raises(errors.Invalid):
        validate.settings(values)


def test_new_subvolume():
    assert validate.new_subvolume('/srv', ['/home', '/srv']) == '/srv'
    with pytest.raises(errors.Invalid):
        validate.new_subvolume('/srv/', ['/home', '/srv'])
