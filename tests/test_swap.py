# SPDX-License-Identifier: GPL-2.0-or-later

import datetime

import pytest

from wisp_helper import layout, swap

MOUNTINFO = """\
609 1 0:36 /root / rw,relatime shared:1 - btrfs /dev/vda3 rw,seclabel,subvolid=287,subvol=/root
612 609 259:2 / /boot rw,relatime shared:4 - ext4 /dev/vda2 rw,seclabel
"""
SNAPSHOT = '/.snapshots/5/snapshot'
# 12:00 in Chisinau.
NOW = datetime.datetime(
    2026, 9, 29, 12, 0, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=3))
)
INFO = (
    '<snapshot><type>single</type><num>11</num><date>2026-09-29 09:00:05</date>'
    '<description>rollback backup</description><cleanup>number</cleanup>'
    '<userdata><key>important</key><value>yes</value></userdata></snapshot>\n'
)
NESTED = ['.snapshots', 'var/lib/machines', 'var/lib/portables']


@pytest.fixture
def system(tmp_path, monkeypatch):
    mountinfo = tmp_path / 'mountinfo'
    mountinfo.write_text(MOUNTINFO)
    monkeypatch.setattr(layout, 'MOUNTINFO', str(mountinfo))
    inodes = {
        '/.snapshots': 256,
        '/var/lib/machines': 256,
        '/var/lib/portables': 256,
        SNAPSHOT: 256,
        # A snapshot has stand-ins where the root has subvolumes.
        f'{SNAPSHOT}/.snapshots': 2,
        f'{SNAPSHOT}/var/lib/machines': 2,
        f'{SNAPSHOT}/var/lib/portables': 2,
    }
    directories = {'/.snapshots': ['1', '2', '5', '10', 'x'], '/boot': []}
    monkeypatch.setattr(layout, 'inode', lambda path: inodes.get(path, 0))
    monkeypatch.setattr(layout, 'names', lambda path: directories.get(path, []))
    # Subvolumes in the root are what has inode 256 there.
    other = []
    monkeypatch.setattr(
        swap,
        'children',
        lambda subvolume: [path for path in NESTED if inodes.get(f'/{path}') == 256] + other,
    )
    inodes['other'] = other
    return inodes, directories


def plan(kernel='/boot/vmlinuz-7.2.8'):
    return swap.plan(5, NOW, lambda: kernel)


def test_plan(system):
    assert plan() == swap.Plan(
        source='/dev/vda3',
        subvolume='root',
        number=5,
        backup=11,
        kernel='',
        moved=NESTED,
        stand_ins=NESTED,
        stamp='20260929-120005',
        info=INFO,
    )


# The old root an earlier swap kept has no stand-ins.
def test_plan_backup(system):
    inodes, _ = system
    for path in NESTED:
        del inodes[f'{SNAPSHOT}/{path}']
    found = plan()
    assert (found.moved, found.stand_ins) == (NESTED, [])


def test_plan_not_a_subvolume(system):
    inodes, _ = system
    inodes['/var/lib/machines'] = 4711
    found = plan()
    assert found.moved == ['.snapshots', 'var/lib/portables']
    assert found.stand_ins == found.moved


# A subvolume that cannot move, or one of Docker's, would stay in the backup.
@pytest.mark.parametrize(
    'path, left',
    [
        (f'{SNAPSHOT}/var/lib/machines', 'var/lib/machines'),
        (None, 'var/lib/docker/btrfs/subvolumes/4f2a'),
    ],
)
def test_plan_nested(system, path, left):
    inodes, _ = system
    if path:
        inodes[path] = 4711
    else:
        inodes['other'].append(left)
    with pytest.raises(swap.Refused) as info:
        plan()
    assert info.value.code == 'nested'
    assert str(info.value).endswith(f': {left}')


def test_plan_first_backup(system):
    _, directories = system
    directories['/.snapshots'] = ['5', '\u00b2', '\u0663']
    assert plan().backup == 6


def test_no_snapshot(system):
    inodes, _ = system
    inodes[SNAPSHOT] = 2
    with pytest.raises(swap.Refused) as info:
        plan()
    assert info.value.code == 'no-snapshot'


def kernels(system, running, snapshot):
    inodes, directories = system
    directories['/boot'] = [f'vmlinuz-{version}' for version in running] + [
        'vmlinuz-0-rescue-9f1c',
        'config-7.2.8',
        'loader',
    ]
    for version in running:
        inodes[f'/usr/lib/modules/{version}'] = 1000
    for version in snapshot:
        inodes[f'{SNAPSHOT}/usr/lib/modules/{version}'] = 1000


@pytest.mark.parametrize(
    'running, snapshot, default, kernel',
    [
        (['7.2.8', '7.2.9'], ['7.2.8', '7.2.9'], '/boot/vmlinuz-7.2.9', ''),
        # The default one fits, so it stays.
        (['7.2.8', '7.2.9'], ['7.2.8'], '/boot/vmlinuz-7.2.8', ''),
        (['7.2.8', '7.2.9'], ['7.2.8'], '/boot/vmlinuz-7.2.9', '7.2.8'),
        (['6.9.1', '6.10.2', '6.11.0'], ['6.9.1', '6.10.2'], '/boot/vmlinuz-6.11.0', '6.10.2'),
        # The debug kernel only for somebody who runs one.
        (
            ['7.2.9', '7.2.9+debug', '7.3.0'],
            ['7.2.9', '7.2.9+debug'],
            '/boot/vmlinuz-7.3.0',
            '7.2.9',
        ),
        (
            ['7.2.9', '7.2.9+debug', '7.3.0+debug'],
            ['7.2.9', '7.2.9+debug'],
            '/boot/vmlinuz-7.3.0+debug',
            '7.2.9+debug',
        ),
        # No modules in the running system either: not a kernel to count.
        (['7.2.8'], [], None, ''),
    ],
)
def test_kernel(system, running, snapshot, default, kernel):
    kernels(system, running, snapshot)
    if default is None:
        system[0].pop('/usr/lib/modules/7.2.8')
    assert plan(default).kernel == kernel


@pytest.mark.parametrize(
    'snapshot, default, code',
    [([], '/boot/vmlinuz-7.2.9', 'no-kernel'), (['7.2.8'], None, 'no-grubby')],
)
def test_kernel_refused(system, snapshot, default, code):
    kernels(system, ['7.2.8', '7.2.9'], snapshot)
    with pytest.raises(swap.Refused) as info:
        plan(default)
    assert info.value.code == code


# Without a /boot of its own, the kernels go back with the root.
def test_boot_inside(system, tmp_path):
    (tmp_path / 'mountinfo').write_text(MOUNTINFO.splitlines()[0] + '\n')
    kernels(system, ['7.2.8'], [])
    assert plan().kernel == ''


@pytest.mark.parametrize(
    'version, key', [('6.10.2-300.fc45', [6, 10, 2, 300, 45]), ('6.9', [6, 9])]
)
def test_version_key(version, key):
    assert [part for part in swap.version_key(version) if isinstance(part, int)] == key


def test_copy_failed(tmp_path, monkeypatch):
    btrfs = tmp_path / 'btrfs'
    btrfs.write_text(
        '#!/bin/sh\n'
        'if [ "$2" = snapshot ]; then /bin/mkdir "$4"; echo "ERROR: cannot sync" >&2; exit 1; fi\n'
        '/bin/rmdir "$3"\n'
    )
    btrfs.chmod(0o755)
    monkeypatch.setattr(swap, 'BTRFS', str(btrfs))
    with pytest.raises(swap.Failed, match='^ERROR: cannot sync$'):
        swap.copy(str(tmp_path / 'snapshot'), str(tmp_path / 'copy'))
    assert not (tmp_path / 'copy').exists()
