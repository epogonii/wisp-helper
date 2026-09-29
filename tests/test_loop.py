# SPDX-License-Identifier: GPL-2.0-or-later

"""The swap on a throwaway btrfs image, never the real disk.

Needs root and a Linux VM: WISP_LOOP=1 python3 -m pytest tests/test_loop.py
"""

import datetime
import os
import shutil
import subprocess

import pytest

from wisp_helper import layout, swap

pytestmark = pytest.mark.skipif(
    os.environ.get('WISP_LOOP') != '1' or os.geteuid() != 0 or not shutil.which('mkfs.btrfs'),
    reason='root on a Linux VM with WISP_LOOP=1',
)

NOW = datetime.datetime(2026, 9, 29, 12, 0, 5).astimezone()
NESTED = ['.snapshots', 'var/lib/machines', 'var/lib/portables']


def sh(*argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def image(tmp_path, monkeypatch):
    for name in ('setup', 'sysroot', 'check', 'run'):
        (tmp_path / name).mkdir()
    path = tmp_path / 'img'
    with open(path, 'wb') as file:
        file.truncate(400 * 1024 * 1024)
    sh('mkfs.btrfs', '-q', str(path))
    loop = sh('losetup', '-f', '--show', str(path)).strip()
    assert loop.startswith('/dev/loop')
    mounted = []

    def mount(options, where):
        sh('mount', '-o', options, loop, str(where))
        mounted.append(where)

    def unmount(where):
        sh('umount', str(where))
        mounted.remove(where)

    monkeypatch.setattr(layout, 'ROOT', str(tmp_path / 'sysroot'))
    monkeypatch.setattr(layout, 'MOUNTINFO', str(tmp_path / 'mountinfo'))
    monkeypatch.setattr(layout, 'CMDLINE', str(tmp_path / 'cmdline'))
    monkeypatch.setattr(layout, 'FSTAB', str(tmp_path / 'fstab'))
    monkeypatch.setattr(layout, 'PENDING', str(tmp_path / 'run/rollback-pending'))
    monkeypatch.setattr(swap, 'RUNTIME_DIR', str(tmp_path / 'run'))
    (tmp_path / 'mountinfo').write_text(
        f'1 0 0:99 /root / rw - btrfs {loop} rw,subvolid=256,subvol=/root\n'
    )
    (tmp_path / 'cmdline').write_text('root=UUID=x ro rootflags=subvol=root\n')
    (tmp_path / 'fstab').write_text('UUID=x / btrfs subvol=root 0 0\n')
    yield tmp_path, loop, mount, unmount
    for where in reversed(mounted):
        subprocess.run(['umount', str(where)])
    subprocess.run(['losetup', '-d', loop])


# Like Fedora with snapper: .snapshots, machines and portables are subvolumes
# in the root. Snapshot 5 has "old" in it, the root "new" and a container.
def build(tmp_path, mount, unmount, kind):
    setup = tmp_path / 'setup'
    mount('subvolid=5', setup)
    sh('btrfs', '-q', 'subvolume', 'create', str(setup / 'root'))
    sh('btrfs', '-q', 'subvolume', 'create', str(setup / 'home'))
    root = setup / 'root'
    for path in ('var/lib', 'usr/lib/modules/7.2.8', 'etc'):
        (root / path).mkdir(parents=True)
    for path in NESTED:
        sh('btrfs', '-q', 'subvolume', 'create', str(root / path))
    (root / 'etc/marker').write_text('old\n')
    (root / '.snapshots/5').mkdir()
    snapshot = root / '.snapshots/5/snapshot'
    if kind == 'backup':
        sh('btrfs', '-q', 'subvolume', 'create', str(snapshot))
        for path in ('etc', 'var/lib', 'usr/lib/modules/7.2.8'):
            (snapshot / path).mkdir(parents=True)
        (snapshot / 'etc/marker').write_text('old\n')
    else:
        sh('btrfs', '-q', 'subvolume', 'snapshot', '-r', str(root), str(snapshot))
    (root / '.snapshots/5/info.xml').write_text(
        '<?xml version="1.0"?>\n<snapshot><type>single</type><num>5</num>'
        '<date>2026-09-20 09:00:00</date><description>test</description></snapshot>\n'
    )
    (root / 'etc/marker').write_text('new\n')
    (root / 'var/lib/machines/m1').write_text('container\n')
    unmount(setup)
    # The root the machine runs from stays mounted through the swap.
    mount('subvol=root', tmp_path / 'sysroot')


def subvolumes(path):
    return sorted(
        line.split()[-1] for line in sh('btrfs', 'subvolume', 'list', str(path)).splitlines()
    )


@pytest.mark.parametrize('kind', ['snapshot', 'backup'])
def test_swap(image, kind):
    tmp_path, loop, mount, unmount = image
    build(tmp_path, mount, unmount, kind)
    assert layout.rollback({'root': '/'}, lambda config: None) == ('swap', '')
    plan = swap.plan(5, NOW, lambda: None)
    assert plan.source == loop
    assert plan.kernel == ''
    assert plan.backup == 6
    assert plan.moved == NESTED
    assert plan.stand_ins == (NESTED if kind == 'snapshot' else [])

    swap.execute(plan)

    assert os.listdir(tmp_path / 'run') == []
    check = tmp_path / 'check'
    mount('subvolid=5', check)
    root = check / 'root'
    assert sorted(os.listdir(check)) == ['home', 'root']
    assert (root / 'etc/marker').read_text() == 'old\n'
    backup = root / '.snapshots/6/snapshot'
    assert backup.stat().st_ino == 256
    assert (backup / 'etc/marker').read_text() == 'new\n'
    assert (root / '.snapshots/6/info.xml').read_text() == plan.info
    for path in NESTED:
        assert (root / path).stat().st_ino == 256
    assert (root / 'var/lib/machines/m1').read_text() == 'container\n'
    assert sh('btrfs', 'subvolume', 'list', '-o', str(backup)) == ''
    (root / 'etc/written').write_text('yes\n')

    # The running root is still mounted, and mountinfo shows where it went.
    sysroot = tmp_path / 'sysroot'
    assert (sysroot / 'etc/marker').read_text() == 'new\n'
    assert sh('findmnt', '-no', 'FSROOT', str(sysroot)).strip() == '/root/.snapshots/6/snapshot'
    assert not (sysroot / '.snapshots').exists()

    # After a restart snapper takes the backup for one of its own.
    unmount(sysroot)
    mount('subvol=root', sysroot)
    (sysroot / 'etc/snapper/configs').mkdir(parents=True)
    (sysroot / 'etc/snapper/configs/root').write_text('SUBVOLUME="/"\nFSTYPE="btrfs"\n')
    snapper = ['snapper', '--no-dbus', '-r', str(sysroot), '-c', 'root']
    listed = sh(*snapper, 'list', '--columns', 'number,description')
    assert 'rollback backup' in listed
    sh(*snapper, 'delete', '6')
    assert 'rollback backup' not in sh(*snapper, 'list', '--columns', 'number,description')
    assert sorted(os.listdir(root / '.snapshots')) == ['5']


# A failure halfway puts every name back.
def test_swap_put_back(image, monkeypatch):
    tmp_path, loop, mount, unmount = image
    build(tmp_path, mount, unmount, 'snapshot')
    plan = swap.plan(5, NOW, lambda: None)
    rename = os.rename

    def failing(old, new):
        if new.endswith('var/lib/portables'):
            raise OSError(5, 'Input/output error')
        rename(old, new)

    monkeypatch.setattr(os, 'rename', failing)
    with pytest.raises(swap.Failed, match='Everything was put back.$'):
        swap.execute(plan)
    monkeypatch.setattr(os, 'rename', rename)

    check = tmp_path / 'check'
    mount('subvolid=5', check)
    assert sorted(os.listdir(check)) == ['home', 'root']
    root = check / 'root'
    assert (root / 'etc/marker').read_text() == 'new\n'
    assert sorted(os.listdir(root / '.snapshots')) == ['5']
    for path in NESTED:
        assert (root / path).stat().st_ino == 256
    assert (root / 'var/lib/machines/m1').read_text() == 'container\n'
    assert subvolumes(check) == [
        'home',
        'root',
        'root/.snapshots',
        'root/.snapshots/5/snapshot',
        'root/var/lib/machines',
        'root/var/lib/portables',
    ]
    assert sh('findmnt', '-no', 'FSROOT', str(tmp_path / 'sysroot')).strip() == '/root'


# Something left in the way stops it before anything changes.
def test_swap_in_the_way(image):
    tmp_path, loop, mount, unmount = image
    build(tmp_path, mount, unmount, 'snapshot')
    plan = swap.plan(5, NOW, lambda: None)
    setup = tmp_path / 'setup'
    mount('subvolid=5', setup)
    (setup / f'root.{plan.stamp}.new').mkdir()
    unmount(setup)
    with pytest.raises(swap.Failed, match='is in the way$'):
        swap.execute(plan)
    mount('subvolid=5', setup)
    assert sorted(os.listdir(setup)) == ['home', 'root', f'root.{plan.stamp}.new']
    assert sorted(os.listdir(setup / 'root/.snapshots')) == ['5']


# The image's root is not the one this system runs from.
def test_swap_other_root(image):
    tmp_path, loop, mount, unmount = image
    build(tmp_path, mount, unmount, 'snapshot')
    plan = swap.plan(5, NOW, lambda: None)
    unmount(tmp_path / 'sysroot')
    mount('subvol=home', tmp_path / 'sysroot')
    with pytest.raises(swap.Failed, match='/root is not /$'):
        swap.execute(plan)
    check = tmp_path / 'check'
    mount('subvolid=5', check)
    assert sorted(os.listdir(check)) == ['home', 'root']
    assert sorted(os.listdir(check / 'root/.snapshots')) == ['5']


# The snapshot lacks the modules of the default kernel, so grubby picks one it has.
@pytest.mark.parametrize('fails', [False, True])
def test_swap_kernel(image, monkeypatch, fails):
    tmp_path, loop, mount, unmount = image
    build(tmp_path, mount, unmount, 'snapshot')
    sysroot = tmp_path / 'sysroot'
    (sysroot / 'boot').mkdir()
    for version in ('7.2.8', '7.2.9'):
        (sysroot / f'boot/vmlinuz-{version}').touch()
    (sysroot / 'usr/lib/modules/7.2.9').mkdir()
    with open(tmp_path / 'mountinfo', 'a') as file:
        file.write('2 1 8:1 / /boot rw - ext4 /dev/sdz1 rw\n')
    grubby = tmp_path / 'grubby'
    grubby.write_text(
        f'#!/bin/sh\necho "$@" >> {tmp_path}/grubby.log\n'
        '[ "$1" = --default-kernel ] && echo /boot/vmlinuz-7.2.9\nexit 0\n'
    )
    grubby.chmod(0o755)
    monkeypatch.setattr(swap, 'GRUBBY', str(grubby))
    plan = swap.plan(5, NOW, swap.default_kernel)
    assert plan.kernel == '7.2.8'
    calls = ['--default-kernel', '--default-kernel', '--set-default /boot/vmlinuz-7.2.8']
    if fails:
        rename = os.rename

        def failing(old, new):
            if new.endswith('var/lib/portables'):
                raise OSError(5, 'Input/output error')
            rename(old, new)

        monkeypatch.setattr(os, 'rename', failing)
        with pytest.raises(swap.Failed, match='Everything was put back.$'):
            swap.execute(plan)
        calls.append('--set-default /boot/vmlinuz-7.2.9')
    else:
        swap.execute(plan)
    assert (tmp_path / 'grubby.log').read_text().splitlines() == calls


# A timeline snapshot took the number first.
def test_swap_number_taken(image):
    tmp_path, loop, mount, unmount = image
    build(tmp_path, mount, unmount, 'snapshot')
    plan = swap.plan(5, NOW, lambda: None)
    (tmp_path / 'sysroot/.snapshots/6').mkdir()
    with pytest.raises(swap.Failed, match='File exists.*Nothing was changed.$'):
        swap.execute(plan)
    setup = tmp_path / 'setup'
    mount('subvolid=5', setup)
    assert sorted(os.listdir(setup)) == ['home', 'root']


# Docker's would stay in the backup, so nothing is done.
def test_swap_nested(image):
    tmp_path, loop, mount, unmount = image
    build(tmp_path, mount, unmount, 'snapshot')
    sysroot = tmp_path / 'sysroot'
    (sysroot / 'var/lib/docker').mkdir()
    sh('btrfs', '-q', 'subvolume', 'create', str(sysroot / 'var/lib/docker/4f2a'))
    with pytest.raises(swap.Refused, match=': var/lib/docker/4f2a$'):
        swap.plan(5, NOW, lambda: None)
