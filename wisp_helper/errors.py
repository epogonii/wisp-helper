# SPDX-License-Identifier: GPL-2.0-or-later

from wisp_helper import NAME


class Error(Exception):
    @classmethod
    def dbus_name(cls):
        return f'{NAME}.Error.{cls.__name__}'


class NotAuthorized(Error):
    pass


class Invalid(Error):
    pass


class Busy(Error):
    pass


class Unsupported(Error):
    pass


class Pending(Error):
    pass


# The message is the tail of the failed command's stderr.
class Failed(Error):
    pass
