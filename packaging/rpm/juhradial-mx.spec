# Fedora RPM Spec for JuhRadial MX
# Build: rpmbuild -ba juhradial-mx.spec

Name:           juhradial-mx
Version:        0.2.5
Release:        1%{?dist}
Summary:        Beautiful radial menu for Logitech MX Master mice on Linux

License:        GPL-3.0-or-later
URL:            https://github.com/JuhLabs/juhradial-mx
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildRequires:  rust
BuildRequires:  cargo
BuildRequires:  nodejs
BuildRequires:  npm
BuildRequires:  gtk4-devel
BuildRequires:  gtk4-layer-shell-devel
BuildRequires:  dbus-devel
BuildRequires:  systemd-devel
BuildRequires:  libevdev-devel

Requires:       logiops
Requires:       gtk4
Requires:       gtk4-layer-shell
Requires:       python3
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       dbus

Recommends:     ydotool

%description
JuhRadial MX brings a Logi Options+ inspired radial menu experience to Linux.
Hold the gesture button on your MX Master mouse to open a beautiful glassmorphic
radial menu overlay, then move to select actions.

Features:
- Glassmorphic radial menu with smooth animations
- Per-application profiles for context-aware actions
- Real-time battery status monitoring via HID++ protocol
- Visual DPI control with presets (400-8000 DPI)
- SmartShift scroll wheel configuration
- Native KDE Plasma and Wayland integration

%prep
%autosetup -n %{name}-%{version}

%build
# Build Rust daemon
cd daemon
cargo build --release
cd ..

# Build KWin script (optional)
if [ -d kwin-script ]; then
    cd kwin-script
    npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps
    npm run build 2>/dev/null || true
    cd ..
fi

%install
# Install daemon binary
install -Dm755 daemon/target/release/juhradiald %{buildroot}%{_bindir}/juhradiald

# Install launcher script
install -Dm755 juhradial-mx.sh %{buildroot}%{_bindir}/juhradial-mx

# Install overlay Python files
install -dm755 %{buildroot}%{_datadir}/juhradial
install -Dm644 overlay/*.py %{buildroot}%{_datadir}/juhradial/

# Install locales
if [ -d overlay/locales ]; then
    cp -r overlay/locales %{buildroot}%{_datadir}/juhradial/
fi

# Install assets
install -dm755 %{buildroot}%{_datadir}/juhradial/assets
cp -r assets/* %{buildroot}%{_datadir}/juhradial/assets/

# Install desktop file
install -Dm644 juhradial-mx.desktop %{buildroot}%{_datadir}/applications/juhradial-mx.desktop

# Install icon
install -Dm644 assets/juhradial-mx.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/juhradial-mx.svg

# Install systemd user service
install -Dm644 packaging/systemd/juhradialmx-daemon.service %{buildroot}%{_userunitdir}/juhradialmx-daemon.service

# Install udev rules
install -Dm644 packaging/udev/99-logitech-hidpp.rules %{buildroot}%{_udevrulesdir}/99-logitech-hidpp.rules

# Install default logiops config
install -Dm644 packaging/logid.cfg %{buildroot}%{_sysconfdir}/logid.cfg.juhradial

%post
# Update icon cache
/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :

# Reload udev rules
/usr/bin/udevadm control --reload-rules &>/dev/null || :
/usr/bin/udevadm trigger &>/dev/null || :

%postun
# Update icon cache
/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :

%files
%license LICENSE
%doc README.md CONTRIBUTING.md
%{_bindir}/juhradiald
%{_bindir}/juhradial-mx
%{_datadir}/juhradial/
%{_datadir}/applications/juhradial-mx.desktop
%{_datadir}/icons/hicolor/scalable/apps/juhradial-mx.svg
%{_userunitdir}/juhradialmx-daemon.service
%{_udevrulesdir}/99-logitech-hidpp.rules
%config(noreplace) %{_sysconfdir}/logid.cfg.juhradial

%changelog
* Fri Dec 13 2024 JuhLabs (Julian Hermstad) <juhlabs@example.com> - 1.0.0-1
- Initial release
- Glassmorphic radial menu overlay
- Battery status monitoring via HID++
- Settings dashboard with mouse visualization
- DPI and scroll wheel configuration
- KDE Plasma 6 integration
