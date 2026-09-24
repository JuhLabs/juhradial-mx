# Fedora RPM Spec for JuhRadial MX
# Build: rpmbuild -ba juhradial-mx.spec

Name:           juhradial-mx
Version:        0.4.5~beta.1
Release:        1%{?dist}
Summary:        Beautiful radial menu for Logitech MX Master mice on Linux

License:        GPL-3.0-or-later
URL:            https://github.com/JuhLabs/juhradial-mx
Source0:        %{url}/archive/v%{version_no_tilde}/%{name}-%{version_no_tilde}.tar.gz

BuildRequires:  rust
BuildRequires:  cargo
BuildRequires:  nodejs
BuildRequires:  npm
BuildRequires:  gtk4-devel
BuildRequires:  gtk4-layer-shell-devel
BuildRequires:  dbus-devel
BuildRequires:  systemd-devel
BuildRequires:  libevdev-devel

Requires:       gtk4
Requires:       gtk4-layer-shell
Requires:       python3
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       python3-cryptography
Requires:       python3-pyqt6
Requires:       qt6-qtsvg
Requires:       qt6-qtdeclarative
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
%autosetup -n %{name}-%{version_no_tilde}

%build
# The source archive must include the sibling MX Keypad crate.
test -f crates/mx-keypad/Cargo.toml
# Build Rust daemon
cd daemon
cargo build --release --locked
cd ..

# Build KWin script (optional)
if [ -d kwin-script ]; then
    cd kwin-script
    npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps
    npm run build 2>/dev/null || true
    cd ..
fi

%check
cargo test --locked --manifest-path crates/mx-keypad/Cargo.toml

%install
# Install daemon binary
install -Dm755 daemon/target/release/juhradiald %{buildroot}%{_bindir}/juhradiald

# Install launcher scripts
install -Dm755 scripts/juhradial-mx.sh %{buildroot}%{_bindir}/juhradial-mx
install -Dm755 scripts/juhradial-settings.sh %{buildroot}%{_bindir}/juhradial-settings

# Install overlay Python files
install -dm755 %{buildroot}%{_datadir}/juhradial
install -Dm644 overlay/*.py %{buildroot}%{_datadir}/juhradial/

# Install flow module
cp -r overlay/flow %{buildroot}%{_datadir}/juhradial/flow

# Install locales
if [ -d overlay/locales ]; then
    cp -r overlay/locales %{buildroot}%{_datadir}/juhradial/
fi

# Install assets
install -dm755 %{buildroot}%{_datadir}/juhradial/assets
cp -r assets/* %{buildroot}%{_datadir}/juhradial/assets/

# Qt/QML settings app (tools/ and __pycache__ excluded); the overlay also
# resolves wheel skins under %{_datadir}/juhradial/assets/wheels
install -dm755 %{buildroot}%{_datadir}/juhradial/settings-qt
install -Dm644 settings-qt/main.py %{buildroot}%{_datadir}/juhradial/settings-qt/main.py
install -Dm644 settings-qt/VERSION %{buildroot}%{_datadir}/juhradial/settings-qt/VERSION
cp -r settings-qt/bridge settings-qt/qml settings-qt/assets %{buildroot}%{_datadir}/juhradial/settings-qt/
find %{buildroot}%{_datadir}/juhradial/settings-qt -type d -name __pycache__ -exec rm -rf {} +
cp -r settings-qt/assets/wheels %{buildroot}%{_datadir}/juhradial/assets/

# Install desktop files
install -Dm644 packaging/juhradial-mx.desktop %{buildroot}%{_datadir}/applications/juhradial-mx.desktop
install -Dm644 packaging/org.kde.juhradialmx.settings.desktop %{buildroot}%{_datadir}/applications/org.kde.juhradialmx.settings.desktop

# Install icon
install -Dm644 assets/juhradial-mx.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/juhradial-mx.svg

# Install systemd user service
install -Dm644 packaging/systemd/juhradialmx-daemon.service %{buildroot}%{_userunitdir}/juhradialmx-daemon.service
# The unit names the curl installer's /usr/local/bin; the package puts the daemon in %{_bindir}.
sed -i 's|^ExecStart=/usr/local/bin/juhradiald|ExecStart=%{_bindir}/juhradiald|' %{buildroot}%{_userunitdir}/juhradialmx-daemon.service

# Install udev rules
install -Dm644 packaging/udev/99-juhradialmx.rules %{buildroot}%{_udevrulesdir}/99-juhradialmx.rules
install -Dm644 packaging/udev/60-ydotool-uinput.rules %{buildroot}%{_udevrulesdir}/60-ydotool-uinput.rules


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
%{_bindir}/juhradial-settings
%{_datadir}/juhradial/
%{_datadir}/applications/juhradial-mx.desktop
%{_datadir}/applications/org.kde.juhradialmx.settings.desktop
%{_datadir}/icons/hicolor/scalable/apps/juhradial-mx.svg
%{_userunitdir}/juhradialmx-daemon.service
%{_udevrulesdir}/99-juhradialmx.rules
%{_udevrulesdir}/60-ydotool-uinput.rules
%changelog
* Thu Sep 24 2026 Julian Hermstad <dev@juhlabs.com> - 0.4.5~beta.1-1
- Beta of 0.4.5: new Qt/QML settings app, twelve themes, 18 languages
- MX Keypad support: key art on the LCD keys, pages, app profiles, packs
- Deeper MX Master 4 haptics, directional gestures, custom actions,
  per-app buttons and app profiles with their own ring
- Macros record and play back on Wayland; gaming mode; export and
  import of the whole setup; Easy-Switch moves the keyboard along
- Devices tab with battery, keyboard backlight, receivers and firmware
- User-mode install for Bazzite and Fedora Atomic (install.sh --user)
- Native radial menu on niri, NixOS module, GNOME 51 cursor helper
- Fixes for scaled displays, menu latency and Easy-Switch reconnects

* Sat Aug 15 2026 Julian Hermstad <dev@juhlabs.com> - 0.4.3-1
- Editable quick links in the radial submenu (#105)
- Radial menu performance wave: frame-coalesced cursor updates, skipped
  stable repaints, async haptics and media state, native KWin D-Bus calls
- Lower idle footprint: Flow status writes, edge polling cadence, xprop -spy

* Fri Aug 14 2026 Julian Hermstad <dev@juhlabs.com> - 0.4.2-1
- Gesture button survives the power switch and radio sleep (#102)
- PKGBUILD and RPM spec install the current udev rules file (#89)
- Debian/Ubuntu installs pull python3-gi-cairo for the Settings UI (#100)

* Tue Jul 21 2026 Julian Hermstad <dev@juhlabs.com> - 0.4.1-1
- Radial menu opens at the cursor on GNOME Wayland
- Second tap closes the menu again
- Only one overlay instance runs at a time
- Thumb-wheel assignments from the Buttons tab take effect
- Screenshot action picks a tool that works on the running desktop
- GNOME cursor helper extension supports GNOME Shell 50

* Fri Dec 13 2024 JuhLabs (Julian Hermstad) <juhlabs@example.com> - 1.0.0-1
- Initial release
- Glassmorphic radial menu overlay
- Battery status monitoring via HID++
- Settings dashboard with mouse visualization
- DPI and scroll wheel configuration
- KDE Plasma 6 integration
