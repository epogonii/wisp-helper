# SPDX-License-Identifier: GPL-2.0-or-later

import pwd
import re

from wisp_helper.errors import Invalid

# Same rule as in Wisp's prefs. It stays a file name under /etc/snapper/configs.
CONFIG_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')

# ALLOW_USERS is split on spaces, so a name with one would let in someone else.
USER_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,255}')


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
