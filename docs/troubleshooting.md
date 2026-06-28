# Troubleshooting

Practical fixes for the most common JuhRadial MX problems, written as **problem -> cause -> fix**. Most issues fall into one of six buckets: the daemon will not build, the mouse is not detected, the daemon is not running, the menu shows up in the wrong place, button or thumb-wheel actions do nothing, or haptics and battery are missing.

If you only read one thing: collect the diagnostics below first, then jump to the matching section.

See also: [Installation](installation.md) · [Configuration](configuration.md) · [Compositor-Support](compositor-support.md) · [Features](features.md) · [FAQ](faq.md) · [Architecture](architecture.md)

---

## Quick diagnostics

Run these first. The output tells you which section you need.

| What to check | Command |
| --- | --- |
| Is the daemon process alive? | `pgrep -a juhradiald` |
| Service status (user unit) | `systemctl --user status juhradialmx-daemon` |
| Live daemon logs | `journalctl --user -u juhradialmx-daemon -f` |
| Run daemon by hand, verbose | `/usr/local/bin/juhradiald --verbose` |
| Is the mouse on the USB/Bluetooth bus? | `lsusb \| grep -i 046d` |
| HID devices the kernel sees | `ls /sys/bus/hid/devices/ \| grep -i 046D` |
| Are you in the `input` group? | `id -nG \| tr ' ' '\n' \| grep -x input` |
| Can the uinput node be opened? | `ls -l /dev/uinput` |
| Is the injection helper running? | `systemctl --user status ydotoold` |
| Rust toolchain version | `cargo --version` |

!!! tip
    The D-Bus identity is bus name `org.kde.juhradialmx`, object path `/org/kde/juhradialmx/Daemon`, interface `org.kde.juhradialmx.Daemon`. You can confirm the daemon is exporting it with:
    ```bash
    busctl --user introspect org.kde.juhradialmx /org/kde/juhradialmx/Daemon
    ```


---

## Build and installation

### Problem: the build fails on an older distro (Ubuntu 24.04, Debian stable, and similar)

**Cause.** The committed `Cargo.lock` is lockfile format v4, which needs `cargo >= 1.78`, and one dependency (`toml_edit`) needs `rustc >= 1.76`. Distro Rust packages are frequently older: Ubuntu 24.04 ships `1.75`. A too-old `cargo` produces lockfile or edition errors before anything compiles.

**Fix.** Install an up-to-date toolchain with `rustup`. The one-line installer does this automatically when it detects a `cargo` older than `1.78`, but for a manual build do it yourself:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
. "$HOME/.cargo/env"
cargo --version          # confirm 1.78 or newer
cd daemon && cargo build --release
```

If you previously installed the distro `rust`/`cargo` packages, the `rustup` shim in `~/.cargo/bin` must come first on your `PATH`. Open a fresh shell (or re-source `~/.cargo/env`) after installing.

### Problem: the build fails on missing C headers

**Cause.** The daemon links against system libraries for D-Bus, evdev, and HID. Missing `-devel`/`-dev` headers fail the build at the link stage.

**Fix.** Install the development packages for your distro family. These mirror what the installer pulls in:

| Family | Header packages |
| --- | --- |
| Fedora / RHEL | `dbus-devel systemd-devel libevdev-devel hidapi-devel` |
| Arch | `dbus systemd-libs libevdev hidapi` |
| Debian / Ubuntu | `libdbus-1-dev libsystemd-dev libevdev-dev libhidapi-dev` |
| openSUSE | `dbus-1-devel systemd-devel libevdev-devel libhidapi-devel` |

### Problem: openSUSE reports `gtk4-layer-shell` is not available

**Cause.** `gtk4-layer-shell` is not in every openSUSE repository. The installer treats this as a soft warning (`gtk4-layer-shell not available on this repo`) and continues.

**Fix.** It is safe to ignore on most setups. The layer-shell surface is only required for correct menu placement on **niri** (see [niri menu not visible](#problem-the-menu-never-appears-on-niri) below). If you run niri on openSUSE, add a repository that ships the package (for example the relevant `X11:Wayland` devel repo) and install it, or fall back to a compositor with native cursor support. On all other compositors JuhRadial MX positions the overlay through XWayland and does not need the package.

---

## Device detection

### Problem: the mouse is not detected at all

**Cause.** Almost always permissions. The daemon reads `hidraw` (for HID++) and `evdev` (for button events) directly, which requires membership in the `input` group. The udev rules ship `GROUP="input"` on the Logitech device nodes, so without that group the nodes are unreadable.

**Fix.**

```bash
# 1. Confirm the kernel sees a Logitech device (046d):
lsusb | grep -i 046d
ls /sys/bus/hid/devices/ | grep -i 046D

# 2. Make sure the udev rules are installed (the dev sync script does NOT install them):
sudo install -Dm644 packaging/udev/99-juhradialmx.rules /etc/udev/rules.d/99-juhradialmx.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# 3. Join the input group, then LOG OUT and back in (group changes need a fresh session):
sudo usermod -aG input "$USER"
```

!!! warning
    Adding yourself to a group does not affect already-running sessions. You must log out and back in (or reboot). Verify afterwards with `id -nG | grep input`.


### Problem: a USB-cabled or receiver mouse works, but the same mouse over Bluetooth is invisible

**Cause.** A Bluetooth-connected mouse is exposed as a virtual `uhid` device with **no parent that carries `idVendor`/`idProduct`**. Classic rules like `ATTRS{idVendor}=="046d"` therefore never match a Bluetooth device, so the node keeps its default `root:root 0600` permissions.

**Fix.** The shipped rules already handle this by matching the parent kernel name instead of the vendor attribute. Bluetooth devices are named `<bus>:<VID>:<PID>.<n>` (uppercase, bus `0005` = Bluetooth, `0003` = USB), and the rules match `KERNELS=="0005:046D:*"` and `KERNELS=="0003:046D:*"` with `GROUP="input"`. If a Bluetooth mouse is still not picked up:

1. Confirm the rules file is current (it must contain the `KERNELS=="0005:046D:*"` line):
   ```bash
   grep -n 'KERNELS=="0005:046D' /etc/udev/rules.d/99-juhradialmx.rules
   ```
2. Reinstall the rules and re-trigger as shown above, then re-pair or toggle Bluetooth so the node is recreated under the new rules.
3. Confirm group ownership landed on the node:
   ```bash
   ls -l /dev/hidraw*    # look for group "input" on the Logitech node
   ```

!!! note
    The effective access grant for these nodes comes from `GROUP="input"`, not from `uaccess`. A `TAG+="uaccess"` in a `99-*` rule runs too late to take effect, so do not rely on it: being in the `input` group is what matters.


---

## The daemon will not start

### Problem: `systemctl --user status juhradialmx-daemon` shows failed or inactive

**Cause.** Several possibilities: the binary is missing, the user has no graphical session/D-Bus when the unit starts, or the daemon hit its restart limit after repeated crashes.

**Fix.** Work through it with the service tooling:

```bash
# Full status plus the last lines of output:
systemctl --user status juhradialmx-daemon

# Follow the logs while you reproduce the issue:
journalctl --user -u juhradialmx-daemon -f

# Reload unit files, then re-enable and start:
systemctl --user daemon-reload
systemctl --user enable --now juhradialmx-daemon
```

Things to check against the symptoms in the logs:

- **`exec format` / file not found:** the binary is not at `/usr/local/bin/juhradiald`. Re-run the installer or `sudo install -Dm755 daemon/target/release/juhradiald /usr/local/bin/juhradiald`.
- **Start-limit hit (`start request repeated too quickly`):** the daemon crashed five times in a minute and systemd backed off. Clear it and retry:
  ```bash
  systemctl --user reset-failed juhradialmx-daemon
  systemctl --user start juhradialmx-daemon
  ```
- **No device / permission errors in the log:** this is really a detection problem, go back to [Device detection](#device-detection).

To see the real error directly, stop the service and run the binary in the foreground:

```bash
systemctl --user stop juhradialmx-daemon
/usr/local/bin/juhradiald --verbose
```

---

## Menu position and visibility

### Problem: the menu opens in the top-left corner of the screen

**Cause.** The daemon could not read the cursor position from your compositor, so the overlay falls back to the origin. On GNOME this is almost always the cursor-helper Shell extension not being loaded yet (Wayland requires a session restart to activate a newly installed extension).

**Fix (GNOME).**

```bash
gnome-extensions enable juhradial-cursor@dev.juhlabs.com
gnome-extensions info juhradial-cursor@dev.juhlabs.com   # State should read ACTIVE
```

If it is installed but not `ACTIVE`, log out and back in (or restart the session). On other compositors, a top-left menu means cursor detection failed for a different reason: see [Compositor-Support](compositor-support.md) for the per-compositor cursor source (KWin script on KDE, IPC on Hyprland, XWayland on Sway/COSMIC).

### Problem: the menu lands near the cursor but drifts further off the more you move from the top-left, especially at non-100% display scale

**Cause.** Coordinate-space mismatch under fractional scaling. The daemon reads the cursor in **logical** pixels, while the overlay (forced onto XWayland, where Qt6 high-DPI scaling is on) places windows in **point** space (physical pixels divided by the device pixel ratio). Feeding a logical coordinate straight into the overlay overshoots in proportion to distance from the monitor's top-left corner.

**Fix.** This is handled in current builds by dividing the cursor coordinate by the cursor screen's `devicePixelRatio` (with `dpr = 1` as the identity case). If you see the drift, you are on an older build: update to the latest release. Confirm your scale with your display settings; the symptom is strongest at 125 percent, 150 percent, and similar.

```bash
curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
```

### Problem: the menu opens on the wrong monitor in a multi-display setup

**Cause.** Same coordinate-space root as above. If the cursor coordinate is misscaled, the point can land inside a neighbouring monitor's rectangle. It can also happen when the compositor reports cursor position in a different origin than the overlay expects.

**Fix.** Update to the current release (the scaling fix above). If it persists, capture the reported cursor position from `journalctl --user -u juhradialmx-daemon -f` while triggering the menu and open an issue with that output plus your monitor layout and per-display scale.

### Problem: the overlay is positioned correctly but hidden behind other windows (Hyprland)

**Cause.** Without window rules, Hyprland tiles or stacks the overlay like a normal window.

**Fix.** Add the overlay rules (the installer does this automatically on Hyprland). In `hyprland.conf` or a sourced rules file:

```conf
windowrulev2 = float,    title:^(JuhRadial MX)$
windowrulev2 = noblur,   title:^(JuhRadial MX)$
windowrulev2 = noborder, title:^(JuhRadial MX)$
windowrulev2 = noshadow, title:^(JuhRadial MX)$
windowrulev2 = pin,      title:^(JuhRadial MX)$
windowrulev2 = noanim,   title:^(JuhRadial MX)$
```

Then `hyprctl reload`. See [Compositor-Support](compositor-support.md) for other compositors.

### Problem: the menu never appears on niri

**Cause.** niri exposes no cursor IPC and breaks XWayland popup placement, which is the positioning path every other compositor uses. The XWayland `move()` call has nothing to anchor to, so the overlay cannot place itself.

**Fix.** niri needs a `wlr-layer-shell` surface via `gtk4-layer-shell` (a declared dependency) instead of XWayland positioning. Make sure the package is installed:

| Family | Package |
| --- | --- |
| Fedora | `gtk4-layer-shell` |
| Arch | `gtk4-layer-shell` |
| Debian / Ubuntu | `libgtk4-layer-shell0` |
| openSUSE | `gtk4-layer-shell` (may be absent, see [openSUSE note](#problem-opensuse-reports-gtk4-layer-shell-is-not-available)) |

Also run `xwayland-satellite` so the rest of the XWayland pipeline functions. See [Compositor-Support](compositor-support.md) for the full niri setup.

---

## Buttons and thumb-wheel actions do nothing

### Problem: a remapped button or thumb-wheel action (volume, zoom, copy, horizontal scroll) fires nothing

**Cause.** Two separate requirements, and either one missing produces silence:

1. **Injection helper.** Keyboard-shortcut and thumb-wheel actions are injected through the kernel `uinput` device via `ydotool`, because XWayland-style injection cannot drive native Wayland windows. `ydotool` needs its background daemon, `ydotoold`, running.
2. **uinput access.** Both `ydotoold` and the daemon's own virtual input device must be able to open `/dev/uinput`, which stock distros ship as `root:root 0600`.

**Fix.**

Start with the helper:

```bash
# Is ydotoold present and running?
command -v ydotoold
systemctl --user status ydotoold

# If installed but not running, enable it:
systemctl --user enable --now ydotoold
```

Then fix uinput permissions. The installer ships a uaccess rule for `/dev/uinput` (`60-ydotool-uinput.rules`), loads the `uinput` module, and ensures you are in the `input` group. Reproduce that manually if needed:

```bash
# 1. Make sure the uinput module is loaded (and loads at boot):
sudo modprobe uinput
echo uinput | sudo tee /etc/modules-load.d/juhradial-uinput.conf

# 2. Install the uinput access rule and reload:
sudo install -Dm644 packaging/udev/60-ydotool-uinput.rules /etc/udev/rules.d/60-ydotool-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# 3. Confirm the node is accessible to you:
ls -l /dev/uinput

# 4. Be in the input group (log out/in after first time):
id -nG | grep input
```

!!! note
    If `ydotoold` is missing entirely, install `ydotool` for your distro (`dnf install ydotool`, `pacman -S ydotool`, `apt install ydotool`, `zypper install ydotool`). The installer prints `ydotoold not found: shortcut/thumb-wheel actions may not work on Wayland` when it cannot find it.


### Problem: only some buttons respond, others do nothing

**Cause.** Only the gesture button and the haptic button are diverted by default. Back, forward, middle, and shift-wheel are not diverted out of the box, so reassigning them in the settings UI has no effect until the daemon diverts them and routes them through its action handler. Diverts also use a volatile flag, so they are lost on device hotplug.

**Fix.** Update to a build where the button you want is included in the divert set, and re-apply config after a reconnect (`ReloadConfig`, or just trigger the daemon's reconnect path by re-plugging). If your assignment still does nothing after a reload, the CID for that button is not yet diverted: note which physical button in a GitHub issue. See [Features](features.md) for which buttons are remappable.

---

## Haptics and battery

### Problem: no haptic feedback, and battery/DPI/Easy-Switch fields are empty

**Cause.** Haptics, battery level, DPI, scroll-ratchet state, and Easy-Switch host all come from **HID++** feature calls, which only work on a supported Logitech MX device (MX Master 4, MX Master 3S, MX Master 3). When the daemon falls back to **generic mode** (any non-HID++ mouse via evdev), only the radial menu and button remapping are available. There is no HID++ channel to query, so those panels stay blank and the actuator never fires.

**Fix.**

1. Confirm you are on a supported device and that HID++ is reachable:
   ```bash
   lsusb | grep -i 046d
   journalctl --user -u juhradialmx-daemon -f   # look for HID++ feature discovery vs "generic mode"
   ```
2. Make sure `hidraw` access works (HID++ travels over the `hidraw` node, not evdev). This is the same permission story as [Device detection](#device-detection): be in the `input` group and have the udev rules installed.
3. If you are intentionally using a non-Logitech mouse, this is expected: generic mode does not provide haptics or battery. The radial menu and remapping still work. See [Features](features.md) for the per-mode capability matrix.

!!! note
    Battery and Easy-Switch host update live over HID++. If they were populated and then froze, the device likely roamed to another host (Easy-Switch) or the divert state was lost on hotplug; a reconnect re-runs feature discovery.


---

## Still stuck

1. Re-run the installer to pull the latest fixes:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
   ```
2. Capture a verbose run and the service logs:
   ```bash
   systemctl --user stop juhradialmx-daemon
   /usr/local/bin/juhradiald --verbose 2>&1 | tee juhradial-debug.log
   ```
3. Open an issue at <https://github.com/JuhLabs/juhradial-mx/issues> with your distro, compositor (and display scale), the device and connection type (USB receiver vs Bluetooth), and that log.

Related pages: [Installation](installation.md) · [Configuration](configuration.md) · [Compositor-Support](compositor-support.md) · [Features](features.md) · [FAQ](faq.md) · [Architecture](architecture.md) · [Home](index.md)
