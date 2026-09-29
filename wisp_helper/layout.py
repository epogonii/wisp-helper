# SPDX-License-Identifier: GPL-2.0-or-later

"""Mounted subvolumes, and which rollback fits this system: native, swap or none."""

import os
import re

MOUNTINFO = '/proc/self/mountinfo'


# mountinfo writes space, tab, newline, backslash and, in options, comma as \ooo.
def unescape(field):
    return re.sub(rb'\\([0-7]{3})', lambda match: bytes([int(match[1], 8)]), field)


# Each mount point, and whether a whole btrfs subvolume is mounted there.
def mounts():
    with open(MOUNTINFO, 'rb') as file:
        for line in file:
            fields = line.rstrip(b'\n').split(b' ')
            dash = fields.index(b'-', 6)
            root, path = unescape(fields[3]), unescape(fields[4])
            fstype, options = fields[dash + 1], fields[dash + 3].split(b',')
            # A bind mount of a directory, like PrivateTmp's /var/tmp, has a
            # longer root than its subvol=.
            subvol = [unescape(option[7:]) for option in options if option.startswith(b'subvol=')]
            yield os.fsdecode(path), fstype == b'btrfs' and subvol == [root]


# snapper writes the path into the config file in double quotes.
def plain(path):
    return path.isprintable() and not any(char in path for char in '"\\$`')


# Where a subvolume could get a config: not taken, not snapshots.
def subvolumes(taken):
    seen = {}
    for path, whole in mounts():
        # The last one mounted on a path is the one seen there.
        seen[path] = whole
    return sorted(
        path
        for path, whole in seen.items()
        if whole and path not in taken and '.snapshots' not in path.split('/') and plain(path)
    )
