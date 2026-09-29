# SPDX-License-Identifier: GPL-2.0-or-later

import pytest

from wisp_helper import layout

# Fedora 45 as a service with PrivateTmp sees it, with /tmp and /var/tmp of its own.
FEDORA = rb"""
609 227 0:36 /root / rw,relatime shared:591 master:1 - btrfs /dev/nvme0n1p3 rw,seclabel,compress=zstd:1,ssd,space_cache=v2,subvolid=287,subvol=/root
854 609 0:50 / /tmp rw,nosuid,nodev shared:615 master:118 - tmpfs tmpfs rw,seclabel,nr_inodes=1048576,inode64,usrquota
855 609 0:36 /home /home rw,relatime shared:617 master:160 - btrfs /dev/nvme0n1p3 rw,seclabel,compress=zstd:1,ssd,space_cache=v2,subvolid=256,subvol=/home
856 609 259:2 / /boot rw,relatime shared:618 master:165 - ext4 /dev/nvme0n1p2 rw,seclabel
857 856 259:1 / /boot/efi rw,relatime shared:619 master:170 - vfat /dev/nvme0n1p1 rw,fmask=0077,dmask=0077,codepage=437,iocharset=ascii,shortname=winnt,errors=remount-ro
871 854 0:50 /systemd-private-aeddb912d3984eac91b604e0688e82d0-wisp-helper.service-xFVlt7/tmp /tmp rw,nosuid,nodev shared:616 master:118 - tmpfs tmpfs rw,seclabel,nr_inodes=1048576,inode64,usrquota
873 609 0:36 /root/var/tmp/systemd-private-aeddb912d3984eac91b604e0688e82d0-wisp-helper.service-3GSS0P/tmp /var/tmp rw,relatime shared:636 master:1 - btrfs /dev/nvme0n1p3 rw,seclabel,compress=zstd:1,ssd,space_cache=v2,subvolid=287,subvol=/root
"""  # noqa: E501

TOP_MOUNT = rb"""880 609 0:36 / /run/wisp-helper/top-x1 rw - btrfs /dev/nvme0n1p3 rw,subvolid=5,subvol=/
"""  # noqa: E501

# Like openSUSE, where / is a snapshot and /.snapshots has a mount of its own.
OPENSUSE = rb"""
23 1 0:22 /@/.snapshots/1/snapshot / rw,relatime shared:1 - btrfs /dev/vda2 rw,space_cache=v2,subvolid=267,subvol=/@/.snapshots/1/snapshot
45 23 0:22 /@/.snapshots /.snapshots rw,relatime shared:24 - btrfs /dev/vda2 rw,space_cache=v2,subvolid=266,subvol=/@/.snapshots
46 23 0:22 /@/home /home rw,relatime shared:25 - btrfs /dev/vda2 rw,space_cache=v2,subvolid=264,subvol=/@/home
47 23 0:22 /@/var /var rw,relatime shared:26 - btrfs /dev/vda2 rw,space_cache=v2,subvolid=258,subvol=/@/var
48 23 0:22 /@/boot/grub2/x86_64-efi /boot/grub2/x86_64-efi rw,relatime shared:27 - btrfs /dev/vda2 rw,space_cache=v2,subvolid=260,subvol=/@/boot/grub2/x86_64-efi
"""  # noqa: E501

ODD = rb"""
90 23 0:40 / /run/media/ann/My\040Disk rw,nosuid,nodev,relatime shared:50 - btrfs /dev/sdb1 rw,subvolid=5,subvol=/
91 23 0:41 / /mnt/new\012line rw shared:51 - btrfs /dev/sdc1 rw,subvolid=5,subvol=/
92 23 0:42 / /mnt/back\134slash rw shared:52 - btrfs /dev/sdd1 rw,subvolid=5,subvol=/
93 23 0:43 / /mnt/quote" rw shared:53 - btrfs /dev/sde1 rw,subvolid=5,subvol=/
94 23 0:44 / /mnt/<ff> rw shared:54 - btrfs /dev/sdf1 rw,subvolid=5,subvol=/
95 23 0:45 /a,b /mnt/comma rw shared:55 - btrfs /dev/sdg1 rw,subvolid=256,subvol=/a\054b
96 23 0:46 / /mnt/under rw shared:56 - btrfs /dev/sdh1 rw,subvolid=5,subvol=/
97 96 0:47 / /mnt/under rw shared:57 - tmpfs tmpfs rw
98 23 0:48 / /mnt/over rw shared:58 - tmpfs tmpfs rw
99 98 0:49 / /mnt/over rw shared:59 - btrfs /dev/sdi1 rw,subvolid=5,subvol=/
100 23 0:50 /@home/.snapshots /home/.snapshots rw shared:60 - btrfs /dev/vda2 rw,subvolid=270,subvol=/@home/.snapshots
101 23 0:51 / /mnt/nameless rw shared:61 - tmpfs  rw
102 23 0:52 / /mnt/plain rw - btrfs /dev/sdj1 rw,subvolid=5,subvol=/
""".replace(b'<ff>', b'\xff')  # noqa: E501


@pytest.fixture
def mountinfo(tmp_path, monkeypatch):
    path = tmp_path / 'mountinfo'
    monkeypatch.setattr(layout, 'MOUNTINFO', str(path))
    return lambda text: path.write_bytes(text.lstrip())


@pytest.mark.parametrize(
    'text, taken, found',
    [
        (FEDORA, [], ['/', '/home']),
        (FEDORA, ['/'], ['/home']),
        (FEDORA, ['/', '/home'], []),
        (OPENSUSE, ['/'], ['/boot/grub2/x86_64-efi', '/home', '/var']),
        (ODD, [], ['/mnt/comma', '/mnt/over', '/mnt/plain', '/run/media/ann/My Disk']),
        # The top a swap mounts for a moment.
        (FEDORA + TOP_MOUNT, ['/', '/home'], []),
    ],
)
def test_subvolumes(mountinfo, text, taken, found):
    mountinfo(text)
    assert layout.subvolumes(taken) == found


def test_unescape():
    assert layout.unescape(rb'/a\040b\011c\012d\134e\054f') == b'/a b\tc\nd\\e,f'


FEDORA_CMDLINE = (
    'BOOT_IMAGE=(hd0,gpt2)/vmlinuz-6.17.1 root=UUID=1b2c ro rootflags=subvol=root rhgb quiet'
)
FEDORA_FSTAB = """\
# /etc/fstab
UUID=1b2c /     btrfs subvol=root,compress=zstd:1 0 0
UUID=9f00 /boot ext4  defaults                    1 2
UUID=1b2c /home btrfs subvol=home,compress=zstd:1 0 0
"""
OPENSUSE_FSTAB = (
    'UUID=77aa / btrfs defaults 0 0\nUUID=77aa /.snapshots btrfs subvol=/@/.snapshots 0 0\n'
)
CONFIGS = {'root': '/', 'home': '/home'}
DEFAULT = {'number': 1, 'default': True, 'read-only': False, 'running': 1, 'pending': False}

# After a swap: the root the machine runs from was renamed into the new one's .snapshots.
SWAPPED = FEDORA.replace(b'/root / rw', b'/root/.snapshots/26/snapshot / rw', 1).replace(
    b'subvol=/root\n', b'subvol=/root/.snapshots/26/snapshot\n', 1
)
ARCH = rb"""
30 1 0:25 /@ / rw,relatime shared:1 - btrfs /dev/sda2 rw,subvolid=256,subvol=/@
31 30 0:25 /@snapshots /.snapshots rw,relatime shared:2 - btrfs /dev/sda2 rw,subvolid=258,subvol=/@snapshots
"""  # noqa: E501
TOP = rb"""
30 1 0:25 / / rw,relatime shared:1 - btrfs /dev/sda2 rw,subvolid=5,subvol=/
"""
EXT4 = rb"""
30 1 8:2 / / rw,relatime shared:1 - ext4 /dev/sda2 rw
"""


@pytest.fixture
def system(tmp_path, monkeypatch, mountinfo):
    cmdline, fstab = tmp_path / 'cmdline', tmp_path / 'fstab'
    monkeypatch.setattr(layout, 'CMDLINE', str(cmdline))
    monkeypatch.setattr(layout, 'FSTAB', str(fstab))
    monkeypatch.setattr(layout, 'PENDING', str(tmp_path / 'rollback-pending'))
    inodes = {'/.snapshots': 256}
    monkeypatch.setattr(layout, 'inode', lambda path: inodes.get(path, 0))

    def system(text=FEDORA, flags=FEDORA_CMDLINE, table=FEDORA_FSTAB):
        mountinfo(text)
        cmdline.write_text(flags + '\n')
        fstab.write_text(table)
        return inodes

    return system


def rollback(configs=CONFIGS, row=None):
    return layout.rollback(configs, lambda config: row)


def test_swap(system):
    system()
    assert rollback() == ('swap', '')
    assert not layout.pending()
    system(flags=FEDORA_CMDLINE.replace('subvol=root', 'subvol=/root'))
    assert rollback() == ('swap', '')


@pytest.mark.parametrize(
    'text, flags, table, why',
    [
        (
            FEDORA,
            FEDORA_CMDLINE.replace('subvol=root', 'subvol=root,subvolid=287'),
            FEDORA_FSTAB,
            'by-id',
        ),
        (FEDORA, FEDORA_CMDLINE, FEDORA_FSTAB.replace('subvol=root', 'subvolid=287'), 'by-id'),
        (FEDORA, FEDORA_CMDLINE.replace(' rootflags=subvol=root', ''), FEDORA_FSTAB, 'cmdline'),
        (FEDORA, FEDORA_CMDLINE.replace('subvol=root', 'compress=zstd'), FEDORA_FSTAB, 'cmdline'),
        (TOP, 'root=/dev/sda2', '', 'top-level'),
        (EXT4, 'root=/dev/sda2', '', 'not-btrfs'),
        (ARCH, 'root=/dev/sda2 rootflags=subvol=@', '', 'snapshots-mounted'),
    ],
)
def test_no_swap(system, text, flags, table, why):
    system(text, flags, table)
    assert rollback() == ('none', why)


# Missing, or the stand-in a snapshot has for it.
@pytest.mark.parametrize('number', [0, 2])
def test_snapshots_missing(system, number):
    system()['/.snapshots'] = number
    assert rollback() == ('none', 'snapshots-missing')


def test_no_root_config(system):
    system()

    def default(config):
        raise AssertionError(config)

    assert layout.rollback({'home': '/home'}, default) == ('none', 'no-root-config')


def test_native(system):
    system(OPENSUSE, 'root=UUID=77aa splash=silent', OPENSUSE_FSTAB)
    assert rollback(row=DEFAULT) == ('native', '')
    # Booted from a read-only snapshot out of the boot menu.
    system(OPENSUSE, 'root=UUID=77aa rootflags=subvol=@/.snapshots/1/snapshot', OPENSUSE_FSTAB)
    assert rollback(row=DEFAULT) == ('native', '')


# After snapper rollback from a terminal. Where fstab names the root, the
# default does not matter.
def test_native_pending(system):
    system(OPENSUSE, 'root=UUID=77aa', OPENSUSE_FSTAB)
    assert rollback(row={**DEFAULT, 'pending': True}) == ('none', 'pending')
    assert not layout.pending()
    system()
    assert rollback(row={**DEFAULT, 'pending': True}) == ('swap', '')


# A root like @ is no snapshot. Named on the command line, it is what starts
# again, whatever the default.
def test_root_named(system):
    at = OPENSUSE.replace(b'/@/.snapshots/1/snapshot / ', b'/@ / ', 1).replace(
        b'subvol=/@/.snapshots/1/snapshot\n', b'subvol=/@\n', 1
    )
    row = {**DEFAULT, 'running': None, 'pending': True}
    system(at, 'root=UUID=77aa', OPENSUSE_FSTAB)
    assert rollback(row=row) == ('none', 'pending')
    system(at, 'root=UUID=77aa rootflags=subvol=@', OPENSUSE_FSTAB)
    assert rollback(row=row) == ('none', 'rootflags')
    assert not layout.pending()
    system(at, 'root=UUID=77aa rootflags=subvol=@', OPENSUSE_FSTAB.splitlines(True)[1])
    assert rollback(row=row) == ('none', 'rootflags')
    system(table='UUID=1b2c / btrfs defaults 0 0\n')
    assert rollback(row=row) == ('swap', '')


# A snapshot once made default, and fstab asking for the root by name anyway.
def test_default_overruled(system):
    system()
    assert rollback(row=DEFAULT) == ('swap', '')
    system()['/.snapshots'] = 0
    assert rollback(row=DEFAULT) == ('none', 'fstab')


def test_no_native(system):
    system(OPENSUSE, 'root=UUID=77aa', OPENSUSE_FSTAB)
    assert rollback(row={**DEFAULT, 'read-only': True}) == ('none', 'transactional')
    system(OPENSUSE, 'root=UUID=77aa', 'UUID=77aa / btrfs subvol=@/.snapshots/1/snapshot 0 0\n')
    assert rollback(row=DEFAULT) == ('none', 'fstab')


def test_pending(system, tmp_path):
    system(SWAPPED)
    assert layout.pending()
    assert rollback() == ('none', 'pending')
    system()
    (tmp_path / 'rollback-pending').touch()
    assert layout.pending()
    assert rollback(row=DEFAULT) == ('none', 'pending')


# ostree before composefs: / is a directory of the subvolume, bound there.
def test_not_pending_bound(system):
    system(FEDORA.replace(b'/root / rw', b'/root/ostree/deploy/fedora/deploy/1a2b.0 / rw', 1))
    assert not layout.pending()


def test_no_files(system, tmp_path):
    system()
    (tmp_path / 'fstab').unlink()
    assert rollback() == ('swap', '')
