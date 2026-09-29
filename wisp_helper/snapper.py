# SPDX-License-Identifier: GPL-2.0-or-later

"""Running snapper and reading its --jsonout."""

import json
import shutil
import subprocess
import tempfile

from wisp_helper.errors import Failed, Unsupported

ENV = {'PATH': '/usr/sbin:/usr/bin', 'LC_ALL': 'C.UTF-8'}
SNAPPER = shutil.which('snapper', path=ENV['PATH'])
# The unit's RuntimeDirectory.
RUNTIME_DIR = '/run/wisp-helper'


# A path or a description in the output need not be UTF-8.
def run(argv, timeout=600):
    try:
        done = subprocess.run(
            argv,
            env=ENV,
            capture_output=True,
            text=True,
            errors='surrogateescape',
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise Failed(f'{argv[0]} did not finish in {timeout} s') from None
    if done.returncode != 0:
        raise Failed(
            printable(done.stderr.strip()[-2000:]) or f'{argv[0]} exited with {done.returncode}'
        )
    return done


# D-Bus takes only UTF-8.
def printable(text):
    return text.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace')


def snapper(*args, timeout=600):
    if SNAPPER is None:
        raise Unsupported('snapper is not installed')
    return run([SNAPPER, *args], timeout)


def read(*args):
    try:
        return json.loads(snapper('--jsonout', *args).stdout)
    except ValueError as error:
        raise Failed(f'cannot read snapper output: {error}') from None


# Each config's name with the subvolume it takes snapshots of.
def configs():
    return {row['config']: row['subvolume'] for row in read('list-configs')['configs']}


def get_config(config):
    return read('-c', config, 'get-config')


def set_config(config, values):
    snapper('-c', config, 'set-config', *(f'{key}={value}' for key, value in values.items()))


def create_config(config, subvolume):
    snapper('-c', config, 'create-config', subvolume)


def delete_config(config):
    snapper('-c', config, 'delete-config')


# The numbers of config's snapshots, with 0 for the running system.
def numbers(config):
    return {row['number'] for row in read('-c', config, 'list', '--columns', 'number')[config]}


# The snapshot btrfs mounts by default, or None when that is not one of config's.
def default_snapshot(config):
    rows = read('-c', config, 'list', '--columns', 'number,default,read-only')[config]
    return next((row for row in rows if row['default'] and row['number'] != 0), None)


# snapper keeps the running system as "rollback backup of #N" and makes a
# writable copy of the snapshot the default subvolume.
def rollback(config, number):
    before = numbers(config)
    snapper('-c', config, 'rollback', str(number), timeout=None)
    rows = read('-c', config, 'list', '--columns', 'number,description')[config]
    for row in rows:
        if row['number'] not in before and row['description'].startswith('rollback backup'):
            return row['number']
    return 0


def undo_change(config, first, last, paths):
    with tempfile.NamedTemporaryFile(dir=RUNTIME_DIR) as file:
        file.write(b''.join(path + b'\n' for path in paths))
        file.flush()
        # Without -i snapper would undo every change. There is no timeout:
        # killed halfway, it would leave the restore half done.
        argv = ['-c', config, 'undochange', '-i', file.name, f'{first}..{last}']
        done = snapper(*argv, timeout=None)
    # A file snapper could not put back does not change its exit code.
    failed = [line for line in done.stderr.splitlines() if line.startswith('failed to ')]
    if failed:
        raise Failed(printable('\n'.join(failed)[-2000:]))


# What to set so that user may use the config. Empty if it may already.
def allow_user(values, user):
    users = values.get('ALLOW_USERS', '').split()
    if user in users and values.get('SYNC_ACL') == 'yes':
        return {}
    if user not in users:
        users.append(user)
    return {'ALLOW_USERS': ' '.join(users), 'SYNC_ACL': 'yes'}
