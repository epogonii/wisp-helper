# SPDX-License-Identifier: GPL-2.0-or-later

project('wisp-helper',
  version: '0.1.0',
  license: 'GPL-2.0-or-later',
  meson_version: '>= 1.0',
)

python = import('python').find_installation('python3')

prefix = get_option('prefix')
datadir = prefix / get_option('datadir')
libexecdir = prefix / get_option('libexecdir')
# Not libdir, units go to /usr/lib on lib64 systems too.
unitdir = prefix / 'lib' / 'systemd' / 'system'

python.install_sources(
  'wisp_helper/__init__.py',
  'wisp_helper/__main__.py',
  'wisp_helper/errors.py',
  'wisp_helper/layout.py',
  'wisp_helper/maintenance.py',
  'wisp_helper/polkit.py',
  'wisp_helper/service.py',
  'wisp_helper/snapper.py',
  'wisp_helper/swap.py',
  'wisp_helper/validate.py',
  subdir: 'wisp_helper',
)

install_data('wisp-helper',
  install_dir: libexecdir,
  install_mode: 'rwxr-xr-x',
)

install_data('data/io.github.epogonii.WispHelper.service',
  install_dir: datadir / 'dbus-1' / 'system-services',
)
install_data('data/io.github.epogonii.WispHelper.conf',
  install_dir: datadir / 'dbus-1' / 'system.d',
)
install_data('data/io.github.epogonii.WispHelper.policy',
  install_dir: datadir / 'polkit-1' / 'actions',
)

configure_file(
  input: 'data/wisp-helper.service.in',
  output: 'wisp-helper.service',
  configuration: {'libexecdir': libexecdir},
  install_dir: unitdir,
)

pytest = find_program('pytest-3', 'pytest', required: false)
if pytest.found()
  test('pytest', pytest,
    args: ['-q', '-p', 'no:cacheprovider', meson.project_source_root() / 'tests'],
    workdir: meson.project_source_root(),
  )
endif
