# SPDX-License-Identifier: GPL-2.0-or-later

import pytest

from wisp_helper import errors, validate

CONFIGS = {'root', 'home'}


def test_error_names():
    names = {cls.dbus_name() for cls in errors.Error.__subclasses__()}
    assert names == {
        f'io.github.epogonii.WispHelper.Error.{name}'
        for name in ('NotAuthorized', 'Invalid', 'Busy', 'Unsupported', 'Pending', 'Failed')
    }


def test_config():
    assert validate.config('root', CONFIGS) == 'root'
    with pytest.raises(errors.Invalid):
        validate.config('srv', CONFIGS)


@pytest.mark.parametrize('name', ['srv', 'var-log', 'data_2', 'home.old', 'A', 'x' * 64])
def test_new_config(name):
    assert validate.new_config(name, CONFIGS) == name


@pytest.mark.parametrize(
    'name',
    [
        '',
        'root',
        '.',
        '..',
        '.hidden',
        '-c',
        '_x',
        'a/b',
        '../etc',
        'a b',
        'a\nb',
        'a\0b',
        'snäp',
        'x' * 65,
    ],
)
def test_new_config_refused(name):
    with pytest.raises(errors.Invalid):
        validate.new_config(name, CONFIGS)
