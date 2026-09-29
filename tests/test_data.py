# SPDX-License-Identifier: GPL-2.0-or-later

import configparser
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import wisp_helper
from wisp_helper import NAME

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'

ALLOW_ACTIVE = {
    'grant-access': 'auth_admin_keep',
    'set-config': 'auth_admin_keep',
    'create-config': 'auth_admin_keep',
    'delete-config': 'auth_admin',
    'undo-change': 'auth_admin_keep',
    'rollback': 'auth_admin',
    'set-maintenance': 'auth_admin_keep',
}


def ini(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(path)
    return parser


def test_policy_actions():
    root = ET.parse(DATA / f'{NAME}.policy').getroot()
    found = {}
    for action in root.iter('action'):
        defaults = action.find('defaults')
        assert defaults.findtext('allow_any') == 'auth_admin'
        assert defaults.findtext('allow_inactive') == 'auth_admin'
        assert action.findtext('description')
        assert action.findtext('message')
        found[action.get('id').removeprefix(f'{NAME}.')] = defaults.findtext('allow_active')
    assert found == ALLOW_ACTIVE


def test_bus_policy():
    root = ET.parse(DATA / f'{NAME}.conf').getroot()
    (owner,) = root.findall("policy[@user='root']")
    assert [rule.attrib for rule in owner] == [{'own': NAME}]
    (default,) = root.findall("policy[@context='default']")
    assert all(rule.tag == 'allow' for rule in default)
    assert all(rule.get('send_destination') == NAME for rule in default)
    assert {rule.get('send_interface') for rule in default} == {
        NAME,
        'org.freedesktop.DBus.Introspectable',
        'org.freedesktop.DBus.Properties',
        'org.freedesktop.DBus.Peer',
    }


def test_activation_file():
    service = ini(DATA / f'{NAME}.service')['D-BUS Service']
    assert service['Name'] == NAME
    assert service['User'] == 'root'
    assert service['SystemdService'] == 'wisp-helper.service'


def test_unit():
    unit = ini(DATA / 'wisp-helper.service.in')
    assert 'Install' not in unit
    assert unit['Service']['Type'] == 'dbus'
    assert unit['Service']['BusName'] == NAME
    assert unit['Service']['ExecStart'] == '@libexecdir@/wisp-helper'
    # Stopping the helper must not kill snapper or btrfs halfway.
    assert unit['Service']['KillMode'] == 'mixed'


def test_meson_version():
    meson = (ROOT / 'meson.build').read_text()
    assert re.search(r"^\s*version: '([^']+)'", meson, re.M)[1] == wisp_helper.VERSION


def test_meson_installs_every_module():
    meson = (ROOT / 'meson.build').read_text()
    listed = set(re.findall(r"'wisp_helper/(\w+\.py)'", meson))
    assert listed == {path.name for path in (ROOT / 'wisp_helper').glob('*.py')}
