# SPDX-License-Identifier: GPL-2.0-or-later

"""Editing the btrfsmaintenance file."""

import errno
import os
import re
import shutil
import stat
import tempfile

from wisp_helper.snapper import ENV, run

PATHS = ('/etc/sysconfig/btrfsmaintenance', '/etc/default/btrfsmaintenance')
SYSTEMCTL = shutil.which('systemctl', path=ENV['PATH'])
LABEL = 'security.selinux'


def find():
    for path in PATHS:
        if os.path.exists(path):
            return path
    return None


# Only the lines of these keys change, comments and order stay.
def set_values(path, values):
    with open(path, encoding='utf-8', errors='surrogateescape') as file:
        text = file.read()
    for key, value in values.items():
        line = f'{key}="{value}"'
        text, count = re.subn(rf'^{key}=.*$', lambda match, line=line: line, text, flags=re.M)
        if count == 0:
            text += ('\n' if text and not text.endswith('\n') else '') + line + '\n'
    replace_like(path, text)


# A new file swapped in, so a crash never leaves half of one.
def replace_like(path, text):
    info = os.stat(path)
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.wisp-')
    try:
        with open(fd, 'w', encoding='utf-8', errors='surrogateescape') as file:
            file.write(text)
            file.flush()
            os.fchown(fd, info.st_uid, info.st_gid)
            os.fchmod(fd, stat.S_IMODE(info.st_mode))
            copy_label(path, fd)
            os.fsync(fd)
        os.replace(temp, path)
    except BaseException:
        os.unlink(temp)
        raise


def copy_label(path, fd):
    try:
        label = os.getxattr(path, LABEL)
    except OSError as error:
        # No SELinux here.
        if error.errno in (errno.ENODATA, errno.ENOTSUP):
            return
        raise
    os.setxattr(fd, LABEL, label)


# The path unit that would run it by itself is off by default on Fedora.
def refresh():
    run([SYSTEMCTL, 'start', 'btrfsmaintenance-refresh.service'])
