# SPDX-License-Identifier: GPL-2.0-or-later

import logging
import signal

from gi.repository import Gio, GLib

from wisp_helper import NAME
from wisp_helper.service import Service


def main():
    logging.basicConfig(format='%(message)s', level=logging.INFO)
    loop = GLib.MainLoop()
    service = Service(loop.quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, service.stop)
    owner = Gio.bus_own_name(
        Gio.BusType.SYSTEM,
        NAME,
        Gio.BusNameOwnerFlags.NONE,
        service.register,
        None,
        lambda *args: loop.quit(),
    )
    loop.run()
    Gio.bus_unown_name(owner)


if __name__ == '__main__':
    main()
