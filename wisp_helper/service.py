# SPDX-License-Identifier: GPL-2.0-or-later

"""The D-Bus object and its methods."""

import logging
import platform
import threading

from gi.repository import Gio, GLib

from wisp_helper import API_VERSION, PATH, VERSION, maintenance, polkit, snapper, validate
from wisp_helper.errors import Busy, Error, Failed, NotAuthorized, Unsupported

log = logging.getLogger(__name__)

XML = """
<node>
  <interface name="io.github.epogonii.WispHelper">
    <property name="Version" type="u" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="const"/>
    </property>
    <method name="GetInfo">
      <arg name="info" type="a{sv}" direction="out"/>
    </method>
    <method name="GrantAccess">
      <arg name="config" type="s" direction="in"/>
    </method>
    <method name="SetConfig">
      <arg name="config" type="s" direction="in"/>
      <arg name="values" type="a{ss}" direction="in"/>
    </method>
    <method name="ListSubvolumes">
      <arg name="subvolumes" type="as" direction="out"/>
    </method>
    <method name="CreateConfig">
      <arg name="config" type="s" direction="in"/>
      <arg name="subvolume" type="s" direction="in"/>
    </method>
    <method name="DeleteConfig">
      <arg name="config" type="s" direction="in"/>
    </method>
    <method name="UndoChange">
      <arg name="config" type="s" direction="in"/>
      <arg name="from" type="u" direction="in"/>
      <arg name="to" type="u" direction="in"/>
      <arg name="paths" type="as" direction="in"/>
    </method>
    <method name="PlanRollback">
      <arg name="config" type="s" direction="in"/>
      <arg name="number" type="u" direction="in"/>
      <arg name="plan" type="a{sv}" direction="out"/>
    </method>
    <method name="Rollback">
      <arg name="config" type="s" direction="in"/>
      <arg name="number" type="u" direction="in"/>
      <arg name="result" type="a{sv}" direction="out"/>
    </method>
    <method name="SetMaintenance">
      <arg name="values" type="a{ss}" direction="in"/>
    </method>
  </interface>
</node>
"""

# Methods that change something, with their polkit actions.
ACTIONS = {
    'GrantAccess': 'grant-access',
    'SetConfig': 'set-config',
    'CreateConfig': 'create-config',
    'DeleteConfig': 'delete-config',
    'UndoChange': 'undo-change',
    'Rollback': 'rollback',
    'SetMaintenance': 'set-maintenance',
}

# Seconds with nothing to do before the service quits. The next call starts it again.
IDLE = 60


def distro():
    try:
        return platform.freedesktop_os_release().get('ID', 'linux')
    except OSError:
        return 'linux'


def unwritten(*args):
    raise Unsupported('not written yet')


class Call:
    def __init__(self, connection, invocation):
        self.invocation = invocation
        self.method = invocation.get_method_name()
        self.args = invocation.get_parameters().unpack()
        self.uid = polkit.caller_uid(connection, invocation.get_sender())

    def __str__(self):
        args = ', '.join(map(repr, self.args))
        return f'{self.method}({args}) from uid {self.uid}'

    def reply(self, value):
        log.info('%s: ok', self)
        self.invocation.return_value(value)

    def fail(self, error):
        if not isinstance(error, Error):
            log.error('%s failed', self, exc_info=error)
            error = Failed(str(error))
        log.info('%s: %s: %s', self, type(error).__name__, error)
        self.invocation.return_dbus_error(error.dbus_name(), str(error))


class Service:
    def __init__(self, quit):
        self.quit = quit
        self.busy = False
        self.timer = 0

    def register(self, connection, name):
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        connection.register_object(
            PATH, info.interfaces[0], self.on_call, self.on_get_property, None
        )
        self.restart_timer()

    def restart_timer(self):
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add_seconds(IDLE, self.on_idle)

    def on_idle(self):
        if self.busy:
            return GLib.SOURCE_CONTINUE
        log.info('Nothing to do for %d s, quitting', IDLE)
        self.timer = 0
        self.quit()
        return GLib.SOURCE_REMOVE

    def on_get_property(self, connection, sender, path, interface, name):
        return GLib.Variant('u', API_VERSION)

    def on_call(self, connection, sender, path, interface, method, params, invocation):
        self.restart_timer()
        call = Call(connection, invocation)
        handler = getattr(self, method, None)
        try:
            if method not in ACTIONS:
                call.reply((handler or unwritten)(call, *call.args))
                return
            if self.busy:
                raise Busy('another action is running')
            # The handler checks the arguments and returns the work to run after polkit.
            work = handler(call, *call.args) if handler else unwritten
        except Exception as error:
            call.fail(error)
            return
        self.busy = True
        polkit.authorize(
            connection,
            invocation,
            ACTIONS[method],
            lambda allowed: self.authorized(call, work, allowed),
        )

    def authorized(self, call, work, allowed):
        if allowed:
            threading.Thread(target=self.run, args=(call, work)).start()
        else:
            self.finish(call, NotAuthorized('not authorized'))

    def run(self, call, work):
        try:
            result = work()
        except Exception as error:
            result = error
        GLib.idle_add(self.finish, call, result)

    def finish(self, call, result):
        self.busy = False
        self.restart_timer()
        if isinstance(result, Exception):
            call.fail(result)
        else:
            call.reply(result)
        return GLib.SOURCE_REMOVE

    def GetInfo(self, call):
        info = {
            'version': GLib.Variant('s', VERSION),
            'distro': GLib.Variant('s', distro()),
            'maintenance': GLib.Variant('b', maintenance.find() is not None),
        }
        return GLib.Variant('(a{sv})', (info,))

    def GrantAccess(self, call, config):
        user = validate.user(call.uid)
        validate.config(config, snapper.configs())

        def work():
            values = snapper.allow_user(snapper.get_config(config), user)
            if values:
                snapper.set_config(config, values)

        return work
