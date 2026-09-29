# SPDX-License-Identifier: GPL-2.0-or-later

import re

from wisp_helper.errors import Invalid

# Same rule as in Wisp's prefs. It stays a file name under /etc/snapper/configs.
CONFIG_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')


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
