# wisp-helper

Helper for [Wisp](https://github.com/epogonii/wisp), the snapper extension for
GNOME Shell. It does the things that need root.

extensions.gnome.org doesn't accept extensions that run commands as root, so
that part of Wisp lives here. wisp-helper is a system D-Bus service. D-Bus
starts it on the first call from Wisp, and it exits after a minute of idle.
Anything that changes the system goes through polkit first.

Version 0.1.0 is packaged for Fedora and openSUSE. Wisp doesn't use it yet,
that comes with Wisp 1.1.0.

## What it does

- add your user to `ALLOW_USERS` of a config
- change timeline and cleanup settings
- create and delete configs
- restore files from a snapshot
- roll back (snapper rollback on openSUSE, subvolume swap on Fedora)
- set the btrfsmaintenance schedule

Methods take config names and snapshot numbers. The only paths it accepts are
the files to restore, which must be inside the config's subvolume, and the
subvolume for a new config, which must be one the helper listed itself. It
doesn't use a shell. Deleting a config and rolling back ask for the password
every time, the rest is remembered for a few minutes.

## Install

Fedora 43 or newer, from [COPR](https://copr.fedorainfracloud.org/coprs/swink/wisp-helper/):

```sh
sudo dnf copr enable swink/wisp-helper
sudo dnf install wisp-helper
```

openSUSE Tumbleweed, from [OBS](https://build.opensuse.org/package/show/home:swink/wisp-helper):

```sh
sudo zypper addrepo https://download.opensuse.org/repositories/home:swink/openSUSE_Tumbleweed/home:swink.repo
sudo zypper install wisp-helper
```

On Leap 16.0 use `16.0` in the URL instead of `openSUSE_Tumbleweed`. Arch comes
later.

From source with meson. Use `--prefix=/usr`, polkit and the system bus don't
read files from `/usr/local`.

```sh
meson setup build --prefix=/usr
meson compile -C build
sudo meson install -C build
```

Runtime dependencies: Python 3, PyGObject, snapper, btrfs-progs, polkit, and
grubby for rollback on Fedora.

## License

GPL-2.0-or-later, same as Wisp.
