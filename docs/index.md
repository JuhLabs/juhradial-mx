<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/juhradial-mx.svg" width="120" alt="JuhRadial MX">
  <h1>JuhRadial MX Wiki</h1>
  <p><strong>The ultimate Logitech MX Master experience on Linux</strong></p>
  <p>
    <code>Radial Menu</code> &nbsp;&middot;&nbsp; <code>Thumb-Wheel</code> &nbsp;&middot;&nbsp; <code>Per-App Profiles</code> &nbsp;&middot;&nbsp; <code>Haptics</code> &nbsp;&middot;&nbsp; <code>Easy-Switch</code> &nbsp;&middot;&nbsp; <code>Flow</code>
  </p>
</div>

Welcome. JuhRadial MX brings the full Logitech MX Master experience to Linux, native on Wayland: a radial gesture menu, haptic feedback, button and thumb-wheel remapping, per-application profiles, Easy-Switch, and cross-computer Flow. This wiki is the complete guide.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
```

The installer detects your distro, installs dependencies, builds from source, and sets up autostart. Full steps and per-distro notes: [Installation](installation.md).

## Explore

| Page | What's there |
|------|--------------|
| [Installation](installation.md) | One-line install, per-distro steps, build from source, updating |
| [Features](features.md) | Radial menu, remapping, thumb-wheel, haptics, Easy-Switch, Flow, gaming, macros |
| [Configuration](configuration.md) | `config.json` reference, themes, per-application profiles |
| [Compositor Support\](compositor-support.md) | GNOME, KDE Plasma 6, Hyprland, COSMIC, Sway, niri, X11 |
| [Troubleshooting](troubleshooting.md) | Common problems and how to fix them |
| [Architecture](architecture.md) | How it works, for contributors |
| [FAQ](faq.md) | Quick answers to common questions |

## What is new in v0.4.1

The radial menu now opens on the cursor on GNOME Wayland, a second tap closes it again, only one overlay runs at a time, thumb-wheel assignments in the Buttons tab take effect, and the screenshot action picks a tool that works on the desktop you are running. See the [Changelog](https://github.com/JuhLabs/juhradial-mx/blob/master/CHANGELOG.md).

## A look at it

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/screenshots/RadialWheel.png" width="260" alt="Radial menu">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/screenshots/Settings.png" width="430" alt="Settings dashboard">
</div>

---

New here? Start with [Installation](installation.md), then skim [Features](features.md). Stuck? See [Troubleshooting](troubleshooting.md) or open an [issue](https://github.com/JuhLabs/juhradial-mx/issues).
