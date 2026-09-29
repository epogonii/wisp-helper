# SPDX-License-Identifier: GPL-2.0-or-later

import pwd

import pytest

from wisp_helper import errors, validate

CONFIGS = {'root', 'home'}
NUMBERS = {0, 1, 2, 5}

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


@pytest.mark.parametrize(
    'values',
    [
        {'BTRFS_SCRUB_PERIOD': 'monthly'},
        {'BTRFS_BALANCE_PERIOD': 'none', 'BTRFS_DEFRAG_PERIOD': 'daily'},
        {'BTRFS_TRIM_PERIOD': 'weekly'},
    ],
)
def test_periods(values):
    assert validate.periods(values) == values


@pytest.mark.parametrize(
    'values',
    [
        {},
        {'BTRFS_SCRUB_MOUNTPOINTS': 'monthly'},
        {'BTRFS_LOG_OUTPUT': 'none'},
        {'btrfs_scrub_period': 'monthly'},
        {'NUMBER_LIMIT': 'none'},
        {'BTRFS_SCRUB_PERIOD': ''},
        {'BTRFS_SCRUB_PERIOD': 'hourly'},
        {'BTRFS_SCRUB_PERIOD': 'Monthly'},
        {'BTRFS_SCRUB_PERIOD': 'monthly '},
        {'BTRFS_SCRUB_PERIOD': 'Sun *-*-* 03:00'},
        {'BTRFS_SCRUB_PERIOD': 'monthly\nBTRFS_LOG_OUTPUT=x'},
        {'BTRFS_SCRUB_PERIOD': 'monthly"; id; "'},
        {'BTRFS_SCRUB_PERIOD': '$(id)'},
        {'BTRFS_SCRUB_PERIOD': '`id`'},
        {'BTRFS_TRIM_PERIOD': 'weekly', 'BTRFS_SCRUB_PERIOD': 'yearly'},
    ],
)
def test_periods_refused(values):
    with pytest.raises(errors.Invalid):
        validate.periods(values)


def test_new_subvolume():
    assert validate.new_subvolume('/srv', ['/home', '/srv']) == '/srv'
    with pytest.raises(errors.Invalid):
        validate.new_subvolume('/srv/', ['/home', '/srv'])


@pytest.mark.parametrize(
    'paths, subvolume',
    [
        (['/etc/hostname'], '/'),
        (['/etc', '/etc/a b', '/.hidden', '/usr/lib/modules/x', '/ünal'], '/'),
        (['/home/ann', '/home/ann/.bashrc'], '/home'),
        (['/home/ann'], '/home/'),
    ],
)
def test_paths(paths, subvolume):
    assert validate.paths(paths, subvolume) == [path.encode() for path in paths]


# As snapperd sends them: \xNN for a byte over 127, \\ for \.
@pytest.mark.parametrize(
    'path, found',
    [
        ('/etc/\\xc3\\xbcnal', b'/etc/\xc3\xbcnal'),
        ('/etc/\\xC3\\xBCnal', b'/etc/\xc3\xbcnal'),
        ('/etc/\\xff', b'/etc/\xff'),
        ('/etc/a\\\\b', b'/etc/a\\b'),
        ('/etc/\\\\x41', b'/etc/\\x41'),
        ('/etc/\\x41', b'/etc/A'),
    ],
)
def test_paths_escaped(path, found):
    assert validate.paths([path], '/') == [found]


@pytest.mark.parametrize(
    'paths, subvolume',
    [
        ([], '/'),
        ([''], '/'),
        (['/'], '/'),
        (['etc/hostname'], '/'),
        (['//etc/hostname'], '/'),
        (['/etc//hostname'], '/'),
        (['/etc/./hostname'], '/'),
        (['/etc/../etc/hostname'], '/'),
        (['/etc/'], '/'),
        (['/etc/a\nb'], '/'),
        (['/etc/a\0b'], '/'),
        (['/etc/hostname', '/etc/a\n/etc/shadow'], '/'),
        (['/home'], '/home'),
        (['/home/'], '/home'),
        (['/home2/ann'], '/home'),
        (['/etc/passwd'], '/home'),
        (['/home/../etc/passwd'], '/home'),
        (['/etc/a\\b'], '/'),
        (['/etc/a\\'], '/'),
        (['/etc/\\x4'], '/'),
        (['/etc/\\xzz'], '/'),
        (['/etc/a\\x0ab'], '/'),
        (['/etc/a\\x00b'], '/'),
        (['/etc/\\x2e\\x2e/shadow'], '/'),
        (['/home/ann\\x2f..\\x2f..\\x2fetc'], '/home'),
    ],
)
def test_paths_refused(paths, subvolume):
    with pytest.raises(errors.Invalid):
        validate.paths(paths, subvolume)


@pytest.mark.parametrize('first, last', [(1, 2), (2, 1), (5, 0)])
def test_snapshots(first, last):
    assert validate.snapshots(first, last, NUMBERS) == (first, last)


# The running system as first, the same twice, a snapshot that is not there.
@pytest.mark.parametrize('first, last', [(0, 5), (0, 0), (2, 2), (3, 0), (1, 7)])
def test_snapshots_refused(first, last):
    with pytest.raises(errors.Invalid):
        validate.snapshots(first, last, NUMBERS)
