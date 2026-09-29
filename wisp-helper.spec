Name:           wisp-helper
Version:        0.1.0
Release:        1%{?dist}
Summary:        Root helper for the Wisp GNOME Shell extension
License:        GPL-2.0-or-later
URL:            https://github.com/epogonii/wisp-helper
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  meson
BuildRequires:  python3-dbusmock
BuildRequires:  python3-pytest
BuildRequires:  systemd-rpm-macros
%if 0%{?suse_version}
BuildRequires:  dbus-1-daemon
BuildRequires:  python-rpm-macros
BuildRequires:  python3-gobject
Requires:       btrfsprogs
Requires:       python3-gobject
%else
BuildRequires:  dbus-daemon
BuildRequires:  python3-devel
BuildRequires:  python3-gobject-base
Requires:       btrfs-progs
Requires:       grubby
Requires:       python3-gobject-base
%endif
Requires:       polkit
Requires:       snapper
Recommends:     btrfsmaintenance
%{?systemd_ordering}

%description
wisp-helper does the work that needs root for Wisp, the snapper extension
for GNOME Shell: access to snapshots, snapper configs, restoring files,
rollback and the btrfs maintenance schedule. It is a system D-Bus service
that starts on demand, and every change goes through polkit.

%prep
%autosetup

%build
%meson
%meson_build

%install
%meson_install

%check
%meson_test

# No restart, the helper exits by itself after a minute of idle.
%if 0%{?suse_version}
%pre
%service_add_pre wisp-helper.service

%post
%service_add_post wisp-helper.service

%preun
%service_del_preun wisp-helper.service

%postun
%service_del_postun_without_restart wisp-helper.service
%else
%post
%systemd_post wisp-helper.service

%preun
%systemd_preun wisp-helper.service

%postun
%systemd_postun wisp-helper.service
%endif

%files
%license LICENSE
%doc README.md
%{_libexecdir}/wisp-helper
%{python3_sitelib}/wisp_helper/
%{_datadir}/dbus-1/system-services/io.github.epogonii.WispHelper.service
%{_datadir}/dbus-1/system.d/io.github.epogonii.WispHelper.conf
%{_datadir}/polkit-1/actions/io.github.epogonii.WispHelper.policy
%{_unitdir}/wisp-helper.service

%changelog
* Tue Sep 29 2026 Evghenii Pogonii <epogonii@gmail.com> - 0.1.0-1
- First release
