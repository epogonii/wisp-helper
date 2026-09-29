# SPDX-License-Identifier: GPL-2.0-or-later

"""polkit checks and the caller's UID."""

import logging

from gi.repository import Gio, GLib

from wisp_helper import NAME

log = logging.getLogger(__name__)


def authorize(bus, invocation, action, done):
    flags = invocation.get_message().get_flags()
    interactive = bool(flags & Gio.DBusMessageFlags.ALLOW_INTERACTIVE_AUTHORIZATION)
    subject = ('system-bus-name', {'name': GLib.Variant('s', invocation.get_sender())})
    args = (subject, f'{NAME}.{action}', {}, int(interactive), '')

    def finish(bus, result):
        try:
            allowed = bus.call_finish(result).unpack()[0][0]
        except GLib.Error as error:
            log.warning('polkit: %s', error.message)
            allowed = False
        done(allowed)

    # No timeout: someone may be typing the password.
    bus.call(
        'org.freedesktop.PolicyKit1',
        '/org/freedesktop/PolicyKit1/Authority',
        'org.freedesktop.PolicyKit1.Authority',
        'CheckAuthorization',
        GLib.Variant('((sa{sv})sa{ss}us)', args),
        GLib.VariantType('((bba{ss}))'),
        Gio.DBusCallFlags.NONE,
        GLib.MAXINT,
        None,
        finish,
    )


def caller_uid(bus, sender):
    reply = bus.call_sync(
        'org.freedesktop.DBus',
        '/org/freedesktop/DBus',
        'org.freedesktop.DBus',
        'GetConnectionUnixUser',
        GLib.Variant('(s)', (sender,)),
        GLib.VariantType('(u)'),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    return reply.unpack()[0]
