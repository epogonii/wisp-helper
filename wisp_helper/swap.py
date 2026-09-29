# SPDX-License-Identifier: GPL-2.0-or-later

"""Rollback by swapping subvolumes, for Fedora.

snapper rolls back by pointing btrfs at another default subvolume, and
refuses where the default is not one of its snapshots. Fedora as installed
mounts the root by subvolume name instead, and there the same is done by
renaming. A writable copy of the snapshot takes the root's name, the
snapshots move across to it, and the system as it was becomes one of them.
Ported from Wisp's lib/rollback.js at 31d86da.
"""

import datetime
import logging
import os
import re
import shutil
import tempfile
from typing import NamedTuple

from wisp_helper import layout
from wisp_helper.errors import Failed
from wisp_helper.snapper import ENV, run

log = logging.getLogger(__name__)

BTRFS = shutil.which('btrfs', path=ENV['PATH'])
MOUNT = shutil.which('mount', path=ENV['PATH'])
UMOUNT = shutil.which('umount', path=ENV['PATH'])
GRUBBY = shutil.which('grubby', path=ENV['PATH'])
# The unit's RuntimeDirectory. The top of the filesystem is mounted in it
# while the names change, and PrivateMounts hides that from everybody else.
RUNTIME_DIR = layout.RUNTIME_DIR

# Subvolumes systemd makes inside the root, moved across like .snapshots.
NESTED = ['var/lib/machines', 'var/lib/portables']


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Plan(NamedTuple):
    source: str
    subvolume: str
    number: int
    backup: int
    kernel: str
    moved: list
    stand_ins: list
    stamp: str
    info: str


def default_kernel():
    if GRUBBY is None:
        return None
    return run([GRUBBY, '--default-kernel']).stdout.strip()


# Subvolumes right inside the running root, as paths in it.
def children(subvolume):
    lines = run([BTRFS, 'subvolume', 'list', '-o', layout.at('/')]).stdout.splitlines()
    paths = [line.split(' path ', 1)[1] for line in lines if ' path ' in line]
    return [path.removeprefix(f'{subvolume}/') for path in paths]


# 6.10 comes after 6.9.
def version_key(version):
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', version)]


# What a swap to snapshot number would do, worked out from the running system
# alone. layout.rollback() has said swap already.
def plan(number, now, current_kernel):
    table = layout.mounts()
    root = layout.seen('/', table)
    subvolume = root.root.strip('/')
    snapshot = f'/.snapshots/{number}/snapshot'
    if layout.inode(snapshot) != layout.SUBVOLUME:
        raise Refused('no-snapshot', f'snapshot {number} is not there')

    # The system as it is now is kept as a snapshot, under a number snapper
    # has not used yet.
    used = [int(name) for name in layout.names('/.snapshots') if re.fullmatch('[0-9]+', name)]
    backup = max(used, default=0) + 1

    # The copy's stand-ins go before the subvolumes move in. An old root kept
    # by an earlier swap has none: the subvolumes moved out of it.
    moved = ['.snapshots']
    for path in NESTED:
        there = layout.inode(f'{snapshot}/{path}')
        if layout.inode(f'/{path}') == layout.SUBVOLUME and there in (layout.STAND_IN, 0):
            moved.append(path)
    stand_ins = [path for path in moved if layout.inode(f'{snapshot}/{path}') != 0]
    # Any other would stay in the backup, with an empty directory for it in the new root.
    left = sorted(set(children(subvolume)) - set(moved))
    if left:
        raise Refused('nested', f'subvolumes in the root would stay behind: {", ".join(left)}')

    # A /boot of its own does not go back with the rest. A kernel there whose
    # modules the snapshot lacks would start without them.
    kernel = ''
    if layout.seen('/boot', table) is not None:
        versions = [
            name[8:]
            for name in layout.names('/boot')
            if name.startswith('vmlinuz-') and layout.inode(f'/usr/lib/modules/{name[8:]}')
        ]
        fit = [
            version for version in versions if layout.inode(f'{snapshot}/usr/lib/modules/{version}')
        ]
        if versions and not fit:
            raise Refused('no-kernel', f'no kernel in /boot has its modules in snapshot {number}')
        if len(fit) < len(versions):
            current = current_kernel()
            if current is None:
                raise Refused(
                    'no-grubby', 'without grubby no kernel the snapshot has can be picked'
                )
            if current not in [f'/boot/vmlinuz-{version}' for version in fit]:
                # A +debug kernel only for somebody who runs one.
                variant = current.partition('+')[2]
                same = [version for version in fit if version.partition('+')[2] == variant]
                kernel = max(same or fit, key=version_key)

    # What snapper writes for the backup its own rollback keeps: cleaned up
    # by number, among the important ones.
    date = now.astimezone(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')
    info = (
        f'<snapshot><type>single</type><num>{backup}</num><date>{date}</date>'
        '<description>rollback backup</description><cleanup>number</cleanup>'
        '<userdata><key>important</key><value>yes</value></userdata></snapshot>\n'
    )
    # Named after the time, so a second go never runs into what the first left.
    stamp = now.strftime('%Y%m%d-%H%M%S')
    return Plan(root.source, subvolume, number, backup, kernel, moved, stand_ins, stamp, info)


# btrfs can fail with the copy already made.
def copy(source, target):
    try:
        run([BTRFS, 'subvolume', 'snapshot', source, target], timeout=None)
    except Failed:
        if os.path.lexists(target):
            run([BTRFS, 'subvolume', 'delete', target], timeout=None)
        raise


def write(path, text):
    with open(path, 'x', encoding='utf-8') as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())


# btrfs gives each subvolume a device number of its own.
def same(path, running):
    first, second = os.stat(path), os.stat(layout.at(running))
    if (first.st_dev, first.st_ino) != (second.st_dev, second.st_ino):
        raise Failed(f'{path} is not {running}')


# Nothing in a swap is killed halfway for taking long.
def execute(plan):
    top = tempfile.mkdtemp(dir=RUNTIME_DIR, prefix='top-')
    try:
        run([MOUNT, '-t', 'btrfs', '-o', 'subvolid=5', plan.source, top], timeout=None)
        try:
            swap(top, plan)
        finally:
            unmount(top)
    finally:
        try:
            os.rmdir(top)
        except OSError as error:
            log.warning('Cannot remove %s: %s', top, error)


# The mount goes with the helper's mount namespace anyway, so none of this
# fails a rollback.
def unmount(top):
    try:
        run([BTRFS, 'filesystem', 'sync', top], timeout=None)
    except Failed as error:
        log.warning('Cannot sync %s: %s', top, error)
    try:
        run([UMOUNT, top], timeout=None)
    except Failed as error:
        log.warning('Cannot unmount %s: %s', top, error)


def swap(top, plan):
    def at(path):
        return os.path.join(top, path)

    sub = plan.subvolume
    kept, fresh = f'{sub}.{plan.stamp}', f'{sub}.{plan.stamp}.new'
    snapshot = f'.snapshots/{plan.number}/snapshot'
    backup = at(f'{sub}/.snapshots/{plan.backup}')
    same(at(sub), '/')
    # btrfs would put the copy inside a directory that is already there.
    for name in (kept, fresh):
        if os.path.lexists(at(name)):
            raise Failed(f'{at(name)} is in the way')
    previous = default_kernel() if plan.kernel else None

    # The number is taken and the copy made before anything is renamed, so a
    # failure up to there leaves the system as it was.
    steps = [
        (f'mkdir {backup}', lambda: os.mkdir(backup), lambda: os.rmdir(backup)),
        (
            f'write {backup}/info.xml',
            lambda: write(f'{backup}/info.xml', plan.info),
            lambda: os.unlink(f'{backup}/info.xml'),
        ),
    ]
    if plan.kernel:
        steps.append(
            (
                f'grubby --set-default /boot/vmlinuz-{plan.kernel}',
                lambda: run(
                    [GRUBBY, '--set-default', f'/boot/vmlinuz-{plan.kernel}'], timeout=None
                ),
                lambda: run([GRUBBY, '--set-default', previous], timeout=None),
            )
        )
    steps.append(
        (
            f'snapshot {snapshot} as {fresh}',
            lambda: copy(at(f'{sub}/{snapshot}'), at(fresh)),
            lambda: run([BTRFS, 'subvolume', 'delete', at(fresh)], timeout=None),
        )
    )
    # Deleting the copy takes these along, so they have nothing to undo.
    for path in plan.stand_ins:
        steps.append(
            (f'rmdir {fresh}/{path}', lambda path=path: os.rmdir(at(f'{fresh}/{path}')), None)
        )
    renames = [(sub, kept), (fresh, sub)]
    renames += [(f'{kept}/{path}', f'{sub}/{path}') for path in plan.moved]
    renames.append((kept, f'{sub}/.snapshots/{plan.backup}/snapshot'))
    for old, new in renames:
        steps.append(
            (
                f'mv {old} {new}',
                lambda old=old, new=new: os.rename(at(old), at(new)),
                lambda old=old, new=new: os.rename(at(new), at(old)),
            )
        )

    done = []
    for name, do, undo in steps:
        log.info('Rollback: %s', name)
        try:
            do()
        except Exception as error:
            put_back(f'{name} failed: {error}', done)
        done.append((name, undo))


def put_back(problem, done):
    undone = False
    for name, undo in reversed(done):
        if undo is None:
            continue
        log.info('Rollback: undoing %s', name)
        try:
            undo()
            undone = True
        except Exception as error:
            raise Failed(
                f'{problem}. Undoing "{name}" failed too: {error}. '
                'What came before it is still done.'
            ) from None
    raise Failed(
        f'{problem}. ' + ('Everything was put back.' if undone else 'Nothing was changed.')
    )
