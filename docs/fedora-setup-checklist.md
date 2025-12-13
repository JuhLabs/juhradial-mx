# Fedora KDE Setup Checklist

Before starting Epic 6 (Settings Dashboard), verify the development environment on Fedora.

## Prerequisites

- [ ] Fedora KDE Spin (or Fedora with KDE Plasma installed)
- [ ] Git repository cloned to Fedora machine
- [ ] MX Master 4 mouse available for testing

## 1. Rust Toolchain

```bash
# Install Rust if not present
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Verify installation
rustc --version
cargo --version
```

## 2. Build Dependencies

```bash
# Install development packages
sudo dnf install -y \
    gcc \
    pkg-config \
    systemd-devel \
    dbus-devel \
    libevdev-devel \
    hidapi-devel \
    cmake \
    make
```

## 3. KDE/Plasma Development Tools

```bash
# Install KDE development packages for Epic 6
sudo dnf install -y \
    qt6-qtbase-devel \
    qt6-qtdeclarative-devel \
    kf6-kcmutils-devel \
    kf6-ki18n-devel \
    kf6-kconfigwidgets-devel \
    kf6-kirigami-devel \
    plasma-sdk \
    kdeplasma-addons
```

## 4. Verify Daemon Builds

```bash
cd /path/to/JuhRadialMX

# Build the daemon
cd daemon
cargo build

# Expected: Compiles without errors
```

## 5. Run Test Suite

```bash
cd daemon

# Run all tests
cargo test

# Expected: All tests pass (60+ tests)
# Note: Some HID tests may be skipped without real device
```

## 6. Verify D-Bus Tools

```bash
# Check D-Bus is running
systemctl --user status dbus

# Install D-Bus debugging tools
sudo dnf install -y d-feet dbus-x11

# Test D-Bus introspection (after daemon runs)
# busctl --user introspect org.juhradial.Daemon /org/juhradial/Daemon
```

## 7. Device Access Setup

```bash
# Check if MX Master 4 is detected
lsusb | grep -i logitech

# Check evdev devices
ls -la /dev/input/event*

# If permission issues, the udev rules from Story 1.6 need to be installed:
# sudo cp system/99-juhradial.rules /etc/udev/rules.d/
# sudo udevadm control --reload-rules
# sudo udevadm trigger
```

## 8. Verify KDE Plasma Version

```bash
# Check Plasma version (should be 6.x for latest Fedora)
plasmashell --version

# Check KDE Frameworks version
kf6-config --version
```

## 9. QML Development Verification

```bash
# Test QML can run
qml6 --version

# Create a simple test (optional)
echo 'import QtQuick; Rectangle { width: 100; height: 100; color: "red" }' > /tmp/test.qml
qml6 /tmp/test.qml
```

## 10. IDE Setup (Optional)

```bash
# VS Code with extensions
sudo dnf install -y code
# Install extensions: rust-analyzer, QML, KDE Plasma Tools

# Or Kate (KDE native)
sudo dnf install -y kate
```

## Quick Verification Script

Save and run this script to verify everything:

```bash
#!/bin/bash
echo "=== JuhRadial MX Fedora Setup Verification ==="

echo -n "Rust: "
rustc --version 2>/dev/null || echo "NOT INSTALLED"

echo -n "Cargo: "
cargo --version 2>/dev/null || echo "NOT INSTALLED"

echo -n "Plasma: "
plasmashell --version 2>/dev/null || echo "NOT INSTALLED"

echo -n "QML6: "
qml6 --version 2>/dev/null || echo "NOT INSTALLED"

echo -n "D-Bus: "
systemctl --user is-active dbus 2>/dev/null || echo "NOT RUNNING"

echo -n "Logitech device: "
lsusb | grep -qi logitech && echo "FOUND" || echo "NOT FOUND"

echo ""
echo "=== Build Test ==="
cd daemon 2>/dev/null && cargo check 2>&1 | tail -1
```

## Troubleshooting

### Cargo build fails with missing libraries
```bash
# Check which -devel packages are missing
cargo build 2>&1 | grep "could not find"
# Install the corresponding -devel package
```

### Permission denied on /dev/hidraw*
```bash
# Add user to input group
sudo usermod -aG input $USER
# Log out and back in
```

### Plasma SDK tools not found
```bash
# Ensure plasma-sdk is installed
sudo dnf install -y plasma-sdk
# Tools: plasmoidviewer, plasmaengineexplorer
```

## Ready for Epic 6?

All boxes checked? You're ready to start:
- **Story 6.1**: Plasmoid Shell & Interactive Mouse Preview

Run `/bmad:bmm:workflows:dev-story` to begin implementation.
