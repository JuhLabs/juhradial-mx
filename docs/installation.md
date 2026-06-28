# Installation

JuhRadial MX builds from source on every supported distribution. The fastest path is the one-line installer, which detects your distro, pulls the right packages, compiles the Rust daemon, and wires up autostart and device permissions for you. Manual and NixOS paths are documented below for people who prefer to drive each step themselves.

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/githubheader.png" width="100%" alt="JuhRadial MX">
</div>

!!! note
    JuhRadial MX targets Wayland first (KDE Plasma 6, GNOME, Hyprland, COSMIC, Sway, niri) and also runs on X11. See [Compositor-Support](compositor-support.md) for per-compositor behaviour, and [Features](features.md) for what you get once it is running.


## Contents

- [Quick start: the one-line installer](#quick-start-the-one-line-installer)
- [What the installer does](#what-the-installer-does)
- [Requirements](#requirements)
- [Manual installation per distro](#manual-installation-per-distro)
  - [Fedora](#fedora)
  - [Ubuntu / Debian](#ubuntu-debian)
  - [Arch Linux](#arch-linux)
  - [openSUSE Tumbleweed](#opensuse-tumbleweed)
  - [NixOS (flake)](#nixos-flake)
- [Build from source](#build-from-source)
- [Updating](#updating)
- [After installing](#after-installing)

## Quick start: the one-line installer

```bash
curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
```

The script is interactive: it prints a summary of your system (distro, kernel, session, desktop, whether a Logitech receiver is detected) and asks you to confirm before it changes anything.

!!! warning
    Do not run the installer as `root` or under `sudo`. It refuses to run as root and asks for `sudo` only on the individual steps that need it (package install, copying files into `/usr/local` and `/usr/share`, installing udev rules). The systemd service and config live in your user account, so it must run as your normal user.


## What the installer does

The installer (`install.sh`) runs as a fresh install or an in-place upgrade, depending on whether `/opt/juhradial-mx` already exists. A full run has six visible steps plus a preflight phase.

| Phase | What happens |
|-------|--------------|
| Detect | Reads `/etc/os-release` to resolve a distro family (`arch`, `fedora`, `debian`, `opensuse`), falling back to `ID_LIKE` and then to the available package manager (`pacman`, `apt-get`, `dnf`, `zypper`). Detects Wayland vs X11, the desktop/compositor, an existing install, and whether a Logitech device (USB vendor `046d`) is present. |
| 1. Dependencies | Installs the build and runtime packages for your distro family (Rust/Cargo, Python + PyQt6, GTK4/libadwaita, `gtk4-layer-shell`, HID and evdev dev headers, D-Bus/systemd dev headers, `ydotool`, `git`, `make`). |
| 2. Fetch source | Clones `https://github.com/JuhLabs/juhradial-mx` into `/opt/juhradial-mx` (or, on upgrade, `git fetch` + `git reset --hard origin/master` + `git clean -fd`). |
| 3. Build daemon | Ensures a usable Rust toolchain (see the rustup note below), then runs `cargo build --release` in `daemon/`. |
| 4. Install files | Copies the daemon binary, overlay scripts, theme/device assets, launcher scripts, desktop entries, icons, the systemd user unit, and udev rules into place (see layout table). |
| 5. Desktop integration | Applies compositor-specific setup (Hyprland window rules, GNOME cursor-helper extension). KDE, Sway, and COSMIC need no extra config. |
| 6. Enable service | Reloads the systemd user manager, enables `juhradialmx-daemon`, sets up `ydotoold` autostart, then starts (or restarts) the daemon. |

### Install layout

| Path | Contents |
|------|----------|
| `/opt/juhradial-mx` | Cloned source tree (used for updates) |
| `/usr/local/bin/juhradiald` | Compiled Rust daemon |
| `/usr/local/bin/juhradial-mx`, `/usr/local/bin/juhradial-settings` | Launcher scripts |
| `/usr/share/juhradial/` | Overlay Python, Flow module, locales, theme and device assets |
| `/usr/share/applications/` | `.desktop` entries for the app and settings |
| `~/.config/systemd/user/juhradialmx-daemon.service` | systemd user service |
| `~/.config/juhradial/` | Your `config.json` (see [Configuration](configuration.md)) |

### udev rules, uinput, and the `input` group

For non-root access to the mouse and for action injection, the installer:

- Installs `99-juhradialmx.rules` into `/etc/udev/rules.d/` and removes the older `99-logitech-hidpp.rules` if present.
- Installs `60-ydotool-uinput.rules` so the logged-in user can open `/dev/uinput` (used by both `ydotool` and the daemon's own virtual input device). Stock distros ship `/dev/uinput` as `root:root 0600`.
- Loads the `uinput` kernel module now (`modprobe uinput`) and on boot (`/etc/modules-load.d/juhradial-uinput.conf`).
- Reloads rules (`udevadm control --reload-rules` + `udevadm trigger`).
- Ensures the `input` group exists and adds your user to it (device access via hidraw/evdev comes from `GROUP="input"`).

!!! info
    If your user was just added to the `input` group, log out and back in for the new group membership to take effect. Until then the daemon cannot open the device.


### ydotoold (Wayland action injection)

Keyboard-shortcut button actions and thumb-wheel actions (volume, zoom, horizontal scroll) are injected through the kernel `uinput` device via `ydotool`, which needs its background daemon `ydotoold` running. The installer prefers a packaged `ydotool.service` / `ydotoold.service` if your distro ships one; otherwise it writes a minimal `~/.config/systemd/user/ydotoold.service` and enables it so it autostarts on login. If `ydotoold` is missing, shortcut and thumb-wheel actions may not work on Wayland.

### The rustup bootstrap

The committed `Cargo.lock` is lockfile format v4 (needs Cargo >= 1.78) and the `toml_edit` dependency needs rustc >= 1.76. Several distros ship an older toolchain (Ubuntu 24.04 ships Rust 1.75), which cannot build the daemon.

The installer checks the active Cargo version and, if it is older than 1.78 or missing entirely, bootstraps the official toolchain non-interactively:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
. "$HOME/.cargo/env"
```

!!! tip
    On Ubuntu 24.04 this happens automatically. If you are installing manually there and `cargo build` fails on the lockfile version, run the two commands above (or `rustup update stable`) and rebuild.


## Requirements

- A Wayland compositor (KDE Plasma 6, GNOME, Hyprland, COSMIC, Sway, niri) or X11.
- Rust toolchain (Cargo >= 1.78) to build the daemon. The installer provides this if needed.
- Python 3 with PyQt6 (overlay) and GTK4 + libadwaita via PyGObject (settings UI).
- XWayland, used for overlay window positioning on Wayland.
- A supported mouse (Logitech MX Master 4 / 3S / 3 for full HID++, or any mouse in generic evdev mode). See [FAQ](faq.md) for device coverage.

## Manual installation per distro

Each manual path is: install dependencies, clone, build the daemon, then run. To get autostart, udev rules, the `input` group, and `ydotoold` set up exactly as the one-line installer does, prefer the installer or replicate the steps in [What the installer does](#what-the-installer-does).

### Fedora

Family also covers RHEL, CentOS Stream, Rocky, AlmaLinux, Nobara, Ultramarine.

```bash
sudo dnf install -y \
    rust cargo \
    python3 python3-pip \
    python3-pyqt6 qt6-qtsvg \
    python3-gobject gtk4 libadwaita \
    gtk4-layer-shell \
    python3-cryptography \
    dbus-devel systemd-devel \
    libevdev-devel hidapi-devel \
    ydotool \
    git make
```

### Ubuntu / Debian

Family also covers Linux Mint, Pop!_OS, elementary, Kali, Zorin, KDE neon, MX Linux.

```bash
sudo apt-get update
sudo apt-get install -y \
    rustc cargo \
    python3 python3-pip python3-venv \
    python3-pyqt6 python3-pyqt6.qtsvg \
    python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
    python3-cryptography \
    libdbus-1-dev libsystemd-dev \
    libevdev-dev libhidapi-dev \
    ydotool \
    git make build-essential

# Optional: layer-shell support where the package exists
sudo apt-get install -y libgtk4-layer-shell0
```

!!! note
    On Ubuntu 24.04 the distro Rust (1.75) is too old for the committed lockfile. Bootstrap rustup as shown in [The rustup bootstrap](#the-rustup-bootstrap) before building.


### Arch Linux

Family also covers Manjaro, EndeavourOS, Garuda, Artix, CachyOS, ArcoLinux, Archcraft.

```bash
sudo pacman -S --noconfirm --needed \
    rust \
    python python-pip \
    python-pyqt6 qt6-svg \
    python-gobject gtk4 libadwaita \
    gtk4-layer-shell \
    python-cryptography \
    dbus systemd-libs \
    libevdev hidapi \
    ydotool \
    git make base-devel
```

### openSUSE Tumbleweed

```bash
sudo zypper install -y \
    rust cargo \
    python3 python3-pip \
    python3-PyQt6 \
    python3-gobject gtk4 libadwaita-devel \
    python3-cryptography \
    dbus-1-devel systemd-devel \
    libevdev-devel libhidapi-devel \
    ydotool \
    git make

# layer-shell may not be in your enabled repos; safe to skip if unavailable
sudo zypper install -y gtk4-layer-shell || true
```

!!! note
    On openSUSE the PyQt6 package is `python3-PyQt6` (capital `Q`), unlike the lowercase `python3-pyqt6` used on Fedora and Debian. `gtk4-layer-shell` is not always present in the default repositories; the app still runs without it (layer-shell is only required for niri-style compositors that lack cursor IPC).


### NixOS (flake)

The repository ships a `flake.nix` exposing a package, a NixOS module, and a dev shell.

Try it without installing:

```bash
nix run github:JuhLabs/juhradial-mx
```

Enable it declaratively in your system flake. Add the input:

```nix
{
  inputs.juhradial-mx.url = "github:JuhLabs/juhradial-mx";
}
```

Then import the module and enable the service in your host config:

```nix
{
  imports = [ juhradial-mx.nixosModules.default ];

  services.juhradial-mx.enable = true;
}
```

The module installs the package system-wide, applies the bundled `99-juhradialmx.rules` udev rules for non-root device access, and ensures the `input` group exists. Rebuild with `sudo nixos-rebuild switch --flake .#<host>`.

Contributors can drop into a ready toolchain (Rust, Python with PyQt6 + PyGObject, GTK4/libadwaita, Qt6) with:

```bash
nix develop github:JuhLabs/juhradial-mx
```

## Build from source

If you want to build and run without a full system install:

```bash
git clone https://github.com/JuhLabs/juhradial-mx.git
cd juhradial-mx

# Build the Rust daemon
cd daemon && cargo build --release && cd ..

# Run the overlay + daemon
./scripts/juhradial-mx.sh
```

The daemon binary lands at `daemon/target/release/juhradiald`. You still need the runtime dependencies for your distro (PyQt6, GTK4/libadwaita, `ydotool`) and, for non-root device access, the udev rules and `input` group membership described above. For a full system install identical to the one-line path, run `install.sh` from the cloned tree.

To run the daemon directly with verbose logging while debugging, see [Troubleshooting](troubleshooting.md):

```bash
./daemon/target/release/juhradiald --verbose
```

## Updating

Re-run the same one-line command. When `/opt/juhradial-mx` already exists, the installer switches to upgrade mode: it fetches the latest `master`, hard-resets the source tree, rebuilds the daemon, reinstalls files and udev rules, and restarts the running service.

```bash
curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
```

On NixOS, update the flake input and rebuild:

```bash
nix flake update juhradial-mx   # in your system flake directory
sudo nixos-rebuild switch --flake .#<host>
```

For a source checkout, pull and rebuild:

```bash
cd juhradial-mx
git pull
cd daemon && cargo build --release && cd ..
```

## After installing

- Launch from your application menu (JuhRadial MX) or run `juhradial-mx`. Hold the gesture (thumb) button on your MX Master to open the radial menu.
- Open the settings app (`juhradial-settings`) to remap buttons, pick a theme, and configure haptics, scroll, Easy-Switch, and Flow. See [Configuration](configuration.md) and [Features](features.md).
- Check the daemon:

```bash
systemctl --user status juhradialmx-daemon
journalctl --user -u juhradialmx-daemon -f
```

!!! info
    Two cases need a session restart (log out and back in): first time your user is added to the `input` group, and on GNOME for the cursor-helper Shell extension to load. If the menu appears at the top-left corner on GNOME, this is why.


If the menu does not appear or the mouse is not detected, head to [Troubleshooting](troubleshooting.md). For how the daemon, overlay, and settings app fit together, see [Architecture](architecture.md). Return to [Home](index.md) for the full page index.
