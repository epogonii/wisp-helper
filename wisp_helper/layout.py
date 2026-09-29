# SPDX-License-Identifier: GPL-2.0-or-later

"""Mounted subvolumes, and which rollback fits this system: native, swap or none."""

import os
import re
from typing import NamedTuple

MOUNTINFO = '/proc/self/mountinfo'
CMDLINE = '/proc/cmdline'
FSTAB = '/etc/fstab'
# The unit's RuntimeDirectory keeps it until the machine starts again.
RUNTIME_DIR = '/run/wisp-helper'
PENDING = f'{RUNTIME_DIR}/rollback-pending'
# Where the running system's files are looked at. Tests point it at an image.
ROOT = '/'

# The top directory of a subvolume has inode 256. A snapshot has an empty
# directory with inode 2 where the original had a subvolume of its own.
SUBVOLUME = 256
STAND_IN = 2


class Mount(NamedTuple):
    root: str
    path: str
    fstype: str
    source: str
    options: list


# mountinfo writes space, tab, newline, backslash and, in options, comma as \ooo.
def unescape(field):
    return re.sub(rb'\\([0-7]{3})', lambda match: bytes([int(match[1], 8)]), field)


def mounts():
    found = []
    with open(MOUNTINFO, 'rb') as file:
        for line in file:
            fields = line.rstrip(b'\n').split(b' ')
            dash = fields.index(b'-', 6)
            root, path, fstype, source = (
                os.fsdecode(unescape(field))
                for field in (fields[3], fields[4], fields[dash + 1], fields[dash + 2])
            )
            options = [os.fsdecode(unescape(option)) for option in fields[dash + 3].split(b',')]
            found.append(Mount(root, path, fstype, source, options))
    return found


# The last one mounted on a path is the one seen there.
def seen(path, table):
    return next((mount for mount in reversed(table) if mount.path == path), None)


# A bind mount of a directory, like PrivateTmp's /var/tmp, has a longer root
# than its subvol=.
def whole(mount):
    subvol = [option[7:] for option in mount.options if option.startswith('subvol=')]
    return mount.fstype == 'btrfs' and subvol == [mount.root]


# snapper writes the path into the config file in double quotes.
def plain(path):
    return path.isprintable() and not any(char in path for char in '"\\$`')


# Where a subvolume could get a config: not taken, not snapshots.
def subvolumes(taken):
    table = mounts()
    return sorted(
        path
        for path in {mount.path for mount in table}
        if whole(seen(path, table))
        and path not in taken
        and '.snapshots' not in path.split('/')
        and not path.startswith(f'{RUNTIME_DIR}/')
        and plain(path)
    )


def read(path):
    try:
        with open(path, encoding='utf-8', errors='surrogateescape') as file:
            return file.read()
    except FileNotFoundError:
        return ''


def at(path):
    return os.path.join(ROOT, path.lstrip('/'))


def inode(path):
    try:
        return os.lstat(at(path)).st_ino
    except OSError:
        return 0


def names(path):
    try:
        return os.listdir(at(path))
    except OSError:
        return []


# What the kernel was asked to mount the root with.
def rootflags():
    words = [word for word in read(CMDLINE).split() if word.startswith('rootflags=')]
    return words[-1].removeprefix('rootflags=').split(',') if words else []


def fstab_options():
    for line in read(FSTAB).splitlines():
        fields = line.split()
        if len(fields) > 3 and not fields[0].startswith('#') and fields[1] == '/':
            return fields[3].split(',')
    return []


def mark_pending():
    with open(PENDING, 'w'):
        pass


def asked(flags):
    return [flag[7:].strip('/') for flag in flags if flag.startswith('subvol=')]


def named(options):
    return any(option.startswith(('subvol=', 'subvolid=')) for option in options)


# A swap renames the root the machine runs from, and mountinfo follows the
# rename. So a root that is no longer where the kernel was asked to find it
# has been swapped away since boot.
def pending():
    if os.path.exists(PENDING):
        return True
    root = seen('/', mounts())
    names = asked(rootflags())[-1:]
    return root is not None and whole(root) and names not in ([], [root.root.strip('/')])


# default(config) tells which snapshot btrfs mounts by default, as a row of
# snapper list, or None when that is not a snapshot. Only native needs it.
def rollback(configs, default):
    if pending():
        return 'none', 'pending'
    config = next((name for name, subvolume in configs.items() if subvolume == '/'), None)
    if config is None:
        return 'none', 'no-root-config'
    table = mounts()
    root = seen('/', table)
    if root is None or root.fstype != 'btrfs':
        return 'none', 'not-btrfs'
    fstab = fstab_options()

    # snapper rolls back by pointing btrfs at another default subvolume, which
    # fstab overrules when it names the root. So does the kernel command line,
    # unless the root it names is a snapshot, as from the boot menu.
    row = default(config)
    pinned = ''
    if row is not None:
        if row['read-only']:
            return 'none', 'transactional'
        if named(fstab):
            pinned = 'fstab'
        elif row['running'] is None and named(rootflags()):
            pinned = 'rootflags'
        elif row['pending']:
            # snapper rollback from a terminal leaves no mark.
            return 'none', 'pending'
        else:
            return 'native', ''
    why = no_swap(root, table, fstab)
    if not why:
        return 'swap', ''
    return 'none', pinned or why


# A swap renames subvolumes, which does nothing to a root asked for by id.
def no_swap(root, table, fstab):
    if root.root == '/':
        return 'top-level'
    flags = rootflags()
    if any(option.startswith('subvolid=') for option in flags + fstab):
        return 'by-id'
    if asked(flags)[-1:] != [root.root.strip('/')]:
        return 'cmdline'
    # .snapshots has to be a subvolume inside the root, as snapper makes it.
    if seen('/.snapshots', table) is not None:
        return 'snapshots-mounted'
    if inode('/.snapshots') != SUBVOLUME:
        return 'snapshots-missing'
    return ''
