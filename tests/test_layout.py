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
    ],
)
def test_subvolumes(mountinfo, text, taken, found):
    mountinfo(text)
    assert layout.subvolumes(taken) == found


def test_unescape():
    assert layout.unescape(rb'/a\040b\011c\012d\134e\054f') == b'/a b\tc\nd\\e,f'
