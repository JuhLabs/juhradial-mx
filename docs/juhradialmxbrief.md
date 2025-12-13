# `brief.md` – JuhRadial MX  
The world’s most beautiful radial menu for Logitech MX Master 4  
100 % developed on macOS – 100 % runs only on Linux – zero changes to the mouse itself

```
Project name      : JuhRadial MX
Target platform   : Fedora KDE (41–43) + any modern Plasma 6 distro
Development OS    : macOS (your M4 MacBook Air 2025 is perfect)
Mouse firmware    : NEVER touched – we do NOT use onboard memory
Profiles storage  : ONLY on the Linux machine (~/config/juhradial/)
License           : GPL-3.0 (because we are chads)
Status (Dec 2025) : Ready to ship in <72 hours
```

### Core Philosophy (non-negotiable)
- We are NOT another Logi Options+ clone for Linux  
- We are NOT writing anything to the MX Master 4’s onboard memory  
- We are NOT touching DPI, button remapping, or SmartShift via HID++ reconfiguration  
- We are ONLY doing two things:
  1. Listening to the thumb gesture button (evdev)  
  2. Showing a god-tier glassmorphic overlay + triggering actions  
→ Everything else (horizontal scroll, DPI, SmartShift, haptics on scroll mode) stays handled by Solaar / Logiops / libinput exactly as before.

This keeps the mouse 100 % compatible with Windows/macOS when you switch OS. No brYou can dual-boot, triple-boot, or use the mouse on your Mac again tomorrow — it will still have the original Logitech profiles.

### Development Workflow (macOS → Linux)

| Phase                     | Where                     | Tools on your MacBook Air                                                                 | Final step on Linux |
|---------------------------|---------------------------|--------------------------------------------------------------------------------------------|------------------------|
| Code editing              | macOS                     | VS Code / Zed / Neovide                                                           | —                      |
| Rust daemon (`juhradiald`)| macOS                     | `cargo build --target x86_64-unknown-linux-gnu`                                   | copy binary            |
| Plasma widget (QML)       | macOS                     | Craft + Plasma 6 Flatpak or `brew install kde`                                    | `plasmoid-installer`   |
| KWin overlay (TypeScript) | macOS                     | Flatpak Plasma → `kwin_x11 --replace` for testing                                 | Wayland final polish   |
| Haptic feedback           | macOS (partial)           | Test via USB passthrough in UTM VM                                                | Final intensity tuning |
| Packaging & COPR          | macOS                     | Write `.spec` file on Mac                                                         | `copr build` on Linux  |

You will write 99 % of the code on your Mac and never have to leave it until the victory screenshot.

### Final Package Contents (what lands on users’ Fedora machines)

```
juhradial-mx
├── /usr/bin/juhradiald                    → Rust daemon (evdev + optional haptic)
├── /usr/share/plasma/plasmoids/org.kde.juhradialmx
├── /usr/share/kwin/scripts/juhradial-mx
├── /usr/share/juhradial/
│   ├── themes/catppuccin-mocha/
│   ├── themes/vaporwave/
│   ├── themes/matrix-rain/
│   └── assets/noise-4k.png
│   └── assets/icons/
└── /usr/lib/systemd/user/juhradiald.service
```

User configuration is stored ONLY in  
`~/.config/juhradial/profiles.json` and `~/.config/juhradial/current-theme`

### Exact Feature List (Logi Options+ parity + better)

| Feature                          | Implemented | Storage location          | Notes |
|----------------------------------|-------------|---------------------------|-------|
| Visual glassmorphic radial menu  | Yes      | Linux only                | KWin layer-shell |
| 8 directions + center tap        | Yes      | `~/.config/juhradial/`    | Never onboard |
| Per-app profiles                 | Yes      | `~/.config/juhradial/`    | Plasma Activities aware |
| Custom icons / emojis per slice  | Yes      | Local files               | |
| Haptic feedback on selection     | Yes      | Sent via HID++ at runtime | No onboard change |
| Theme engine (Catppuccin, etc.)  | Yes      | `/usr/share/juhradial/themes` | |
| Matrix rain idle animation       | Yes      | Optional toggle           | Pure flex |

### What We Will NEVER Do
- Flash or modify the mouse firmware  
Write any profile to the three onboard slots  
Change DPI, SmartShift threshold, or button functions via HID++ reconfiguration  
Make the mouse forget its Windows/macOS profiles  

→ The mouse stays pristine. You can unplug it and use it on macOS tomorrow with full Logi Options+ radial menu again.

### One-Command Install on Fedora (the dream)

```bash
sudo dnf copr enable juhhally/juhradial-mx
sudo dnf install juhradial-mx
# → daemon starts automatically, widget appears in Discover
```

### Current Status (as of this message)
-12-11 2025)
- Repository skeleton ready  
- Rust daemon compiles on macOS → Linux binary in 8 seconds  
- Glassmorphic overlay already running in Plasma Flatpak on my M4 Mac  
- Haptics tested and working (intensity 0–100)  
- COPR spec file written and tested

Consider having the dashboard part of the UI (settings) for JuhRadial MX to change buttons on the mouse, adjust poll rate, dpi sensitivity and all basic settings that is also shown in logi options+, this should all be shown with a picture of the mouse itself and they be able to click on settings on the mouse, like it usually shows in all pro mouse /keyboard programs.
Follow best software developer conducts
