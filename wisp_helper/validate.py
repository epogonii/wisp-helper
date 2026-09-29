# SPDX-License-Identifier: GPL-2.0-or-later

import os
import pwd
import re

from wisp_helper.errors import Invalid

# Same rule as in Wisp's prefs. It stays a file name under /etc/snapper/configs.
CONFIG_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')

# ALLOW_USERS is split on spaces, so a name with one would let in someone else.
USER_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,255}')

# The config keys Wisp's prefs change. ALLOW_USERS and SYNC_ACL go through GrantAccess.
SWITCHES = {'TIMELINE_CREATE', 'NUMBER_CLEANUP'}
LIMITS = {
    'NUMBER_LIMIT',
    'NUMBER_LIMIT_IMPORTANT',
    'TIMELINE_LIMIT_HOURLY',
    'TIMELINE_LIMIT_DAILY',
    'TIMELINE_LIMIT_WEEKLY',
    'TIMELINE_LIMIT_MONTHLY',
    'TIMELINE_LIMIT_QUARTERLY',
    'TIMELINE_LIMIT_YEARLY',
}
# A number, or a range like 2-10 that snapper narrows as the disk fills up.
LIMIT = re.compile(r'([0-9]{1,6})(?:-([0-9]{1,6}))?')

# btrfsmaintenance's jobs. Its file is sourced by a root shell, so only these words go in.
JOBS = {'BTRFS_BALANCE_PERIOD', 'BTRFS_SCRUB_PERIOD', 'BTRFS_DEFRAG_PERIOD', 'BTRFS_TRIM_PERIOD'}
PERIODS = {'none', 'daily', 'weekly', 'monthly'}


def user(uid):
    if uid == 0:
        raise Invalid('root needs no access')
    try:
        name = pwd.getpwuid(uid).pw_name
        same = pwd.getpwnam(name).pw_uid == uid
    except KeyError:
        raise Invalid(f'uid {uid} has no account name') from None
    if not same or not USER_NAME.fullmatch(name):
        raise Invalid(f'cannot add {name!r} to ALLOW_USERS')
    return name


def config(name, configs):
    if name not in configs:
        raise Invalid(f'no config {name!r}')
    return name


def new_config(name, configs):
    if not CONFIG_NAME.fullmatch(name):
        raise Invalid(f'not a config name: {name!r}')
    if name in configs:
        raise Invalid(f'config {name!r} already exists')
    return name


def new_subvolume(path, candidates):
    if path not in candidates:
        raise Invalid(f'cannot make a config for {path!r}')
    return path


def settings(values):
    if not values:
        raise Invalid('nothing to change')
    for key, value in values.items():
        if key in SWITCHES:
            good = value in ('yes', 'no')
        elif key in LIMITS:
            match = LIMIT.fullmatch(value)
            good = match and (match[2] is None or int(match[1]) <= int(match[2]))
        else:
            raise Invalid(f'cannot change {key}')
        if not good:
            raise Invalid(f'{key} cannot be {value!r}')
    return values


def periods(values):
    if not values:
        raise Invalid('nothing to change')
    for key, value in values.items():
        if key not in JOBS:
            raise Invalid(f'cannot change {key}')
        if value not in PERIODS:
            raise Invalid(f'{key} cannot be {value!r}')
    return values


# snapperd sends a byte over 127 as \xNN and \ as \\. Plain text is taken as well.
ESCAPED = re.compile(rb'(?:[^\\]|\\\\|\\x[0-9A-Fa-f]{2})*')


def unescape(path):
    raw = path.encode('utf-8')
    if not ESCAPED.fullmatch(raw):
        raise Invalid(f'cannot read {path!r}')
    return re.sub(
        rb'\\(\\|x(..))', lambda match: bytes.fromhex(match[2].decode()) if match[2] else b'\\', raw
    )


# undochange reads its list line by line, as bytes, and looks each path up as it is.
def paths(values, subvolume):
    if not values:
        raise Invalid('nothing to undo')
    prefix = subvolume.rstrip('/') + '/'
    found = []
    for value in values:
        path = os.fsdecode(unescape(value))
        # normpath keeps a leading //.
        clean = os.path.normpath(path) == path and not path.startswith('//')
        inside = path.startswith(prefix) and path != prefix
        if not clean or not inside or '\n' in path or '\0' in path:
            raise Invalid(f'cannot undo {value!r} in {subvolume}')
        found.append(os.fsencode(path))
    return found


# snapper puts files back as first had them. 0 is the running system.
def snapshots(first, last, numbers):
    if first == 0 or first == last:
        raise Invalid(f'cannot undo {first}..{last}')
    for number in (first, last):
        if number not in numbers:
            raise Invalid(f'no snapshot {number}')
    return first, last
