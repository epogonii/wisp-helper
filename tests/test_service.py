# SPDX-License-Identifier: GPL-2.0-or-later

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from wisp_helper import NAME, PATH, VERSION

Gio = pytest.importorskip('gi.repository.Gio')
GLib = pytest.importorskip('gi.repository.GLib')
pytest.importorskip('dbusmock')

ROOT = Path(__file__).resolve().parent.parent
POLKIT = 'org.freedesktop.PolicyKit1'
AUTHORITY = '/org/freedesktop/PolicyKit1/Authority'

# A call for every method that needs polkit.
ACTIONS = {
    'GrantAccess': ('(s)', ('root',)),
    'SetConfig': ('(sa{ss})', ('root', {'NUMBER_LIMIT': '10'})),
    'CreateConfig': ('(ss)', ('srv', '/srv')),
    'DeleteConfig': ('(s)', ('srv',)),
    'UndoChange': ('(suuas)', ('root', 1, 2, ['/etc/hostname'])),
    'Rollback': ('(su)', ('root', 5)),
    'SetMaintenance': ('(a{ss})', ({'BTRFS_SCRUB_PERIOD': 'monthly'},)),
}

SHORT_IDLE = 'from wisp_helper import __main__, service; service.IDLE = 2; __main__.main()'


def request(bus, name, path, interface, method, args=None, reply=None, flags=0):
    reply = GLib.VariantType(reply) if reply else None
    return bus.call_sync(name, path, interface, method, args, reply, flags, 10000, None).unpack()


def remote_error(error):
    return Gio.DBusError.get_remote_error(error).removeprefix(f'{NAME}.Error.')


def refusal(bus, method, interactive=False):
    signature, args = ACTIONS[method]
    flags = Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION if interactive else 0
    with pytest.raises(GLib.Error) as info:
        request(bus, NAME, PATH, NAME, method, GLib.Variant(signature, args), flags=flags)
    return remote_error(info.value)


def wait_for(bus, name, owned=True):
    for _ in range(100):
        args = GLib.Variant('(s)', (name,))
        dbus = 'org.freedesktop.DBus'
        (has,) = request(bus, dbus, '/org/freedesktop/DBus', dbus, 'NameHasOwner', args, '(b)')
        if has == owned:
            return
        time.sleep(0.1)
    raise TimeoutError(name)


def spawn(address, *argv, **kwargs):
    env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=address)
    return subprocess.Popen([sys.executable, *argv], cwd=ROOT, env=env, **kwargs)


def stop(process, bus, name):
    process.terminate()
    process.wait()
    wait_for(bus, name, owned=False)


class Polkit:
    def __init__(self, bus):
        self.bus = bus

    def mock(self, method, args, reply=None):
        return request(
            self.bus, POLKIT, AUTHORITY, 'org.freedesktop.DBus.Mock', method, args, reply
        )

    def allow(self, *actions, delay=0):
        allowed = [f'{NAME}.{action}' for action in actions]
        code = f'import time\ntime.sleep({delay})\nret = (args[1] in {allowed!r}, False, {{}})'
        method = (
            f'{POLKIT}.Authority',
            'CheckAuthorization',
            '(sa{sv})sa{ss}us',
            '(bba{ss})',
            code,
        )
        self.mock('AddMethod', GLib.Variant('(sssss)', method))

    def calls(self):
        args = GLib.Variant('(s)', ('CheckAuthorization',))
        (calls,) = self.mock('GetMethodCalls', args, '(a(tav))')
        return [args for _, args in calls]


@pytest.fixture(scope='module')
def address():
    daemon = subprocess.Popen(
        ['dbus-daemon', '--session', '--nofork', '--print-address'],
        stdout=subprocess.PIPE,
        text=True,
    )
    yield daemon.stdout.readline().strip()
    daemon.terminate()
    daemon.wait()


@pytest.fixture(scope='module')
def bus(address):
    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    bus = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
    yield bus
    bus.close_sync(None)


@pytest.fixture
def polkit(address, bus):
    argv = ('-m', 'dbusmock', '--system', POLKIT, AUTHORITY, f'{POLKIT}.Authority')
    mock = spawn(address, *argv, stdout=subprocess.DEVNULL)
    wait_for(bus, POLKIT)
    polkit = Polkit(bus)
    polkit.allow()
    yield polkit
    stop(mock, bus, POLKIT)


@pytest.fixture
def helper(address, bus, polkit):
    process = spawn(address, '-m', 'wisp_helper')
    wait_for(bus, NAME)
    yield process
    stop(process, bus, NAME)


def test_version(bus, helper):
    args = GLib.Variant('(ss)', (NAME, 'Version'))
    properties = 'org.freedesktop.DBus.Properties'
    assert request(bus, NAME, PATH, properties, 'Get', args, '(v)') == (1,)


def test_info(bus, helper):
    (info,) = request(bus, NAME, PATH, NAME, 'GetInfo')
    assert info.keys() == {'version', 'distro', 'maintenance'}
    assert info['version'] == VERSION
    assert info['distro']
    assert isinstance(info['maintenance'], bool)


@pytest.mark.parametrize('method', ACTIONS)
def test_not_authorized(bus, helper, method):
    assert refusal(bus, method) == 'NotAuthorized'


def test_authorized(bus, helper, polkit):
    polkit.allow('grant-access')
    assert refusal(bus, 'GrantAccess') == 'Unsupported'
    assert refusal(bus, 'SetConfig') == 'NotAuthorized'


def test_polkit_request(bus, helper, polkit):
    refusal(bus, 'GrantAccess')
    refusal(bus, 'GrantAccess', interactive=True)
    subject = ('system-bus-name', {'name': bus.get_unique_name()})
    assert polkit.calls() == [
        [subject, f'{NAME}.grant-access', {}, 0, ''],
        [subject, f'{NAME}.grant-access', {}, 1, ''],
    ]


def test_busy(bus, helper, polkit):
    polkit.allow(delay=1)
    signature, args = ACTIONS['GrantAccess']
    results = []
    bus.call(
        NAME,
        PATH,
        NAME,
        'GrantAccess',
        GLib.Variant(signature, args),
        None,
        Gio.DBusCallFlags.NONE,
        10000,
        None,
        lambda bus, result: results.append(result),
    )
    assert refusal(bus, 'SetConfig') == 'Busy'
    while not results:
        GLib.MainContext.default().iteration(True)
    with pytest.raises(GLib.Error) as info:
        bus.call_finish(results[0])
    assert remote_error(info.value) == 'NotAuthorized'


def test_idle_exit(address, bus, polkit):
    process = spawn(address, '-c', SHORT_IDLE)
    wait_for(bus, NAME)
    assert process.wait(timeout=10) == 0


def test_no_exit_during_polkit_check(address, bus, polkit):
    polkit.allow(delay=3)
    process = spawn(address, '-c', SHORT_IDLE)
    wait_for(bus, NAME)
    assert refusal(bus, 'GrantAccess') == 'NotAuthorized'
    assert process.wait(timeout=10) == 0
