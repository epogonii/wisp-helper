# SPDX-License-Identifier: GPL-2.0-or-later

import errno
import os
from types import SimpleNamespace

import pytest

from wisp_helper import errors, maintenance

# Bits of the file btrfsmaintenance ships.
TEXT = """\
## Type:        string(none,daily,weekly,monthly)
BTRFS_BALANCE_PERIOD="weekly"

BTRFS_SCRUB_MOUNTPOINTS="/"
BTRFS_SCRUB_PERIOD=monthly
#BTRFS_TRIM_PERIOD="daily"
"""
LABEL = b'system_u:object_r:etc_t:s0\0'


@pytest.fixture
def file(tmp_path):
    path = tmp_path / 'sysconfig' / 'btrfsmaintenance'
    path.parent.mkdir()
    path.write_text(TEXT)
    return path


# os.getxattr is only on Linux, and a test has no business setting real labels.
@pytest.fixture
def labels(monkeypatch):
    labels = SimpleNamespace(label=errno.ENODATA, error=0, set=[])

    def getxattr(path, name):
        if isinstance(labels.label, int):
            raise OSError(labels.label, os.strerror(labels.label))
        return labels.label

    def setxattr(fd, name, value):
        if labels.error:
            raise OSError(labels.error, os.strerror(labels.error))
        labels.set.append((os.fstat(fd).st_ino, name, value))

    monkeypatch.setattr(os, 'getxattr', getxattr, raising=False)
    monkeypatch.setattr(os, 'setxattr', setxattr, raising=False)
    return labels


def test_find(tmp_path, monkeypatch):
    sysconfig, default = tmp_path / 'sysconfig', tmp_path / 'default'
    monkeypatch.setattr(maintenance, 'PATHS', (str(sysconfig), str(default)))
    assert maintenance.find() is None
    default.touch()
    assert maintenance.find() == str(default)
    sysconfig.touch()
    assert maintenance.find() == str(sysconfig)


# Quoted, not quoted, only in a comment.
@pytest.mark.parametrize(
    'values, text',
    [
        ({'BTRFS_BALANCE_PERIOD': 'none'}, TEXT.replace('"weekly"', '"none"')),
        ({'BTRFS_SCRUB_PERIOD': 'daily'}, TEXT.replace('=monthly', '="daily"')),
        ({'BTRFS_TRIM_PERIOD': 'weekly'}, TEXT + 'BTRFS_TRIM_PERIOD="weekly"\n'),
        (
            {'BTRFS_DEFRAG_PERIOD': 'none', 'BTRFS_BALANCE_PERIOD': 'monthly'},
            TEXT.replace('"weekly"', '"monthly"') + 'BTRFS_DEFRAG_PERIOD="none"\n',
        ),
    ],
)
def test_set_values(file, labels, values, text):
    maintenance.set_values(str(file), values)
    assert file.read_text() == text


@pytest.mark.parametrize(
    'before, after',
    [
        (b'', b'BTRFS_TRIM_PERIOD="weekly"\n'),
        (b'X="1"', b'X="1"\nBTRFS_TRIM_PERIOD="weekly"\n'),
        (
            b'BTRFS_TRIM_PERIOD="none"\nX="1"\nBTRFS_TRIM_PERIOD=daily\n',
            b'BTRFS_TRIM_PERIOD="weekly"\nX="1"\nBTRFS_TRIM_PERIOD="weekly"\n',
        ),
        (
            b'BTRFS_TRIM_PERIOD_OLD="none"\n',
            b'BTRFS_TRIM_PERIOD_OLD="none"\nBTRFS_TRIM_PERIOD="weekly"\n',
        ),
        (b'# \xff\nBTRFS_TRIM_PERIOD="none"\n', b'# \xff\nBTRFS_TRIM_PERIOD="weekly"\n'),
        # The shell ends a line only at \n.
        (
            b'# lone\rBTRFS_TRIM_PERIOD=x\n',
            b'# lone\rBTRFS_TRIM_PERIOD=x\nBTRFS_TRIM_PERIOD="weekly"\n',
        ),
        (
            b'X="1"\r\nBTRFS_TRIM_PERIOD="none"\r\nY="2"\r\n',
            b'X="1"\r\nBTRFS_TRIM_PERIOD="weekly"\nY="2"\r\n',
        ),
    ],
)
def test_set_values_bytes(file, labels, before, after):
    file.write_bytes(before)
    maintenance.set_values(str(file), {'BTRFS_TRIM_PERIOD': 'weekly'})
    assert file.read_bytes() == after


def test_set_values_link(file, labels, tmp_path):
    link = tmp_path / 'default' / 'btrfsmaintenance'
    link.parent.mkdir()
    link.symlink_to(file)
    maintenance.set_values(str(link), {'BTRFS_BALANCE_PERIOD': 'none'})
    assert link.is_symlink()
    assert file.read_text() == TEXT.replace('"weekly"', '"none"')
    assert os.listdir(link.parent) == [link.name]


def test_replace_like(file, labels):
    file.chmod(0o640)
    labels.label = LABEL
    before = file.stat()
    maintenance.replace_like(str(file), 'X="1"\n')
    after = file.stat()
    assert file.read_text() == 'X="1"\n'
    assert after.st_mode == before.st_mode
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert after.st_ino != before.st_ino
    assert labels.set == [(after.st_ino, 'security.selinux', LABEL)]
    assert os.listdir(file.parent) == [file.name]


# No SELinux, or no xattrs at all.
@pytest.mark.parametrize('code', [errno.ENODATA, errno.ENOTSUP])
def test_no_label(file, labels, code):
    labels.label = code
    maintenance.replace_like(str(file), 'X="1"\n')
    assert file.read_text() == 'X="1"\n'
    assert labels.set == []


# The label cannot be read, or cannot be set.
@pytest.mark.parametrize('label, error', [(errno.EACCES, 0), (LABEL, errno.EPERM)])
def test_replace_like_failed(file, labels, label, error):
    labels.label, labels.error = label, error
    with pytest.raises(PermissionError):
        maintenance.replace_like(str(file), 'X="1"\n')
    assert file.read_text() == TEXT
    assert os.listdir(file.parent) == [file.name]


def test_refresh(tmp_path, monkeypatch):
    path = tmp_path / 'systemctl'
    path.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{tmp_path}/args"\n')
    path.chmod(0o755)
    monkeypatch.setattr(maintenance, 'SYSTEMCTL', str(path))
    maintenance.refresh()
    assert (tmp_path / 'args').read_text().splitlines() == [
        'start',
        'btrfsmaintenance-refresh.service',
    ]
    path.write_text(
        '#!/bin/sh\necho "Unit btrfsmaintenance-refresh.service not found." >&2\nexit 5\n'
    )
    with pytest.raises(errors.Failed, match='^Unit btrfsmaintenance-refresh.service not found.$'):
        maintenance.refresh()
