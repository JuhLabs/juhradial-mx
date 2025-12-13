---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
inputDocuments:
  - docs/juhradialmxbrief.md
documentCounts:
  briefs: 1
  research: 0
  brainstorming: 0
  projectDocs: 0
workflowType: 'prd'
lastStep: 11
project_name: 'JuhRadial MX'
user_name: 'Julianhermstad'
date: '2025-12-11'
---

# Product Requirements Document - JuhRadial MX

**Author:** Julianhermstad
**Date:** 2025-12-11
**Version:** 1.0
**Status:** Draft

---

## 1. Executive Summary

### 1.1 Product Vision

JuhRadial MX is a beautiful, glassmorphic radial menu overlay for the Logitech MX Master 4 mouse, designed exclusively for Linux (Fedora KDE / Plasma 6). It provides Logi Options+ style radial menu functionality without modifying the mouse's onboard memory, ensuring the mouse remains fully compatible with Windows and macOS when switching operating systems.

### 1.2 Problem Statement

Linux users of the Logitech MX Master 4 lack the polished radial menu experience available on Windows/macOS through Logi Options+. Existing Linux solutions (Solaar, Logiops, libinput) handle button remapping and DPI but don't provide the visual radial menu overlay that makes the MX Master 4's gesture button truly useful. Users want:

- A beautiful, modern radial menu triggered by the thumb gesture button
- Per-application profiles with custom actions
- No risk of breaking cross-platform mouse compatibility
- Native KDE Plasma integration

### 1.3 Proposed Solution

A Rust daemon + KDE Plasma widget combination that:
1. Listens to the thumb gesture button via evdev (no HID++ reconfiguration)
2. Displays a stunning glassmorphic overlay via KWin layer-shell
3. Triggers customizable actions per direction (8 directions + center tap)
4. Provides haptic feedback at runtime (without writing to onboard memory)
5. Offers a visual settings dashboard with interactive mouse preview

### 1.4 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Installation success rate | >95% | COPR install completion |
| Response latency (button → menu) | <50ms | Performance profiling |
| User satisfaction | 4.5+ stars | COPR/GitHub reviews |
| Cross-platform compatibility | 100% | Mouse works identically on Win/Mac after use |
| Memory footprint | <50MB RAM | Runtime monitoring |

---

## 2. Product Overview

### 2.1 Product Name & Tagline

**JuhRadial MX**
*"The world's most beautiful radial menu for Logitech MX Master 4"*

### 2.2 Target Platform

- **Primary:** Fedora KDE (41-43) with Plasma 6
- **Secondary:** Any modern Plasma 6 distribution (Kubuntu, openSUSE, Arch + KDE)
- **Development:** macOS (cross-compilation to Linux)

### 2.3 Core Philosophy (Non-Negotiable Constraints)

| Principle | Rationale |
|-----------|-----------|
| **No onboard memory writes** | Mouse must remain 100% compatible with Windows/macOS |
| **No firmware modifications** | Zero risk of bricking or warranty issues |
| **No DPI/SmartShift reconfiguration** | Let Solaar/Logiops handle hardware settings |
| **Evdev input only** | Standard Linux input subsystem, no proprietary protocols |
| **Runtime haptics only** | Send vibration commands without storing profiles |

### 2.4 What JuhRadial MX Is NOT

- NOT a Logi Options+ clone for Linux (we only do radial menu)
- NOT a button remapper (use Solaar/Logiops for that)
- NOT a DPI/sensitivity manager (use existing tools)
- NOT something that touches onboard mouse memory

---

## 3. User Personas

### 3.1 Primary Persona: "The Linux Power User"

**Name:** Alex
**Role:** Software developer / System administrator
**Technical Level:** Advanced

**Profile:**
- Uses Fedora KDE as primary workstation
- Owns MX Master 4 for productivity
- Dual/triple boots with Windows/macOS occasionally
- Values aesthetics and efficiency equally
- Comfortable with CLI but appreciates good GUI

**Goals:**
- Quick access to frequent actions (copy, paste, screenshot, window management)
- Different actions per application (VS Code vs Firefox vs terminal)
- Beautiful overlay that matches Catppuccin/Nordic theme
- Zero impact on Windows/macOS mouse behavior

**Pain Points:**
- Misses Logi Options+ radial menu on Linux
- Doesn't want to sacrifice cross-platform compatibility
- Tired of ugly GTK2-era Linux utilities
- Wants native Plasma integration, not electron apps

### 3.2 Secondary Persona: "The Creative Professional"

**Name:** Sam
**Role:** Video editor / Designer using Linux
**Technical Level:** Intermediate

**Profile:**
- Uses Linux for DaVinci Resolve / Blender / GIMP
- Needs quick tool switching and shortcuts
- Works on Mac at studio, Linux at home
- Same MX Master 4 on both systems

**Goals:**
- Per-app radial menus for creative tools
- Custom icons/emojis for visual recognition
- Smooth, responsive overlay that doesn't interrupt flow
- Take mouse to Mac without reconfiguration

---

## 4. Features & Requirements

### 4.1 Feature Overview

| Feature | Priority | Category |
|---------|----------|----------|
| Glassmorphic radial menu overlay | P0 | Core |
| 8-direction + center tap actions | P0 | Core |
| Evdev gesture button detection | P0 | Core |
| Per-application profiles | P0 | Core |
| Theme engine (Catppuccin, etc.) | P1 | UX |
| Custom icons per slice | P1 | UX |
| Haptic feedback on selection | P1 | UX |
| Settings dashboard with mouse preview | P1 | UX |
| Plasma Activities integration | P2 | Integration |
| Matrix rain idle animation | P2 | Polish |
| COPR one-command install | P0 | Distribution |

### 4.2 Functional Requirements

#### FR-001: Gesture Button Detection
**Priority:** P0 (Critical)
**Description:** Detect thumb gesture button press/release via Linux evdev subsystem

**Acceptance Criteria:**
- [ ] Daemon detects MX Master 4 via vendor/product ID
- [ ] Listens to gesture button events without root (udev rules)
- [ ] Supports both wired and wireless (Bolt/Bluetooth) connections
- [ ] Does not interfere with Solaar/Logiops if running

#### FR-002: Radial Menu Display
**Priority:** P0 (Critical)
**Description:** Display 8-slice radial menu with center action on gesture button hold

**Acceptance Criteria:**
- [ ] Menu appears within 50ms of button press
- [ ] 8 directional slices + center tap zone
- [ ] Mouse cursor movement selects slice
- [ ] Selection highlights with smooth animation
- [ ] Menu dismisses on button release, triggering selected action

#### FR-003: Action Execution
**Priority:** P0 (Critical)
**Description:** Execute configured action when slice is selected

**Acceptance Criteria:**
- [ ] Supports keyboard shortcuts (e.g., Ctrl+C, Super+Print)
- [ ] Supports shell commands
- [ ] Supports D-Bus calls (KDE-specific actions)
- [ ] Supports KWin scripts for window management
- [ ] Action executes within 10ms of selection

#### FR-004: Per-Application Profiles
**Priority:** P0 (Critical)
**Description:** Load different radial menu configurations based on focused application

**Acceptance Criteria:**
- [ ] Detect focused window via KWin/Plasma APIs
- [ ] Match window class to profile
- [ ] Fall back to default profile if no match
- [ ] Profile switching under 5ms (no visible delay)

#### FR-005: Theme Engine
**Priority:** P1 (High)
**Description:** Support multiple visual themes for the radial menu

**Acceptance Criteria:**
- [ ] Ships with Catppuccin Mocha theme (default)
- [ ] Ships with Vaporwave and Matrix Rain themes
- [ ] Theme defines colors, blur intensity, border radius, glow
- [ ] Hot-reload theme without restarting daemon
- [ ] Users can create custom themes via JSON/YAML

#### FR-006: Haptic Feedback
**Priority:** P1 (High)
**Description:** Provide tactile feedback when hovering/selecting menu slices

**Acceptance Criteria:**
- [ ] Send HID++ haptic command on slice hover
- [ ] Stronger haptic on selection confirmation
- [ ] Intensity configurable (0-100)
- [ ] NO writing to onboard memory (runtime commands only)
- [ ] Graceful fallback if haptics unavailable

#### FR-007: Settings Dashboard
**Priority:** P1 (High)
**Description:** Visual configuration interface for all JuhRadial MX settings

**Acceptance Criteria:**
- [ ] Interactive MX Master 4 image with clickable zones
- [ ] Visual radial menu editor (drag-drop icons, set actions)
- [ ] Profile management (create, edit, delete, duplicate)
- [ ] Theme preview and selection
- [ ] Haptic intensity slider with live test
- [ ] Export/import configuration

#### FR-008: Custom Icons
**Priority:** P1 (High)
**Description:** Allow custom icons or emojis for each radial menu slice

**Acceptance Criteria:**
- [ ] Support PNG/SVG icons
- [ ] Support Unicode emoji
- [ ] Icon picker in settings dashboard
- [ ] Icons stored locally (not in mouse)

#### FR-009: Plasma Activities Integration
**Priority:** P2 (Medium)
**Description:** Different profiles per Plasma Activity

**Acceptance Criteria:**
- [ ] Detect active Plasma Activity
- [ ] Map Activities to profile sets
- [ ] Switch profiles on Activity change

#### FR-010: Idle Animations
**Priority:** P2 (Medium)
**Description:** Optional decorative animations when menu is displayed

**Acceptance Criteria:**
- [ ] Matrix rain effect (optional toggle)
- [ ] Subtle particle effects
- [ ] Performance budget: <5% CPU during animation
- [ ] Disabled by default

### 4.3 Non-Functional Requirements

#### NFR-001: Performance
- Menu appearance latency: <50ms
- Action execution latency: <10ms
- Memory usage: <50MB RAM
- CPU idle: <1%
- CPU during animation: <5%

#### NFR-002: Reliability
- Daemon auto-restart on crash (systemd)
- Graceful handling of mouse disconnect/reconnect
- No data loss on unexpected termination
- Configuration backup on update

#### NFR-003: Security
- No elevated privileges for normal operation
- Udev rules for device access (not root)
- Configuration files in user home only
- No network access required

#### NFR-004: Compatibility
- Fedora 41, 42, 43
- Plasma 6.x
- Wayland (primary) and X11 (fallback)
- MX Master 4 via USB, Bolt, or Bluetooth

#### NFR-005: Maintainability
- Rust for daemon (memory safety, performance)
- QML for Plasma widget (native integration)
- TypeScript for KWin scripts
- Comprehensive logging with configurable levels
- Modular architecture for easy extension

---

## 5. User Experience

### 5.1 User Flows

#### Flow 1: First-Time Setup

```
1. User installs via: sudo dnf install juhradial-mx
2. Systemd user service starts automatically
3. Plasma widget appears in system tray
4. User clicks widget → Settings dashboard opens
5. Dashboard detects MX Master 4 automatically
6. User sees interactive mouse preview
7. User customizes radial menu slices
8. User selects theme (defaults to Catppuccin)
9. User tests haptic feedback intensity
10. User saves → Ready to use
```

#### Flow 2: Daily Usage

```
1. User holds thumb gesture button
2. Glassmorphic radial menu appears instantly
3. User moves mouse toward desired action
4. Slice highlights + haptic feedback
5. User releases button
6. Action executes (e.g., screenshot taken)
7. Menu disappears with fade animation
```

#### Flow 3: App-Specific Profile

```
1. User opens VS Code
2. JuhRadial detects window class "code"
3. Loads "VS Code" profile automatically
4. Radial menu shows: Format, Comment, Go to Definition, etc.
5. User switches to Firefox
6. Loads "Browser" profile
7. Radial menu shows: New Tab, Close Tab, Refresh, etc.
```

### 5.2 Visual Design Principles

- **Glassmorphism:** Frosted glass effect with subtle blur
- **Modern Aesthetics:** Rounded corners, soft shadows, gradient accents
- **Theme Consistency:** Respect user's system theme colors
- **Minimal Chrome:** Focus on actions, minimize UI overhead
- **Smooth Animations:** 60fps transitions, ease-in-out curves

### 5.3 Accessibility

- High contrast mode option
- Configurable animation speed (including disable)
- Keyboard navigation for settings
- Screen reader support for dashboard

---

## 6. Technical Architecture

### 6.1 Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    JuhRadial MX System                      │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐     ┌──────────────────┐             │
│  │   juhradiald     │     │  Plasma Widget   │             │
│  │   (Rust Daemon)  │◄───►│  (QML/JS)        │             │
│  └────────┬─────────┘     └────────┬─────────┘             │
│           │                        │                        │
│           ▼                        ▼                        │
│  ┌──────────────────┐     ┌──────────────────┐             │
│  │   evdev input    │     │  KWin Script     │             │
│  │   (button detect)│     │  (overlay render)│             │
│  └──────────────────┘     └──────────────────┘             │
│           │                        │                        │
│           ▼                        ▼                        │
│  ┌──────────────────┐     ┌──────────────────┐             │
│  │   HID++ haptics  │     │  D-Bus IPC       │             │
│  │   (runtime only) │     │  (daemon↔widget) │             │
│  └──────────────────┘     └──────────────────┘             │
├─────────────────────────────────────────────────────────────┤
│  Configuration: ~/.config/juhradial/                        │
│  Themes: /usr/share/juhradial/themes/                       │
│  Assets: /usr/share/juhradial/assets/                       │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Component Details

#### juhradiald (Rust Daemon)
- **Responsibility:** Input detection, haptics, profile management
- **IPC:** D-Bus session bus for widget communication
- **Lifecycle:** Systemd user service (auto-start, restart on failure)

#### Plasma Widget (QML)
- **Responsibility:** System tray icon, settings dashboard
- **Framework:** Plasma 6 Plasmoid API
- **Distribution:** Discover store compatible

#### KWin Script (TypeScript)
- **Responsibility:** Radial menu overlay rendering
- **Framework:** KWin scripting API with layer-shell
- **Wayland:** Native layer-shell for overlay

### 6.3 Data Storage

| Data | Location | Format |
|------|----------|--------|
| Profiles | ~/.config/juhradial/profiles.json | JSON |
| Current theme | ~/.config/juhradial/current-theme | Text (theme name) |
| User settings | ~/.config/juhradial/settings.json | JSON |
| Themes | /usr/share/juhradial/themes/ | JSON + assets |
| Icons | /usr/share/juhradial/assets/icons/ | PNG/SVG |

### 6.4 IPC Protocol

Daemon ↔ Widget communication via D-Bus:

```
Interface: org.kde.juhradialmx
Methods:
  - ShowMenu() → void
  - HideMenu() → void
  - SetProfile(string appClass) → void
  - TriggerHaptic(int intensity) → void
  - GetProfiles() → array<Profile>
  - SaveProfile(Profile) → void

Signals:
  - MenuShown()
  - MenuHidden()
  - SliceSelected(int index)
  - ProfileChanged(string name)
```

---

## 7. Package Contents

### 7.1 Installed Files

```
juhradial-mx (RPM package)
├── /usr/bin/juhradiald                           # Rust daemon binary
├── /usr/share/plasma/plasmoids/org.kde.juhradialmx/
│   ├── metadata.json
│   ├── contents/ui/main.qml
│   └── contents/ui/config/...
├── /usr/share/kwin/scripts/juhradial-mx/
│   ├── metadata.json
│   └── contents/code/main.js
├── /usr/share/juhradial/
│   ├── themes/
│   │   ├── catppuccin-mocha/
│   │   ├── vaporwave/
│   │   └── matrix-rain/
│   └── assets/
│       ├── noise-4k.png
│       └── icons/
├── /usr/lib/systemd/user/juhradiald.service
└── /usr/lib/udev/rules.d/99-juhradial-mx.rules
```

### 7.2 Distribution

- **Primary:** Fedora COPR repository
- **Installation:** `sudo dnf copr enable juhhally/juhradial-mx && sudo dnf install juhradial-mx`
- **Updates:** Standard DNF updates

---

## 8. Constraints & Assumptions

### 8.1 Constraints

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| No onboard memory access | Cannot persist profiles on mouse | All config stored locally |
| Wayland security model | Limited input injection | Use approved Plasma/KWin APIs |
| Cross-compile from macOS | Testing limitations | Use VMs + final polish on Linux |
| MX Master 4 only | Limited user base initially | Clear documentation of scope |

### 8.2 Assumptions

- User has MX Master 4 (not MX Master 3, 2, etc.)
- User runs Fedora KDE or compatible Plasma 6 distro
- User is comfortable with CLI for initial install
- User has working Bluetooth/Bolt/USB for mouse
- Solaar/Logiops may be running concurrently

### 8.3 Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| Plasma | 6.x | Widget framework, KWin scripting |
| Rust | 1.70+ | Daemon compilation |
| systemd | 250+ | Service management |
| D-Bus | - | IPC |
| evdev | - | Input subsystem |

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| KWin API changes in Plasma 6.x | Medium | High | Version-specific code paths, CI testing |
| Wayland layer-shell limitations | Low | Medium | X11 fallback for overlay |
| Haptic HID++ command changes | Low | Low | Runtime detection, graceful fallback |
| User breaks mouse config | Very Low | Medium | Clear documentation: we don't touch mouse |
| Competition from official Logitech Linux support | Low | High | First-mover advantage, community building |

---

## 10. Future Considerations

### 10.1 Potential Expansions (Post v1.0)

- Support for MX Master 3, MX Anywhere 3
- Plugin system for custom actions
- Cloud sync for profiles (optional)
- Mobile companion app for config
- Integration with other overlay tools (Ulauncher, etc.)

### 10.2 Out of Scope (Will Not Implement)

- DPI adjustment
- Button remapping
- SmartShift configuration
- Scroll wheel customization
- Onboard profile management
- Windows/macOS support

---

## 11. Glossary

| Term | Definition |
|------|------------|
| **Evdev** | Linux kernel input event interface |
| **HID++** | Logitech's proprietary device protocol |
| **Onboard memory** | Storage within the mouse for profiles |
| **Bolt** | Logitech's wireless receiver technology |
| **Glassmorphism** | UI design style with frosted glass effect |
| **KWin** | KDE's window manager and compositor |
| **Plasma** | KDE's desktop environment |
| **Layer-shell** | Wayland protocol for overlay windows |
| **D-Bus** | Linux IPC message bus system |

---

## 12. Appendices

### Appendix A: Competitor Analysis

| Solution | Platform | Radial Menu | Onboard Safe | Native KDE |
|----------|----------|-------------|--------------|------------|
| Logi Options+ | Win/Mac | Yes | N/A | N/A |
| Solaar | Linux | No | Yes | No |
| Logiops | Linux | No | Yes | No |
| Piper | Linux | No | Varies | No |
| **JuhRadial MX** | **Linux** | **Yes** | **Yes** | **Yes** |

### Appendix B: Sample Profile Configuration

```json
{
  "profiles": {
    "default": {
      "name": "Default",
      "slices": [
        { "direction": "N", "icon": "📋", "action": { "type": "shortcut", "value": "Ctrl+C" } },
        { "direction": "NE", "icon": "📝", "action": { "type": "shortcut", "value": "Ctrl+V" } },
        { "direction": "E", "icon": "↩️", "action": { "type": "shortcut", "value": "Ctrl+Z" } },
        { "direction": "SE", "icon": "↪️", "action": { "type": "shortcut", "value": "Ctrl+Shift+Z" } },
        { "direction": "S", "icon": "📸", "action": { "type": "shortcut", "value": "Print" } },
        { "direction": "SW", "icon": "🔍", "action": { "type": "shortcut", "value": "Ctrl+F" } },
        { "direction": "W", "icon": "💾", "action": { "type": "shortcut", "value": "Ctrl+S" } },
        { "direction": "NW", "icon": "📂", "action": { "type": "command", "value": "dolphin ~" } }
      ],
      "center": { "icon": "🚀", "action": { "type": "dbus", "value": "org.kde.krunner" } }
    },
    "vscode": {
      "appClass": "code",
      "name": "VS Code",
      "slices": [
        { "direction": "N", "icon": "🔧", "action": { "type": "shortcut", "value": "Shift+Alt+F" } },
        { "direction": "E", "icon": "💬", "action": { "type": "shortcut", "value": "Ctrl+/" } },
        { "direction": "S", "icon": "🔎", "action": { "type": "shortcut", "value": "F12" } },
        { "direction": "W", "icon": "📖", "action": { "type": "shortcut", "value": "Ctrl+Shift+O" } }
      ]
    }
  }
}
```

---

**Document Status:** Complete
**Next Steps:** Architecture Design → Epic/Story Breakdown → Implementation
