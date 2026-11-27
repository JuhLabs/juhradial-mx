# Flatpak

`packaging/org.juhlabs.JuhRadialMX.yaml` builds JuhRadial MX as a Flatpak from this source tree. It is meant for [Flatpark](https://flatpark.org/) or a repository hosted by the project, not for Flathub.

The Flatpak ships the application. It cannot grant itself access to the mouse, so there is a one-time host step (below).

## What the Flatpak can and cannot do

| | |
|---|---|
| Bundled | the daemon (`juhradiald`), the Qt overlay (the radial menu), the Qt Settings app, `ydotool` and `ydotoold`, PyQt6, `cryptography` |
| Not bundled | the GTK Settings fallback and the niri layer-shell host (both need PyGObject, GTK 4 and libadwaita, which the KDE runtime does not ship), `playerctl`, `xdotool` and other host tools the daemon calls |
| Cannot do from inside the sandbox | install udev rules, load the `uinput` module, add you to a group |
| Needs the host | udev rules for `/dev/hidraw*` and `/dev/uinput` (`host-setup.sh`), a Wayland or X11 session |
| Not covered | login autostart (the native install writes an XDG autostart entry; a Flatpak needs the Background portal), the systemd user unit |

`QtQuick.VectorImage` is missing from the PyQt6 base app's Qt; the Settings app has a stand-in for it (spot illustrations only).

Behaviour that depends on the host compositor is unchanged: KWin scripting, GNOME's cursor helper and Hyprland window rules all live on the host. The Hyprland rules and the GNOME extension that `install.sh` installs are not part of the Flatpak.

## Sandbox permissions

| Permission | Why |
|---|---|
| `--socket=wayland`, `--socket=fallback-x11`, `--share=ipc`, `--device=dri` | overlay and Settings windows |
| `--device=all` | `/dev/hidraw*` (HID++), `/dev/input/event*`, `/dev/uinput` (ydotool). Flatpak has no narrower device permission that includes hidraw. The nodes become visible; the host's udev permissions still decide whether they can be opened |
| `--own-name=org.kde.juhradialmx`, `--own-name=org.kde.juhradialmx.*` | the daemon's D-Bus name |
| `--talk-name=org.kde.KWin`, `org.kde.kglobalaccel`, `org.kde.plasmashell`, `org.freedesktop.Notifications`, `org.freedesktop.UPower`, `org.kde.StatusNotifierWatcher` | cursor position and window tracking through KWin scripts, global shortcuts, notifications, battery, tray |
| `--filesystem=xdg-run/juhradial-tmp:create` | KWin reads the script file the daemon writes; the launcher points `TMPDIR` here so the host can see it |

The config lives in the sandbox (`~/.var/app/org.juhlabs.JuhRadialMX/config/juhradial`), not in `~/.config/juhradial`.

## One-time host setup

The daemon needs read and write access to the mouse's hidraw node and to `/dev/uinput`. On the host, once:

```bash
sh "$(flatpak info --show-location org.juhlabs.JuhRadialMX)/files/share/juhradial/host-setup.sh"
```

From a source checkout: `sh packaging/flatpak/host-setup.sh` (add `--dry-run` to print the steps first). It installs `60-ydotool-uinput.rules`, `70-juhradialmx-uaccess.rules` and `99-juhradialmx.rules` into `/etc/udev/rules.d`, loads `uinput` now and at boot, reloads udev and adds you to the `input` group, the same as `install.sh`. Reconnect the mouse, or log out and in.

On image-based systems (Bazzite, Silverblue) `/etc/udev/rules.d` and `/etc/modules-load.d` are writable and survive updates; `usermod -aG input` may need the group entry copied from `/usr/lib/group` first, which `install.sh` handles and this script does not.

## Build and test

```bash
flatpak-builder --user --install-deps-from=flathub --force-clean \
    --install build packaging/org.juhlabs.JuhRadialMX.yaml
flatpak run org.juhlabs.JuhRadialMX                 # Settings, services in the background
flatpak run org.juhlabs.JuhRadialMX --background    # services only
flatpak run org.juhlabs.JuhRadialMX doctor          # status check
```

`.github/workflows/flatpak.yml` does the build on every change to the manifest and runs smoke tests in the sandbox (the binaries start, the Python modules import, the Settings Qt report runs, the host script finds its rules, the daemon claims its D-Bus name and `juhradial-mx status` answers). It has no mouse, no uinput permission and no desktop session, so the overlay is not exercised there.

### Updating the Rust crates

`packaging/cargo-sources.json` has to match `daemon/Cargo.lock`; CI fails when it does not. Regenerate it after a dependency change:

```bash
git clone https://github.com/flatpak/flatpak-builder-tools
python3 flatpak-builder-tools/cargo/flatpak-cargo-generator.py daemon/Cargo.lock -o packaging/cargo-sources.json
```

### Building a release

The manifest builds the checkout it sits in (`type: dir`). A package repository can point the two `dir` sources at a release tag with `type: git` and `tag:`/`commit:` instead.
