# SPDX-License-Identifier: GPL-2.0-or-later

from wisp_helper import maintenance


def test_find(tmp_path, monkeypatch):
    sysconfig, default = tmp_path / 'sysconfig', tmp_path / 'default'
    monkeypatch.setattr(maintenance, 'PATHS', (str(sysconfig), str(default)))
    assert maintenance.find() is None
    default.touch()
    assert maintenance.find() == str(default)
    sysconfig.touch()
    assert maintenance.find() == str(sysconfig)
