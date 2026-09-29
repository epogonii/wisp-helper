# SPDX-License-Identifier: GPL-2.0-or-later

"""Running snapper and reading its --jsonout."""

import json
import shutil
import subprocess

from wisp_helper.errors import Failed, Unsupported

ENV = {'PATH': '/usr/sbin:/usr/bin', 'LC_ALL': 'C.UTF-8'}
SNAPPER = shutil.which('snapper', path=ENV['PATH'])


def run(argv, timeout=600):
    try:
        done = subprocess.run(argv, env=ENV, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failed(f'{argv[0]} did not finish in {timeout} s') from None
    if done.returncode != 0:
        raise Failed(done.stderr.strip()[-2000:] or f'{argv[0]} exited with {done.returncode}')
    return done.stdout


def snapper(*args):
    if SNAPPER is None:
        raise Unsupported('snapper is not installed')
    return run([SNAPPER, *args])


def read(*args):
    try:
        return json.loads(snapper('--jsonout', *args))
    except ValueError as error:
        raise Failed(f'cannot read snapper output: {error}') from None


def configs():
    return {row['config'] for row in read('list-configs')['configs']}


def get_config(config):
    return read('-c', config, 'get-config')


def set_config(config, values):
    snapper('-c', config, 'set-config', *(f'{key}={value}' for key, value in values.items()))


# What to set so that user may use the config. Empty if it may already.
def allow_user(values, user):
    users = values.get('ALLOW_USERS', '').split()
    if user in users and values.get('SYNC_ACL') == 'yes':
        return {}
    if user not in users:
        users.append(user)
    return {'ALLOW_USERS': ' '.join(users), 'SYNC_ACL': 'yes'}
