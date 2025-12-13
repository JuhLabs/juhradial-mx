---
stepsCompleted: [1, 2, 3]
requirementsConfirmed: true
epicsApproved: true
storiesGenerated: true
inputDocuments:
  - docs/prd.md
  - docs/architecture.md
  - docs/ux-design-specification.md
  - docs/juhradialmxbrief.md
workflowType: 'epics-stories'
lastStep: 1
project_name: 'JuhRadial MX'
user_name: 'Julianhermstad'
date: '2025-12-11'
---

# JuhRadial MX - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for JuhRadial MX, decomposing the requirements from the PRD, UX Design, and Architecture into implementable stories.

## Requirements Inventory

### Functional Requirements

| ID | Description | Priority | Acceptance Criteria Summary |
|----|-------------|----------|----------------------------|
| FR-001 | Gesture Button Detection | P0 | Detect MX Master 4 via vendor/product ID, listen via evdev without root, support USB/Bolt/BT, no interference with Solaar/Logiops |
| FR-002 | Radial Menu Display | P0 | Menu appears <50ms, 8 directional slices + center tap, cursor movement selects slice, smooth highlight animation, dismiss on release |
| FR-003 | Action Execution | P0 | Support keyboard shortcuts, shell commands, D-Bus calls, KWin scripts; execute <10ms |
| FR-004 | Per-Application Profiles | P0 | Detect focused window via KWin/Plasma APIs, match window class to profile, fallback to default, switch <5ms |
| FR-005 | Theme Engine | P1 | Ship Catppuccin Mocha (default), Vaporwave, Matrix Rain themes; define colors/blur/glow; hot-reload without restart; custom themes via JSON |
| FR-006 | Haptic Feedback | P1 | Send HID++ haptic on hover/selection, configurable intensity 0-100, NO onboard memory writes, graceful fallback |
| FR-007 | Settings Dashboard | P1 | Interactive MX Master 4 image, visual radial menu editor, profile management, theme preview, haptic slider, export/import |
| FR-008 | Custom Icons | P1 | Support PNG/SVG icons and Unicode emoji, icon picker in dashboard, stored locally |
| FR-009 | Plasma Activities Integration | P2 | Detect active Activity, map to profile sets, switch on Activity change |
| FR-010 | Idle Animations | P2 | Matrix rain effect (optional), subtle particles, <5% CPU, disabled by default |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Performance | Menu appearance latency | <50ms |
| NFR-001 | Performance | Action execution latency | <10ms |
| NFR-001 | Performance | Memory usage | <50MB RAM |
| NFR-001 | Performance | CPU idle | <1% |
| NFR-001 | Performance | CPU during animation | <5% |
| NFR-002 | Reliability | Daemon auto-restart on crash | systemd |
| NFR-002 | Reliability | Mouse disconnect/reconnect handling | Graceful |
| NFR-002 | Reliability | No data loss on termination | Required |
| NFR-002 | Reliability | Configuration backup on update | Required |
| NFR-003 | Security | No elevated privileges | udev rules |
| NFR-003 | Security | Configuration files location | User home only |
| NFR-003 | Security | Network access | None required |
| NFR-004 | Compatibility | Fedora versions | 41, 42, 43 |
| NFR-004 | Compatibility | Plasma version | 6.x |
| NFR-004 | Compatibility | Display servers | Wayland (primary), X11 (fallback) |
| NFR-004 | Compatibility | Connection types | USB, Bolt, Bluetooth |
| NFR-005 | Maintainability | Daemon language | Rust |
| NFR-005 | Maintainability | Widget framework | QML (Plasma 6) |
| NFR-005 | Maintainability | KWin script language | TypeScript |
| NFR-005 | Maintainability | Logging | Configurable levels |

### Additional Requirements

**From Architecture:**
- Monorepo structure: `daemon/`, `kwin-script/`, `widget/`, `themes/`, `packaging/`
- D-Bus interface: `org.kde.juhradialmx.Daemon` with defined methods/signals
- zbus 5.x for Rust D-Bus (pure Rust, async)
- evdev 0.13.x crate for input events
- criterion crate for performance benchmarks
- Makefile for unified build commands
- GitHub Actions CI on Linux runner
- 80%+ unit test coverage for daemon logic
- Linux VM required for KWin overlay testing
- USB passthrough required for haptic testing
- COPR-only distribution for MVP
- udev rules for non-root input device access
- User added to `input` group during install
- Blur fallback to solid background if GPU can't sustain 60fps (first-class feature)

**From UX Design:**
- Menu diameter: 280px (scales with display factor)
- Center zone: 80px diameter (28% of total)
- Slice arc: 45° each (8 equal sectors)
- Icon zone: 100px from center
- Outer ring: 60px thickness
- Cursor-centered positioning with edge clamping (20px margin)
- Direction mapping: N=0, NE=1, E=2, SE=3, S=4, SW=5, W=6, NW=7
- Haptic profile: appear=20/100, slice change=40/100, confirm=80/100, invalid=30/100
- Glassmorphism: 24px blur, 75% background opacity, 180% saturation, 3-5% noise
- Animation: 30ms appear, 50ms dismiss, 80ms slice highlight in, 60ms highlight out
- Catppuccin Mocha palette as default
- High contrast mode: 95% opacity, 60% border, no blur
- Reduced motion: instant transitions (0ms)
- Display scaling: proportional at 100%, 125%, 150%, 200%
- Empty slices: "+" affordance with dashed border, invalid haptic on selection
- Profile stays same if app changes mid-menu

**From Brief:**
- No onboard memory writes (critical constraint)
- macOS development → Linux deployment workflow
- GPL-3.0 license
- One-command COPR install: `sudo dnf copr enable juhhally/juhradial-mx && sudo dnf install juhradial-mx`
- Configuration at `~/.config/juhradial/`

### FR Coverage Map

| FR | Epic | Description |
|----|------|-------------|
| FR-001 | Epic 2 | Gesture Button Detection |
| FR-002 | Epic 2 | Radial Menu Display |
| FR-003 | Epic 2 | Action Execution |
| FR-004 | Epic 3 | Per-Application Profiles |
| FR-005 | Epic 4 | Theme Engine |
| FR-006 | Epic 5 | Haptic Feedback |
| FR-007 | Epic 6 | Settings Dashboard |
| FR-008 | Epic 3 | Custom Icons |
| FR-009 | Epic 8 | Plasma Activities Integration |
| FR-010 | Epic 8 | Idle Animations |

## Epic List

### Epic 1: Foundation & Architecture Spike
**Goal:** Validate the end-to-end architecture (evdev → Rust daemon → D-Bus → KWin overlay) and establish the monorepo structure with CI/CD.

**User Outcome:** Development infrastructure is validated and ready. Developers can build upon a proven architecture.

**FRs Covered:** None directly (infrastructure epic)
**NFRs Addressed:** NFR-003 (Security: udev rules), NFR-005 (Maintainability: project structure)

---

### Epic 2: Core Radial Menu Experience
**Goal:** Deliver the core radial menu interaction loop that makes JuhRadial MX usable for daily tasks.

**User Outcome:** Linux users can hold the gesture button and see a beautiful radial menu appear, select actions by moving the mouse, and execute common shortcuts.

**FRs Covered:** FR-001 (Gesture Detection), FR-002 (Radial Menu Display), FR-003 (Action Execution)
**NFRs Addressed:** NFR-001 (Performance: <50ms latency), NFR-004 (Compatibility: Wayland + X11)

---

### Epic 3: Profile & Personalization System
**Goal:** Enable per-application profiles and custom action configuration.

**User Outcome:** Users can customize their radial menu actions and have different configurations for different applications automatically.

**FRs Covered:** FR-004 (Per-Application Profiles), FR-008 (Custom Icons)
**NFRs Addressed:** NFR-002 (Reliability: config management)

---

### Epic 4: Visual Customization & Themes
**Goal:** Deliver the theme engine with bundled themes and hot-reload capability.

**User Outcome:** Users can choose beautiful themes (Catppuccin, Vaporwave, Matrix) and the menu matches their desktop aesthetic.

**FRs Covered:** FR-005 (Theme Engine)
**NFRs Addressed:** NFR-001 (Performance: blur fallback)

---

### Epic 5: Haptic Feedback System
**Goal:** Implement runtime HID++ haptic commands with configurable intensity.

**User Outcome:** Users feel tactile feedback when interacting with the menu, making selection more intuitive and satisfying.

**FRs Covered:** FR-006 (Haptic Feedback)
**Critical Constraint:** No onboard memory writes

---

### Epic 6: Settings Dashboard
**Goal:** Deliver the complete settings experience with visual editor, theme picker, and haptic controls.

**User Outcome:** Users can visually configure all aspects of JuhRadial MX through an intuitive Plasma widget with an interactive mouse preview.

**FRs Covered:** FR-007 (Settings Dashboard)

---

### Epic 7: Distribution & Packaging
**Goal:** Package everything for Fedora COPR distribution with proper systemd integration.

**User Outcome:** Users can install JuhRadial MX with a single command via COPR and have it "just work."

**FRs Covered:** None directly (distribution epic)
**NFRs Addressed:** NFR-002 (Reliability: auto-restart), NFR-004 (Compatibility: Fedora 41-43)

---

### Epic 8: Advanced Features (P2)
**Goal:** Implement P2 features for enthusiasts and power users.

**User Outcome:** Power users can integrate with Plasma Activities and enjoy decorative idle animations.

**FRs Covered:** FR-009 (Plasma Activities Integration), FR-010 (Idle Animations)

---

## Epic 1: Foundation & Architecture Spike - Stories

### Story 1.1: Create Monorepo Structure with Build System

As a developer,
I want a standardized monorepo layout with a unified build system,
So that I can work efficiently across all components with consistent tooling.

**Acceptance Criteria:**

**Given** I am starting the JuhRadial MX project
**When** I initialize the repository structure
**Then** the following directories exist: `daemon/`, `kwin-script/`, `widget/`, `themes/`, `packaging/`
**And** each component has its own build configuration (Cargo.toml for daemon, package.json for kwin-script, etc.)
**And** a root Makefile provides unified commands: `make build`, `make test`, `make clean`
**And** a root README.md documents the monorepo structure and build commands

**Given** the monorepo structure is in place
**When** I run `make build` from the repository root
**Then** all components build successfully without errors
**And** build artifacts are placed in a `build/` directory with subdirectories per component
**And** the build process completes in under 2 minutes on a standard development machine

---

### Story 1.2: Implement D-Bus Interface Definition

As a developer,
I want a well-defined D-Bus interface between the daemon and KWin overlay,
So that components can communicate reliably with a stable API contract.

**Acceptance Criteria:**

**Given** the daemon component is initialized
**When** I define the D-Bus interface `org.kde.juhradialmx.Daemon`
**Then** the interface includes the following methods:
- `ShowMenu(x: i32, y: i32) -> ()`
- `HideMenu() -> ()`
- `ExecuteAction(action_id: s) -> ()`
**And** the interface includes the following signals:
- `MenuRequested(x: i32, y: i32)`
- `SliceSelected(index: u8)`
- `ActionExecuted(action_id: s)`

**Given** the D-Bus interface is implemented in the daemon
**When** I run `busctl introspect org.kde.juhradialmx.Daemon /org/kde/juhradialmx/Daemon`
**Then** the interface appears in the introspection output
**And** all defined methods and signals are listed

---

### Story 1.3: Setup GitHub Actions CI Pipeline

As a developer,
I want automated CI testing on every commit,
So that I catch build failures and test regressions before they reach main.

**Acceptance Criteria:**

**Given** the GitHub repository is created
**When** I push a `.github/workflows/ci.yml` file
**Then** the workflow runs on: push to main, pull requests, and manual dispatch
**And** the workflow runs on a Linux runner (ubuntu-latest)
**And** the workflow installs required dependencies: Rust toolchain, Qt6/Plasma dev packages, D-Bus

**Given** the CI workflow is configured
**When** a commit is pushed to any branch
**Then** the workflow executes: Checkout code, Install dependencies, Run `make build`, Run `make test`
**And** the workflow fails if any step returns a non-zero exit code
**And** the workflow completes in under 5 minutes

---

### Story 1.4: Validate evdev Input Capture

As a developer,
I want to capture MX Master 4 gesture button events via evdev,
So that I can trigger menu display without root privileges.

**Acceptance Criteria:**

**Given** I have an MX Master 4 connected via USB, Bluetooth, or Bolt
**When** I run `evtest` and list devices
**Then** the MX Master 4 appears with vendor ID 0x046d
**And** the product ID matches the MX Master 4 (0xb034 or similar)

**Given** I create a udev rule at `/etc/udev/rules.d/99-juhradialmx.rules`
**When** the rule contains: `SUBSYSTEM=="input", ATTRS{idVendor}=="046d", MODE="0660", GROUP="input"`
**Then** after reloading udev rules and adding user to input group
**And** logging out and back in
**Then** the daemon can open the evdev device without sudo

**Given** the daemon is listening for evdev events
**When** I press the gesture button on the MX Master 4
**Then** the daemon receives an EV_KEY event with the correct key code
**And** releasing the button generates a corresponding release event

**Given** Solaar or Logiops is running
**When** the JuhRadial MX daemon is also running
**Then** both applications receive input events independently without interference

---

### Story 1.5: Create Proof-of-Concept KWin Overlay

As a developer,
I want a minimal KWin script that can display an overlay window,
So that I can validate the overlay rendering approach on Wayland.

**Acceptance Criteria:**

**Given** I have KDE Plasma 6 running on Wayland
**When** I create a KWin script in `kwin-script/contents/code/main.js`
**Then** the script registers a D-Bus listener for `org.kde.juhradialmx.Daemon.MenuRequested`
**And** the metadata.json file contains: `"Api": "KWin/Script"`, `"Type": "Service"`

**Given** the KWin script is installed and enabled
**When** the daemon emits a `MenuRequested` signal with coordinates (500, 300)
**Then** a basic QML window appears at screen position (500, 300)
**And** the window is a frameless overlay with no title bar or decorations
**And** the window appears on top of all other windows
**And** the window does not steal keyboard focus

---

### Story 1.6: Setup udev Rules and systemd Service

As a developer,
I want udev rules and a systemd user service template,
So that the daemon can run automatically without root privileges.

**Acceptance Criteria:**

**Given** I am preparing the packaging structure
**When** I create `packaging/udev/99-juhradialmx.rules`
**Then** the file contains rules for Logitech vendor ID 0x046d
**And** the rules set MODE="0660" and GROUP="input"

**Given** I am creating the systemd service
**When** I create `packaging/systemd/juhradialmx-daemon.service`
**Then** the service file contains `Type=simple`, `ExecStart=/usr/bin/juhradialmx-daemon`, `Restart=on-failure`, `RestartSec=5s`
**And** the `[Install]` section includes `WantedBy=default.target`

**Given** the daemon crashes
**When** systemd detects the process has exited with an error
**Then** systemd automatically restarts the daemon within 5 seconds

---

## Epic 2: Core Radial Menu Experience - Stories

### Story 2.1: Implement MX Master 4 Device Detection

As a user,
I want the daemon to automatically detect my MX Master 4 mouse,
So that I don't have to manually configure device paths.

**Acceptance Criteria:**

**Given** I have an MX Master 4 connected via USB
**When** the daemon starts
**Then** it scans `/dev/input/` for event devices
**And** it identifies the MX Master 4 by vendor ID 0x046d and product ID
**And** it logs: "Detected MX Master 4 at /dev/input/eventX"

**Given** no MX Master 4 is connected
**When** the daemon starts
**Then** it logs: "Waiting for MX Master 4 to be connected..."
**And** the daemon continues running and polls for device connection every 2 seconds

**Given** I have multiple Logitech devices connected
**When** the daemon scans for devices
**Then** it identifies only the MX Master 4 and ignores other Logitech devices

---

### Story 2.2: Capture Gesture Button Press/Release Events

As a user,
I want the daemon to detect when I press and release the gesture button,
So that it can trigger menu display and dismiss.

**Acceptance Criteria:**

**Given** the daemon has detected an MX Master 4
**When** I press the gesture button
**Then** the daemon receives an EV_KEY event with state 1 (pressed)
**And** the daemon logs: "Gesture button pressed"

**Given** the gesture button is pressed
**When** I release the gesture button
**Then** the daemon receives an EV_KEY event with state 0 (released)
**And** the duration between press and release is calculated

**Given** I press the gesture button rapidly (5 times in 1 second)
**When** the daemon processes these events
**Then** all press and release events are captured in order without drops

---

### Story 2.3: Emit D-Bus MenuRequested Signal

As a user,
I want the daemon to notify the KWin overlay when I press the gesture button,
So that the radial menu appears at my cursor position.

**Acceptance Criteria:**

**Given** the daemon has detected a gesture button press
**When** the daemon processes the press event
**Then** it queries the current cursor position
**And** it emits a D-Bus signal `MenuRequested(x: i32, y: i32)`
**And** the signal is emitted within 10ms of the button press event

**Given** the cursor is within 20 pixels of the screen edge
**When** the daemon emits MenuRequested
**Then** it adjusts coordinates to ensure the menu fits on screen with 20px minimum margin

---

### Story 2.4: Render Basic Radial Menu Overlay

As a user,
I want to see a glassmorphic radial menu appear when I press the gesture button,
So that I can visually select actions.

**Acceptance Criteria:**

**Given** the KWin script receives a MenuRequested signal
**When** the signal contains coordinates (500, 300)
**Then** a QML overlay window appears centered at screen position (500, 300)
**And** the overlay renders within 50ms of signal reception (NFR-001)

**Given** the menu overlay is rendering
**When** I observe the visual design
**Then** the menu has a total diameter of 280px
**And** it contains 8 equal slices arranged in a circle (45° each)
**And** the center zone is a circle with 80px diameter

**Given** the menu is displayed
**When** I inspect the glassmorphism effects
**Then** the background has a 24px blur effect at 75% opacity
**And** saturation is increased by 180%

**Given** the GPU cannot sustain 60fps with blur enabled
**When** the menu detects frame drops
**Then** it automatically disables blur and falls back to a solid background

---

### Story 2.5: Implement Slice Selection via Cursor Movement

As a user,
I want to select a slice by moving my cursor while holding the gesture button,
So that I can choose actions intuitively.

**Acceptance Criteria:**

**Given** the radial menu is displayed
**When** I move my cursor within the center zone (80px diameter)
**Then** no slice is highlighted

**Given** the cursor is in the center zone
**When** I move my cursor into the North slice (0° ± 22.5°)
**Then** the North slice (index 0) is highlighted within 16ms (1 frame at 60fps)
**And** the highlight animation takes 80ms (ease-in)

**Given** the menu is displayed
**When** I test all 8 directional slices (N, NE, E, SE, S, SW, W, NW)
**Then** each slice highlights correctly when the cursor enters its 45° arc
**And** the direction mapping matches: N=0, NE=1, E=2, SE=3, S=4, SW=5, W=6, NW=7

---

### Story 2.6: Execute Keyboard Shortcut Actions

As a user,
I want to execute keyboard shortcuts when I release the gesture button over a slice,
So that I can trigger common actions like copy/paste.

**Acceptance Criteria:**

**Given** the default profile has a keyboard shortcut action assigned to the North slice
**When** the radial menu is displayed and the North slice is highlighted
**And** I release the gesture button
**Then** the daemon synthesizes the key combination (e.g., Ctrl+C)
**And** the total execution time is under 10ms (NFR-001)

**Given** I have text selected in an application
**When** I use the radial menu to execute Ctrl+C
**Then** the selected text is copied to the clipboard

**Given** a slice has no action assigned (empty slice)
**When** I release the gesture button over that slice
**Then** no keyboard events are synthesized and the menu dismisses normally

---

### Story 2.7: Dismiss Menu on Gesture Button Release

As a user,
I want the radial menu to disappear when I release the gesture button,
So that my screen returns to normal after making a selection.

**Acceptance Criteria:**

**Given** the radial menu is displayed
**When** I release the gesture button
**Then** the daemon emits a D-Bus signal `HideMenu()`
**And** the radial menu fades out over 50ms with an ease-in animation

**Given** I release the gesture button while the cursor is in the center zone
**When** the menu dismisses
**Then** no action is executed and the menu simply disappears

**Given** the user has enabled "reduced motion" accessibility setting
**When** the menu dismisses
**Then** the fade-out animation is instant (0ms)

---

### Story 2.8: Execute Shell Command Actions

As a user,
I want to execute shell commands from radial menu slices,
So that I can trigger custom scripts and system utilities.

**Acceptance Criteria:**

**Given** a slice has a shell command action assigned
**When** I release the gesture button over that slice
**Then** the daemon executes the shell command in a subprocess
**And** the command executes within the user's shell environment
**And** the command execution begins within 10ms of action trigger

**Given** I assign the command `konsole` to a slice
**When** I trigger that slice
**Then** the Konsole terminal application launches
**And** the daemon does not wait for Konsole to exit

**Given** I assign an invalid command to a slice
**When** I trigger that slice
**Then** the execution fails gracefully with logged error
**And** the daemon does not crash

---

## Epic 3: Profile & Personalization System - Stories

### Story 3.1: Implement Profile Configuration Schema

As a developer,
I want a well-defined JSON schema for profile configuration,
So that profiles are validated and consistent.

**Acceptance Criteria:**

**Given** I am defining the profile system
**When** I create the configuration schema
**Then** the profile configuration file is located at `~/.config/juhradial/profiles.json`
**And** the schema defines: default profile, application-specific profiles, 8 slice actions per profile

**Given** the profiles.json file does not exist
**When** the daemon starts
**Then** it creates profiles.json with a default profile containing common actions (copy, paste, undo, etc.)

---

### Story 3.2: Detect Focused Window via KWin/Plasma APIs

As a user,
I want the system to automatically detect which application I'm using,
So that the correct profile loads when I open the radial menu.

**Acceptance Criteria:**

**Given** the daemon is running on KDE Plasma
**When** it initializes
**Then** it establishes a D-Bus connection to `org.kde.KWin`
**And** it subscribes to window focus change signals

**Given** I switch focus to Firefox
**When** Firefox becomes the active window
**Then** the daemon receives a focus change event
**And** it extracts the window class as a string (e.g., "firefox")
**And** this happens within 5ms of the focus change (NFR-004)

---

### Story 3.3: Match Window Class to Profile

As a user,
I want the radial menu to automatically use the correct profile for each application,
So that I see relevant actions without manual switching.

**Acceptance Criteria:**

**Given** the profiles.json contains profiles for "firefox", "konsole", and default
**When** the active window class is "firefox"
**And** I press the gesture button
**Then** the daemon loads the Firefox profile within 5ms

**Given** the active window class is "dolphin" with no matching profile
**When** I press the gesture button
**Then** the daemon falls back to the default profile

**Given** I open the radial menu with Firefox focused
**When** the menu is displayed and I switch to another application mid-interaction
**Then** the profile remains "Firefox" until I close the menu

---

### Story 3.4: Implement Default Profile Fallback

As a user,
I want a default profile to handle applications without custom profiles,
So that the radial menu always works even for unconfigured apps.

**Acceptance Criteria:**

**Given** the profiles.json file contains a default profile (windowClass: null)
**When** no application profiles match the active window
**Then** the daemon loads the default profile with common shortcuts

**Given** the profiles.json file is missing or corrupted
**When** the daemon fails to load any profiles
**Then** it falls back to a hardcoded default profile and continues running

---

### Story 3.5: Support Custom Icons for Actions

As a user,
I want to assign custom icons to each slice action,
So that I can visually identify actions at a glance.

**Acceptance Criteria:**

**Given** an action object in the profile configuration
**When** I add an "icon" field
**Then** the field accepts: PNG file path, SVG file path, Unicode emoji, or system icon name

**Given** I configure a slice with icon: "📋"
**When** the radial menu displays
**Then** the emoji renders at 32px in the slice icon zone (100px from center)

**Given** the icon file path does not exist
**When** the daemon attempts to load the icon
**Then** it falls back to a default icon and logs a warning

---

### Story 3.6: Validate Profile Configuration on Load

As a user,
I want the daemon to validate my profile configuration,
So that I'm alerted to errors before they cause runtime failures.

**Acceptance Criteria:**

**Given** the daemon loads profiles.json
**When** it parses the configuration
**Then** it validates: default profile exists, each profile has 8 slices, each action has valid type

**Given** a profile has 7 slices (missing one)
**When** the daemon validates the configuration
**Then** it pads the missing slice with a "none" action and continues loading

---

## Epic 4: Visual Customization & Themes - Stories

### Story 4.1: Theme JSON Schema & Parser

As a developer,
I want a validated theme JSON schema and parser in the daemon,
So that custom themes can be loaded safely without crashes.

**Acceptance Criteria:**

**Given** the daemon is starting up
**When** it loads theme files from `/usr/share/juhradial/themes/` and `~/.config/juhradial/themes/`
**Then** each theme JSON is validated against the schema
**And** invalid themes are logged with specific error messages and skipped

**Given** a theme JSON contains all required fields
**When** the theme is parsed
**Then** the following properties are extracted: colors, blur intensity (8-48px), border radius, glow settings, noise opacity

---

### Story 4.2: Bundled Theme Implementation

As a Linux user,
I want three beautiful pre-installed themes to choose from,
So that I can personalize my radial menu appearance immediately.

**Acceptance Criteria:**

**Given** JuhRadial MX is freshly installed
**When** the daemon starts for the first time
**Then** three themes are available: "Catppuccin Mocha" (default), "Vaporwave", "Matrix Rain"
**And** Catppuccin Mocha is active by default with 24px blur, 75% opacity, 180% saturation

---

### Story 4.3: Hot-Reload via inotify File Watching

As a theme designer,
I want theme changes to apply instantly without restarting the daemon,
So that I can iterate quickly on custom theme designs.

**Acceptance Criteria:**

**Given** the daemon is running and watching theme directories
**When** a theme JSON file is modified
**Then** the daemon detects the change via inotify within 100ms
**And** reloads and applies changes immediately if the theme is active

**Given** the active theme file is saved with syntax errors
**When** the daemon detects the change
**Then** it keeps the last valid version active and logs the validation error

---

### Story 4.4: GPU Performance Monitoring & Blur Fallback

As a Linux user on older hardware,
I want the menu to automatically disable blur if my GPU can't handle it,
So that I get smooth performance without manual configuration.

**Acceptance Criteria:**

**Given** the daemon is monitoring frame times during menu animations
**When** three consecutive frames take longer than 16.67ms (below 60fps)
**Then** the daemon disables blur rendering automatically
**And** switches to solid background maintaining 75% opacity

---

### Story 4.5: High Contrast Mode Support

As a Linux user with vision accessibility needs,
I want a high contrast mode that prioritizes clarity over aesthetics,
So that I can use the radial menu comfortably.

**Acceptance Criteria:**

**Given** high contrast mode is enabled in system settings
**When** the daemon detects the accessibility setting
**Then** background opacity is set to 95%, border opacity to 60%, all blur is disabled
**And** text/icon contrast meets WCAG AAA standards (7:1 ratio minimum)

---

### Story 4.6: Reduced Motion Support

As a Linux user sensitive to motion,
I want animations to be disabled when reduced motion is enabled,
So that the interface is comfortable to use.

**Acceptance Criteria:**

**Given** reduced motion is enabled in system settings
**When** the gesture button is pressed
**Then** the radial menu appears instantly (0ms transition)
**And** all slice highlight changes are instant (0ms)

---

## Epic 5: Haptic Feedback System - Stories

### Story 5.1: HID++ Protocol Research & Command Implementation

As a developer,
I want to send HID++ haptic commands via hidapi to the MX Master 4,
So that runtime haptic feedback works without writing to device memory.

**Acceptance Criteria:**

**Given** the MX Master 4 is connected via USB, Bolt, or Bluetooth
**When** the daemon initializes the haptic subsystem
**Then** it detects the mouse using vendor ID 0x046D
**And** validates that HID++ 2.0 protocol is supported

**Given** the mouse does not support haptics
**When** the daemon queries for haptic feature support
**Then** it disables the haptic subsystem gracefully and logs a warning

---

### Story 5.2: Configurable Haptic Intensity

As a Linux user,
I want to configure haptic feedback intensity from 0-100,
So that I can customize the tactile feedback to my preference.

**Acceptance Criteria:**

**Given** the configuration file at `~/.config/juhradial/config.toml`
**When** the daemon reads the haptic section
**Then** it loads the `haptic_intensity` value (0-100, default 50)

**Given** haptic intensity is set to 0
**When** any haptic event should trigger
**Then** no HID++ haptic command is sent

---

### Story 5.3: UX Haptic Profile Implementation

As a Linux user,
I want distinct haptic patterns for different menu interactions,
So that I can feel the difference between hovering, selecting, and errors.

**Acceptance Criteria:**

**Given** the radial menu appears
**When** the menu render completes
**Then** a haptic pulse at 20% intensity is sent (30ms duration)

**Given** the cursor highlights a new slice
**When** the cursor moves from slice N to slice N+1
**Then** a haptic pulse at 40% intensity is sent (40ms duration)

**Given** a slice is selected (gesture button released)
**When** the selection is confirmed
**Then** a haptic pulse at 80% intensity is sent (60ms duration)

**Given** an empty slice is selected
**When** the selection would trigger no action
**Then** a haptic pulse at 30% with double-tap pattern is sent

---

### Story 5.4: Runtime-Only Commands (No Memory Writes)

As a cross-platform mouse user,
I want JuhRadial MX to never write to my mouse's onboard memory,
So that my mouse configuration remains compatible with macOS/Windows.

**Acceptance Criteria:**

**Given** the haptic subsystem is initialized
**When** any haptic command is constructed
**Then** it uses only volatile/runtime HID++ commands
**And** no persistent memory write commands are ever used

**Given** the mouse is disconnected and reconnected
**When** the daemon re-initializes haptic support
**Then** no configuration is persisted on the device
**And** the mouse behaves identically to before JuhRadial MX was installed

---

### Story 5.5: Graceful Fallback & Error Handling

As a Linux user,
I want JuhRadial MX to work perfectly even if haptic feedback fails,
So that device compatibility issues don't break core functionality.

**Acceptance Criteria:**

**Given** the daemon cannot open the HID device
**When** initialization fails with permission error
**Then** all menu functionality continues to work normally without crashes

**Given** HID device handle becomes invalid mid-session
**When** the mouse is disconnected or sleeps
**Then** the daemon attempts to re-initialize haptic support on next menu appearance

---

### Story 5.6: Haptic Latency Optimization

As a Linux user,
I want haptic feedback to be imperceptible in latency,
So that the menu feels instantaneous and responsive.

**Acceptance Criteria:**

**Given** a haptic event is triggered
**When** measuring from event trigger to HID command send
**Then** the latency is less than 5ms (P95)

**Given** multiple haptic events occur rapidly (slice changes)
**When** the user moves the cursor quickly across slices
**Then** haptic commands are debounced with minimum 20ms gap between pulses

---

## Epic 6: Settings Dashboard - Stories

### Story 6.1: Plasmoid Shell & Interactive Mouse Preview

As a Linux user,
I want to open a Plasma widget that shows an interactive MX Master 4 image,
So that I can visually understand which button triggers the radial menu.

**Acceptance Criteria:**

**Given** JuhRadial MX is installed and the daemon is running
**When** I click the system tray icon or open the Plasmoid
**Then** the settings dashboard opens (minimum 800x600px)
**And** an SVG/PNG image of the MX Master 4 is displayed with the gesture button zone highlighted

**Given** the daemon is not running or mouse is not detected
**When** I open the settings dashboard
**Then** the mouse image is displayed in grayscale with an error message

---

### Story 6.2: Visual Radial Menu Editor

As a user customizing my workflow,
I want to visually edit the radial menu by clicking on slices,
So that I can configure actions without editing JSON files manually.

**Acceptance Criteria:**

**Given** the settings dashboard is open and a profile is selected
**When** I view the radial menu preview section
**Then** I see a full-size (280px diameter) radial menu with 8 slices plus center
**And** each slice displays its current icon, label, and accent color

**Given** I click on any slice
**When** the slice editor modal opens
**Then** I see fields for: icon picker, label input, action type dropdown, action value input

---

### Story 6.3: Icon Picker Component

As a user personalizing my radial menu,
I want to choose icons from emojis, system icons, or custom files,
So that I can visually identify each action at a glance.

**Acceptance Criteria:**

**Given** I am editing a slice in the slice editor modal
**When** I click the icon picker button
**Then** a tabbed dialog opens with three tabs: "Emoji", "System Icons", "Custom"

**Given** I am on the "Custom" tab
**When** I click "Browse"
**Then** a file picker opens accepting .svg, .png formats
**And** after selecting a valid file, the icon is copied to `~/.config/juhradial/icons/`

---

### Story 6.4: Profile Management Panel

As a user managing multiple workflows,
I want to create, edit, delete, and duplicate profiles,
So that I can organize different radial menu configurations.

**Acceptance Criteria:**

**Given** the settings dashboard is open
**When** I navigate to the "Profiles" tab
**Then** I see a list of all profiles with columns: Name, Icon, Description, App Classes
**And** buttons are visible: "New Profile", "Edit", "Delete", "Duplicate"

**Given** I select a profile and click "Delete"
**When** a confirmation dialog appears
**Then** the default profile cannot be deleted (button is disabled)

---

### Story 6.5: App-Specific Profile Assignment Table

As a user with different workflows per application,
I want to assign profiles to specific applications,
So that the correct radial menu appears automatically when I switch windows.

**Acceptance Criteria:**

**Given** I click "Add Assignment"
**When** I use "Detect Window" mode and click on an application window
**Then** the window class is detected via KWin D-Bus API
**And** the application name and icon are fetched from Plasma

---

### Story 6.6: Theme Preview & Selection with Live Toggle

As a user who values aesthetics,
I want to preview and select themes with a live toggle,
So that I can see how each theme looks before committing.

**Acceptance Criteria:**

**Given** I click "Preview Live" on a theme
**When** the preview activates
**Then** the radial menu preview updates to use the theme
**And** a countdown timer (10 seconds) auto-reverts if not applied

---

### Story 6.7: Haptic Intensity Controls with Live Test

As a user who values tactile feedback,
I want to adjust haptic intensity and test it immediately,
So that I can find the perfect vibration strength for my preference.

**Acceptance Criteria:**

**Given** I adjust any haptic slider
**When** I drag the slider
**Then** the value updates in real-time and auto-saves

**Given** I click a "Test" button
**When** the MX Master 4 is connected
**Then** the daemon sends the corresponding haptic command and I feel the vibration

---

### Story 6.8: Configuration Export & Import

As a user who manages multiple machines or backs up settings,
I want to export and import my complete JuhRadial configuration,
So that I can migrate settings between systems or recover from data loss.

**Acceptance Criteria:**

**Given** I click "Export Configuration"
**When** a file save dialog opens
**Then** a .zip is created containing: profiles.json, settings.json, custom icons, custom themes

**Given** I click "Import Configuration"
**When** I select a valid .zip file
**Then** I can choose to "Merge" or "Replace" existing configuration

---

## Epic 7: Distribution & Packaging - Stories

### Story 7.1: RPM Spec File & Build Configuration

As a package maintainer,
I want a complete RPM spec file for Fedora COPR,
So that JuhRadial MX can be built and distributed via DNF.

**Acceptance Criteria:**

**Given** the monorepo contains all components
**When** I create the RPM spec file at `packaging/fedora/juhradial-mx.spec`
**Then** the spec file defines: Name, Version, Release, License (GPL-3.0), Summary
**And** BuildRequires includes: rust, cargo, qt6-qtbase-devel, kf6-plasma-devel, systemd-rpm-macros

---

### Story 7.2: Systemd User Service Integration

As a user installing JuhRadial MX,
I want the daemon to start automatically on login and restart on crashes,
So that I don't have to manually manage the service.

**Acceptance Criteria:**

**Given** the RPM package contains the systemd service file
**When** the package is installed
**Then** the service file exists with `Restart=on-failure` and `RestartSec=5s`

**Given** the daemon crashes
**When** systemd detects the failure
**Then** the service automatically restarts after 5 seconds

---

### Story 7.3: Udev Rules for Non-Root Device Access

As a user without root privileges,
I want to access the MX Master 4 gesture button via evdev,
So that the daemon can function without requiring sudo.

**Acceptance Criteria:**

**Given** the RPM package includes the udev rules file
**When** the package is installed
**Then** the file `/usr/lib/udev/rules.d/99-juhradial-mx.rules` grants input group access

**Given** the current user is not in the `input` group
**When** the post-install script runs
**Then** the user is added to the input group with a logout notification

---

### Story 7.4: COPR Repository Setup & One-Command Install

As a Fedora user,
I want to install JuhRadial MX with a single DNF command,
So that I can start using it immediately without manual building.

**Acceptance Criteria:**

**Given** the COPR project `juhhally/juhradial-mx` is created
**When** I run: `sudo dnf copr enable juhhally/juhradial-mx && sudo dnf install juhradial-mx`
**Then** the package is downloaded, installed, and the service starts automatically

---

### Story 7.5: Configuration Backup on Package Update

As a user updating JuhRadial MX,
I want my custom profiles and settings to be backed up before the update,
So that I can recover my configuration if something goes wrong.

**Acceptance Criteria:**

**Given** JuhRadial MX is being upgraded
**When** the `%pre` script runs
**Then** a backup is created at `~/.config/juhradial/backups/{timestamp}/`
**And** the backup includes all configuration files

---

### Story 7.6: License Compliance & Attribution

As a FOSS contributor,
I want JuhRadial MX to properly declare its GPL-3.0 license and attributions,
So that users and distributors understand their rights and obligations.

**Acceptance Criteria:**

**Given** the monorepo root directory
**When** I check for license files
**Then** a `LICENSE` file exists with the full GPL-3.0 license text
**And** a `NOTICE` file exists with third-party attributions

---

## Epic 8: Advanced Features (P2) - Stories

### Story 8.1: Plasma Activities Detection Integration

As a Plasma user organizing work into Activities,
I want JuhRadial to detect the active Activity,
So that profile switching can be context-aware in the future.

**Acceptance Criteria:**

**Given** KDE Plasma Activities service is running
**When** juhradiald starts
**Then** it connects to D-Bus interface `org.kde.ActivityManager.Activities`
**And** the current Activity ID and name are fetched

**Given** Activities service is not available
**When** juhradiald attempts to connect
**Then** the daemon continues normal operation without Activity support

---

### Story 8.2: Activity-to-Profile Mapping Configuration

As a power user with multiple Plasma Activities,
I want to map each Activity to a profile or profile set,
So that my radial menu adapts to my current context automatically.

**Acceptance Criteria:**

**Given** I assign a profile to an Activity
**When** I select a profile from the dropdown and click "Save"
**Then** the mapping is saved to `~/.config/juhradial/activity-mappings.json`

---

### Story 8.3: Activity Switching Performance Validation

As a user switching between Activities frequently,
I want profile changes to happen instantly,
So that there's no visible delay when changing context.

**Acceptance Criteria:**

**Given** Activity-based profile mapping is enabled
**When** I switch Activities
**Then** the profile change completes within 5ms

---

### Story 8.4: Idle Animation - Matrix Rain Effect

As a user who loves cyberpunk aesthetics,
I want an optional Matrix rain effect on the radial menu,
So that the menu looks visually striking when idle.

**Acceptance Criteria:**

**Given** the "Matrix Rain" theme is selected
**When** the radial menu is displayed and idle
**Then** Matrix-style falling characters animate behind the menu slices at 30fps minimum
**And** CPU usage for the effect is less than 5%

---

### Story 8.5: Idle Animation - Particle System

As a user who prefers subtle visual effects,
I want gentle particle animations around the radial menu,
So that the menu feels alive without being distracting.

**Acceptance Criteria:**

**Given** a theme with `"animation.enableParticles": true` is selected
**When** the radial menu is displayed
**Then** 20-30 small particles float around the menu with random drift

**Given** the user enables "Reduced motion" in accessibility settings
**When** the radial menu appears
**Then** all particle animations are disabled automatically

---

### Story 8.6: P2 Features Settings Panel

As a user exploring advanced features,
I want a dedicated settings section for P2 features,
So that I can enable, disable, and configure experimental functionality.

**Acceptance Criteria:**

**Given** the settings dashboard is open
**When** I navigate to the "Advanced" tab
**Then** I see toggle switches for: "Plasma Activities Integration", "Idle Animations (Matrix Rain)", "Idle Animations (Particles)"

---

## Epic 9: Critical Wayland Fixes & Logi Options+ Dashboard

**Goal:** Fix the two critical blocking issues (haptic button detection, cursor position on Wayland) and build the professional Logi Options+ style settings dashboard.

**User Outcome:** The radial menu works correctly on Fedora KDE Plasma 6 Wayland with the MX Master 4, appearing at the cursor when the haptic thumb button is pressed. Users get a familiar, professional settings interface.

**Priority:** P0 (Blocking)
**Status:** Story 9.1 ✅ COMPLETED | Story 9.2 Pending

**Summary:** The core radial menu is now fully functional on KDE Plasma 6 Wayland with multi-monitor support. The solution uses KWin scripting for accurate cursor position detection and XWayland for overlay positioning - a hybrid approach that works around Wayland's security restrictions while maintaining full functionality.

---

### Story 9.1: Critical Wayland Fixes - Haptic Button, Cursor Position & Visual Polish

As a Linux user on Fedora KDE Plasma 6 Wayland with an MX Master 4,
I want the radial menu to appear at my cursor when I press the haptic thumb button,
So that I can use JuhRadialMX as intended with proper Wayland support.

**Status:** ✅ COMPLETED (2025-12-13)

**Actual Implementation (What Made It Work):**

The original approach (logid + ydotool + GTK4) was replaced with a more robust solution:

1. **Gesture Button Detection via HID++ / hidraw**
   - Rust daemon (`daemon/src/hidraw.rs`) directly reads HID++ reports from `/dev/hidraw*`
   - Detects gesture button press/release without requiring logid or evdev workarounds
   - No interference with Solaar or other Logitech software

2. **Multi-Monitor Cursor Position via KWin Scripting**
   - Problem: XWayland/xdotool clamps cursor position to a single monitor
   - Solution: KWin script (`/tmp/juhradial_show_menu.js`) uses `workspace.cursorPos` to get real Wayland cursor coordinates
   - Daemon triggers KWin script via D-Bus: `qdbus org.kde.kwin.Scripting /Scripting org.kde.kwin.Scripting.loadScript`
   - KWin script calls back to daemon with `ShowMenuAtCursor(x, y)` via D-Bus

3. **Overlay Window Positioning via XWayland**
   - Problem: Native Wayland doesn't allow apps to position their own windows
   - Solution: Force XWayland platform in overlay: `os.environ["QT_QPA_PLATFORM"] = "xcb"`
   - This allows `QWidget.move(x, y)` to work correctly across all monitors

4. **Taskbar Icon Hidden with ToolTip Window Type**
   - Problem: `X11BypassWindowManagerHint` broke multi-monitor positioning
   - Solution: Use `Qt.WindowType.ToolTip` - hides from taskbar while preserving positioning

5. **Visual Polish**
   - Hover effect changed to neutral (white overlay with 45 alpha instead of colored)
   - Icon backgrounds made neutral (surface colors instead of accent colors)
   - Icon sizes increased (26px radius) with subtle glow ring on hover
   - Emoji icon spacing fixed (smile no longer touches eyes or circle border)

6. **Desktop Launcher**
   - Launcher script: `juhradial-mx.sh` (kills existing instances, starts overlay + daemon)
   - Desktop entry: `juhradial-mx.desktop` with autostart enabled
   - Beautiful SVG icon: `assets/juhradial-mx.svg` (Catppuccin Mocha colors, 8-slice radial design)

**Key Files Modified:**
- `overlay/juhradial-overlay.py` - Main overlay with all visual fixes
- `daemon/src/hidraw.rs` - KWin script trigger for cursor position
- `juhradial-mx.sh` - Launcher script
- `juhradial-mx.desktop` - Desktop entry
- `assets/juhradial-mx.svg` - Application icon

**Git Commits:**
- `2e05a62` - Multi-monitor radial menu with KWin scripting
- `4f7fa4c` - Enhanced UI, desktop launcher, and improved icons

**Acceptance Criteria:** ✅ ALL MET
- ✅ Gesture button triggers radial menu correctly
- ✅ Menu appears at cursor position on ALL monitors
- ✅ Hover highlighting is neutral (no color tint)
- ✅ No taskbar icon when menu appears
- ✅ Desktop shortcut works with beautiful icon

---

### Story 9.2: Logi Options+ Style Settings Dashboard

As a Linux MX Master user,
I want a settings window that looks exactly like Logi Options+ (Windows/macOS),
So that I have a familiar, professional interface for configuring my mouse.

**Key Design Requirements:**
- Window: 1160x740px, forced dark theme, black background
- Two-column layout: device image (40%) + settings cards (60%)
- Cards: Point & Scroll, Button Assignments, Thumbwheel, SmartShift, App-specific, Device Info
- Instant apply (no Apply button), stays on top
- Exact Logi Options+ color palette: #000000 bg, #111111 cards, #00A0E9 accent

**Acceptance Criteria:**
- Window matches Logi Options+ layout exactly
- All setting cards present and functional
- Instant apply behavior
- Professional dark theme
