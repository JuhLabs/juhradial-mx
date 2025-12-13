---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - docs/prd.md
  - docs/ux-design-specification.md
  - docs/juhradialmxbrief.md
workflowType: 'architecture'
lastStep: 8
status: 'complete'
completedAt: '2025-12-11'
project_name: 'JuhRadial MX'
user_name: 'Julianhermstad'
date: '2025-12-11'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

JuhRadial MX requires 10 functional capabilities spanning three priority levels:

| Priority | Count | Focus |
|----------|-------|-------|
| P0 (Critical) | 4 | Gesture detection, radial menu display, action execution, per-app profiles |
| P1 (High) | 4 | Theme engine, haptic feedback, settings dashboard, custom icons |
| P2 (Medium) | 2 | Plasma Activities integration, idle animations |

The core loop is: **evdev input → daemon processing → IPC signal → overlay display → user selection → action execution**

**Non-Functional Requirements:**

| Requirement | Target | Architectural Impact |
|-------------|--------|---------------------|
| Menu latency | <50ms | Pre-warm overlay, hot daemon |
| Action execution | <10ms | Direct D-Bus, no shell spawn for common actions |
| Frame budget | <16ms | GPU-accelerated blur via KWin |
| Memory | <50MB total | Lazy-load themes, cache wisely |
| CPU idle | <1% | Event-driven architecture, no polling |
| Wayland + X11 | Both supported | Layer-shell primary, X11 fallback |

**Scale & Complexity:**

- Primary domain: Linux desktop application (KDE Plasma 6 ecosystem)
- Complexity level: Medium-High
- Estimated architectural components: 4 major + supporting utilities

### Phase-Aligned Architecture Scope

**Phase 1 (P0) - Must Work Day One:**
- Evdev gesture button detection (FR-001)
- 8-slice radial menu display (FR-002)
- Action execution: shortcuts, commands, D-Bus (FR-003)
- Per-application profile switching (FR-004)
- Single theme (Catppuccin Mocha)
- Basic haptic feedback

**Phase 2 (P1) - Architect For, Implement Later:**
- Full theme engine with hot-reload (FR-005)
- Complete haptic intensity controls (FR-006)
- Settings dashboard with visual editor (FR-007)
- Custom icon system (FR-008)

**Phase 3 (P2) - Leave Room, Don't Design Now:**
- Plasma Activities integration (FR-009)
- Idle animations like Matrix rain (FR-010)

### Technical Constraints & Dependencies

**Hard Constraints:**
1. No onboard mouse memory writes (cross-platform compatibility)
2. No elevated privileges for normal operation (udev rules for device access)
3. Must work on Wayland (layer-shell) and X11 (fallback)
4. Development on macOS, deployment on Linux only
5. Settings dashboard MUST be Plasma Plasmoid (native theme integration)

**Platform Dependencies:**

| Dependency | Version | Purpose |
|------------|---------|---------|
| Plasma | 6.x | Widget framework, KWin scripting |
| Rust | 1.70+ | Daemon compilation |
| systemd | 250+ | Service management |
| D-Bus | Session bus | IPC |
| evdev | Kernel | Input subsystem |
| KWin | 6.x | Overlay rendering, blur |

### Critical Architectural Decision Required

**KWin Script vs QML Overlay:**

The PRD suggests KWin script (TypeScript) for the radial menu overlay, but QML (as part of the Plasma widget) may be simpler. This is a critical decision with trade-offs:

| Approach | Pros | Cons |
|----------|------|------|
| **KWin Script** | Native layer-shell, better Wayland support | Separate from widget, TypeScript |
| **QML Overlay** | Unified codebase with dashboard, simpler | May have layer-shell limitations |

**Decision needed before proceeding to component architecture.**

### Performance Budget (First-Class Requirement)

The <50ms menu latency is non-negotiable. Architecture must ensure:

| Component | Budget | Priority |
|-----------|--------|----------|
| Blur effect render | 8ms | Critical (GPU) |
| Selection calculation | 1ms | Critical (CPU) |
| Haptic command send | 2ms | High (async) |
| Animation frame | 16ms (60fps) | Must hit |

**Blur Fallback Strategy:**
- Monitor GPU frame time during blur rendering
- If sustained >16ms, automatically fall back to solid background
- Fallback is a **first-class feature**, not a TODO
- Must be tested and ready for Phase 1 launch

### Development Environment Strategy

**macOS → Linux Workflow:**

| Component | macOS Capability | Linux Required |
|-----------|------------------|----------------|
| Rust daemon logic | ✅ Full development | Final integration |
| Evdev parsing | ⚠️ Recorded events only | Real device testing |
| D-Bus IPC | ⚠️ dbus-rs unit tests | Session bus integration |
| KWin overlay | ❌ Cannot test | **Critical** - VM or hardware |
| Haptic HID++ | ❌ Cannot test | **Critical** - real mouse |

**Required Infrastructure:**
- Linux VM (UTM/QEMU) with Plasma 6 for overlay testing
- USB passthrough for haptic testing
- CI pipeline on Linux runner for integration tests
- Recorded evdev events for macOS unit tests

### Cross-Cutting Concerns Identified

1. **IPC Protocol (D-Bus):**
   - `ShowMenu(x, y, profile)` - Position from cursor
   - `HideMenu()` - Dismiss overlay
   - `SliceHovered(index)` - Haptic sync
   - `ActionTriggered(index)` - User selection
   - `ProfileChanged(name)` - App switch notification

2. **Performance Budget:**
   - Blur rendering: 8ms (GPU)
   - Selection calculation: 1ms (CPU)
   - Haptic command: 2ms (async)
   - Animation frame: 16ms total

3. **Theme System Architecture:**
   - JSON configuration schema
   - Hot-reload via file watching
   - Asset loading (noise textures, icons)
   - Three bundled themes + custom support

4. **Error Handling Strategy:**
   - Haptic failures: Silent (graceful degradation)
   - Blur performance issues: Automatic fallback to solid background
   - Mouse disconnect mid-menu: Close immediately, no action
   - Daemon crash: Systemd auto-restart

5. **Multi-Monitor Support:**
   - Menu appears on monitor with cursor
   - Edge clamping logic in widget (QML)
   - Cursor position captured at button-down time

6. **Quality & Testing Strategy:**

| Component | Testable on macOS | Risk Level | Mitigation |
|-----------|-------------------|------------|------------|
| Rust daemon (logic) | ✅ Yes (mocks) | Low | Standard unit tests |
| Evdev parsing | ⚠️ Partial | Medium | Recorded event replay |
| D-Bus IPC | ⚠️ Partial | Medium | dbus-rs mock server |
| KWin overlay | ❌ No | **High** | Linux VM required |
| Haptic HID++ | ❌ No | **High** | USB passthrough testing |
| Full integration | ❌ No | **Critical** | CI on Linux runner |

**Testing Requirements:**
- Unit test coverage: 80%+ for daemon logic
- Performance benchmarks: Automated <50ms verification
- Integration environment: Linux VM with Plasma 6
- Real hardware testing: Final validation before release

## Starter Template Evaluation

### Primary Technology Domain

Linux desktop application (KDE Plasma 6 ecosystem) - Multi-component monorepo architecture requiring separate foundations for each component.

### Critical Decision: KWin Script for Overlay

**Decision:** The radial menu overlay will be rendered by a **KWin Script (TypeScript)**, not QML.

**Rationale:**
- Native layer-shell support on Wayland
- Guaranteed access to KWin compositor blur
- Bypasses normal window positioning rules
- Unanimous team consensus

**Component Responsibilities:**

| Component | Responsibility |
|-----------|---------------|
| **Rust Daemon** | Input detection, haptics, profile management, D-Bus server |
| **KWin Script** | Radial menu overlay rendering, slice selection visual |
| **Plasma Widget** | System tray, settings dashboard, configuration UI |

### Project Structure: Monorepo

```
juhradial-mx/
├── Makefile              # Unified build commands
├── README.md
├── daemon/               # Rust daemon (Cargo)
│   ├── Cargo.toml
│   ├── src/
│   └── benches/          # criterion benchmarks
├── widget/               # Plasma widget (QML)
│   └── org.kde.juhradialmx/
├── kwin-script/          # Overlay script (TypeScript)
│   ├── package.json
│   └── src/
├── themes/               # Shared theme assets
├── packaging/            # RPM spec, udev rules
└── .github/workflows/    # CI on Linux runner
```

### Initialization Commands

**Project Setup:**
```bash
mkdir juhradial-mx && cd juhradial-mx
git init
```

**Daemon (Rust):**
```bash
cargo new daemon --name juhradiald
cd daemon
cargo add evdev@0.13 zbus@5 tokio@1 --features tokio/full
cargo add serde@1 serde_json@1 --features serde/derive
cargo add clap@4 --features derive
cargo add tracing@0.1 tracing-subscriber@0.3
cargo add criterion --dev  # Performance benchmarks
```

**Widget (Plasma 6 - requires Linux):**
```bash
# On Linux with Plasma 6 SDK
kpackagetool6 --type Plasma/Applet --create org.kde.juhradialmx
```

**KWin Script (TypeScript):**
```bash
mkdir kwin-script && cd kwin-script
npm init -y
npm install typescript --save-dev
npm install --save-dev @opekope2/kwin-script-types
```

**Root Makefile:**
```makefile
.PHONY: all daemon widget kwin-script clean install

all: daemon kwin-script
	@echo "Build complete. Widget requires Linux."

daemon:
	cd daemon && cargo build --release

kwin-script:
	cd kwin-script && npm run build

test:
	cd daemon && cargo test
	cd daemon && cargo bench

clean:
	cd daemon && cargo clean
	cd kwin-script && rm -rf dist/

install:
	# Installation commands for Linux
```

### Architectural Decisions Provided by Starter

**Language & Runtime:**
- Rust 1.70+ with Tokio async runtime for daemon
- TypeScript → ES5 for KWin script (compiled)
- QML/JavaScript for Plasma widget

**D-Bus IPC:**
- zbus 5.x (pure Rust, async, no C dependencies)
- Session bus: `org.kde.juhradialmx`

**Input Handling:**
- evdev 0.13.x crate for Linux input events
- Async event stream with tokio integration

**Performance Testing:**
- criterion crate for daemon benchmarks
- Target: verify <50ms latency in CI

**Build Tooling:**
- Cargo for Rust daemon
- npm + TypeScript for KWin script
- kpackagetool6 for Plasma widget (Linux only)
- Root Makefile for unified commands
- GitHub Actions on Linux runner for CI

### Test Strategy Per Component

| Component | Unit Tests | Integration | E2E | Tool |
|-----------|------------|-------------|-----|------|
| Rust daemon | ✅ 80%+ coverage | ⚠️ Linux CI | ❌ Manual | cargo test |
| KWin script | ❌ Limited | ❌ Manual | ❌ Manual | Manual protocol |
| Plasma widget | ⚠️ qmltest | ❌ Manual | ❌ Manual | Snapshot testing |

### First Implementation Story: Architecture Spike

**Title:** Validate end-to-end architecture

**Acceptance Criteria:**
- [ ] Rust daemon detects gesture button press via evdev (mocked or real)
- [ ] Daemon emits D-Bus signal `MenuRequested(x, y)`
- [ ] KWin script receives signal and shows test rectangle
- [ ] Rectangle appears at cursor position
- [ ] Validates: evdev → Rust → D-Bus → KWin pipeline works

**Note:** This spike validates the architecture before investing in full implementation.

## Core Architectural Decisions

_Decisions made via party mode consensus with Winston (Architect), Sally (UX), Amelia (Developer), Murat (Test), and John (PM)._

### ADR-001: Configuration Storage

**Decision:** Pure JSON files with schema validation

**Context:** Need to store user profiles, theme selections, and application-specific configurations.

**Options Considered:**
1. SQLite database
2. Pure JSON files
3. TOML configuration
4. KConfig integration

**Chosen:** Pure JSON files

**Rationale:**
- Human-readable and editable
- No database dependencies
- Easy to backup and version control
- Matches theme file format (consistency)
- JSON Schema provides validation without binary dependencies

**Consequences:**
- Configuration at: `~/.config/juhradial/`
- Schema validation at startup
- Hot-reload via inotify file watching

**Vote:** Unanimous (5/5)

---

### ADR-002: Device Access Strategy

**Decision:** udev rules for non-root input device access

**Context:** Daemon needs access to evdev input device for gesture button detection.

**Options Considered:**
1. Run daemon as root
2. udev rules + user group
3. polkit integration
4. Flatpak portal

**Chosen:** udev rules + user group

**Rationale:**
- Industry standard for input devices (Solaar, libinput)
- No elevated privileges for daemon process
- Simple installation via RPM scriptlet
- User added to `input` group during install

**Consequences:**
- Packaging includes `/etc/udev/rules.d/99-juhradial-mx.rules`
- Post-install script adds user to input group
- Logout/login required after first install

**Vote:** Unanimous (5/5)

---

### ADR-003: D-Bus Interface Design

**Decision:** Single interface with method + signal pairs

**Context:** IPC between Rust daemon, KWin script, and Plasma widget.

**Options Considered:**
1. Multiple interfaces (Daemon, Overlay, Widget)
2. Single unified interface
3. Custom socket protocol
4. Shared memory

**Chosen:** Single unified interface

**Rationale:**
- Simpler introspection and debugging
- All components use same bus name
- Signals broadcast to all listeners
- Methods called by any authorized client

**Interface Definition:**
```
org.kde.juhradialmx.Daemon
├── Methods
│   ├── ShowMenu(x: i32, y: i32, profile: s)
│   ├── HideMenu()
│   ├── TriggerAction(slice_index: u8)
│   ├── SetProfile(name: s)
│   └── ReloadConfig()
├── Signals
│   ├── MenuRequested(x: i32, y: i32, profile: s)
│   ├── MenuDismissed()
│   ├── SliceHovered(index: u8)
│   ├── ActionExecuted(index: u8, success: b)
│   └── ProfileChanged(name: s)
└── Properties
    ├── CurrentProfile: s
    ├── HapticsEnabled: b
    └── DaemonVersion: s
```

**Vote:** Unanimous (5/5)

---

### ADR-004: QML Component Architecture

**Decision:** Feature-based folder structure

**Context:** Widget needs organized QML components for dashboard, tray, and settings.

**Options Considered:**
1. Flat structure (all QML in one folder)
2. Type-based (components/, pages/, dialogs/)
3. Feature-based (profile-editor/, theme-picker/, etc.)

**Chosen:** Feature-based folders

**Rationale:**
- Scales with feature additions
- Clear ownership boundaries
- Easier to locate related code
- Aligns with Phase 2 expansion plans

**Structure:**
```
widget/org.kde.juhradialmx/contents/ui/
├── main.qml
├── FullRepresentation.qml
├── CompactRepresentation.qml
├── components/
│   ├── SliceButton.qml
│   ├── ProfileCard.qml
│   └── ThemeThumbnail.qml
└── pages/
    ├── ProfilesPage.qml
    ├── ThemesPage.qml
    └── SettingsPage.qml
```

**Vote:** Unanimous (5/5)

---

### ADR-005: Packaging Strategy

**Decision:** COPR-only for MVP, AUR/Flathub post-launch

**Context:** Need to distribute JuhRadial MX to Fedora users.

**Options Considered:**
1. COPR only
2. COPR + AUR simultaneously
3. Flatpak first
4. Manual installation only

**Chosen:** COPR only for MVP

**Rationale:**
- Fedora is primary target (stated in brief)
- COPR spec already written and tested
- Single package format reduces testing burden
- AUR can be community-contributed post-launch
- Flatpak has systemd service complications

**Consequences:**
- Primary install: `sudo dnf copr enable juhhally/juhradial-mx && sudo dnf install juhradial-mx`
- AUR PKGBUILD: Community contribution welcomed
- Flatpak: Deferred to Phase 2 (portal considerations)

**Vote:** Unanimous (5/5)

---

## Implementation Patterns

_Coding conventions and patterns established via party mode consensus._

### Naming Conventions

| Context | Convention | Example |
|---------|------------|---------|
| JSON config keys | snake_case | `"default_profile"`, `"haptic_intensity"` |
| D-Bus signals | PascalCase | `MenuRequested`, `SliceHovered` |
| D-Bus methods | PascalCase | `ShowMenu`, `TriggerAction` |
| Rust modules | snake_case | `evdev_handler.rs`, `dbus_server.rs` |
| Rust types | PascalCase | `ProfileManager`, `GestureEvent` |
| TypeScript files | kebab-case | `menu-renderer.ts`, `dbus-client.ts` |
| QML files | PascalCase | `SliceButton.qml`, `ProfileCard.qml` |

### Structure Patterns

**Rust Daemon:**
```rust
// Module organization
src/
├── main.rs          // Entry point, CLI parsing
├── lib.rs           // Public API for testing
├── config.rs        // JSON loading, validation
├── evdev.rs         // Input event handling
├── dbus.rs          // zbus server implementation
├── hidpp.rs         // Logitech HID++ haptic commands
├── profiles.rs      // Profile management logic
├── actions.rs       // Action execution (shortcuts, commands, D-Bus)
└── theme.rs         // Theme file parsing
```

**KWin Script:**
```typescript
// Module organization
src/
├── main.ts          // Entry point, KWin registration
├── menu-renderer.ts // Radial menu drawing
├── dbus-client.ts   // D-Bus signal handling
├── theme-loader.ts  // Theme JSON parsing
└── geometry.ts      // Slice calculations, hit testing
```

### Format Patterns

**Logging Format (Rust):**
```rust
// Structured logging with tracing
tracing::info!(
    profile = %profile_name,
    slice = slice_index,
    "Action triggered"
);
```

**Error Handling Pattern:**
```rust
// Graceful degradation for non-critical failures
match haptic_manager.pulse(intensity) {
    Ok(_) => tracing::debug!("Haptic pulse sent"),
    Err(e) => tracing::warn!(error = %e, "Haptic failed, continuing silently"),
}
```

### Communication Patterns

**D-Bus Signal Flow:**
```
[Gesture Button Press]
        │
        ▼
[Rust Daemon: evdev]
        │
        ▼
[D-Bus Signal: MenuRequested(x, y, profile)]
        │
        ├──────────────────┐
        ▼                  ▼
[KWin Script]         [Plasma Widget]
  - Show menu           - Update tray state
  - Track hover
        │
        ▼
[D-Bus Signal: SliceHovered(index)]
        │
        ▼
[Rust Daemon: HID++]
  - Send haptic pulse
```

### Process Patterns

**Startup Sequence:**
1. systemd starts `juhradiald.service`
2. Daemon loads `~/.config/juhradial/config.json`
3. Daemon opens evdev device (via udev rules)
4. Daemon registers D-Bus interface
5. Daemon emits `Ready` signal
6. KWin script/widget connect on signal

**Shutdown Sequence:**
1. systemd sends SIGTERM
2. Daemon closes evdev device
3. Daemon emits `Shutdown` signal
4. Daemon unregisters D-Bus interface
5. Exit with code 0

---

## Project Structure

_Complete directory layout for JuhRadial MX monorepo._

```
juhradial-mx/
├── Makefile                          # Unified build commands
├── README.md                         # Project overview
├── LICENSE                           # GPL-3.0
│
├── daemon/                           # Rust daemon (juhradiald)
│   ├── Cargo.toml
│   ├── Cargo.lock
│   ├── src/
│   │   ├── main.rs                   # Entry point, CLI
│   │   ├── lib.rs                    # Public API for testing
│   │   ├── config.rs                 # JSON config loading
│   │   ├── evdev.rs                  # Input event handling
│   │   ├── dbus.rs                   # zbus server
│   │   ├── hidpp.rs                  # HID++ haptic commands
│   │   ├── profiles.rs               # Profile management
│   │   ├── actions.rs                # Action execution
│   │   └── theme.rs                  # Theme parsing
│   └── benches/
│       └── latency.rs                # criterion benchmarks
│
├── kwin-script/                      # KWin overlay (TypeScript)
│   ├── package.json
│   ├── tsconfig.json
│   ├── metadata.json                 # KWin script metadata
│   └── src/
│       ├── main.ts                   # Entry point
│       ├── menu-renderer.ts          # Radial menu drawing
│       ├── dbus-client.ts            # D-Bus signal handling
│       ├── theme-loader.ts           # Theme JSON parsing
│       └── geometry.ts               # Slice calculations
│
├── widget/                           # Plasma widget (QML)
│   └── org.kde.juhradialmx/
│       ├── metadata.json
│       └── contents/
│           ├── ui/
│           │   ├── main.qml
│           │   ├── FullRepresentation.qml
│           │   ├── CompactRepresentation.qml
│           │   ├── components/
│           │   │   ├── SliceButton.qml
│           │   │   ├── ProfileCard.qml
│           │   │   └── ThemeThumbnail.qml
│           │   └── pages/
│           │       ├── ProfilesPage.qml
│           │       ├── ThemesPage.qml
│           │       └── SettingsPage.qml
│           └── config/
│               └── config.qml
│
├── themes/                           # Shared theme assets
│   ├── catppuccin-mocha/
│   │   ├── theme.json
│   │   └── noise-overlay.png
│   ├── vaporwave/
│   │   ├── theme.json
│   │   └── noise-overlay.png
│   ├── matrix-rain/
│   │   ├── theme.json
│   │   └── noise-overlay.png
│   └── shared-icons/
│       ├── copy.svg
│       ├── paste.svg
│       ├── undo.svg
│       └── ...
│
├── packaging/                        # Distribution files
│   ├── juhradial-mx.spec             # RPM spec for COPR
│   ├── 99-juhradial-mx.rules         # udev rules
│   └── juhradiald.service            # systemd user service
│
├── docs/                             # Documentation
│   ├── prd.md
│   ├── architecture.md               # This document
│   └── ux-design-specification.md
│
└── .github/
    └── workflows/
        ├── ci.yml                    # Linux CI (build + test)
        └── release.yml               # COPR publish on tag
```

### Integration Boundaries

| Source | Target | Protocol | Data |
|--------|--------|----------|------|
| Daemon → KWin | D-Bus Signal | `MenuRequested(x, y, profile)` |
| KWin → Daemon | D-Bus Signal | `SliceHovered(index)` |
| KWin → Daemon | D-Bus Signal | `ActionTriggered(index)` |
| Widget → Daemon | D-Bus Method | `SetProfile(name)` |
| Widget → Daemon | D-Bus Method | `ReloadConfig()` |
| Daemon → Widget | D-Bus Signal | `ProfileChanged(name)` |
| Daemon → Mouse | HID++ | Haptic pulse command |

### FR-to-File Mapping

| FR | Description | Primary File(s) |
|----|-------------|-----------------|
| FR-001 | Gesture detection | `daemon/src/evdev.rs` |
| FR-002 | Radial menu display | `kwin-script/src/menu-renderer.ts` |
| FR-003 | Action execution | `daemon/src/actions.rs` |
| FR-004 | Per-app profiles | `daemon/src/profiles.rs` |
| FR-005 | Theme engine | `daemon/src/theme.rs`, `kwin-script/src/theme-loader.ts` |
| FR-006 | Haptic feedback | `daemon/src/hidpp.rs` |
| FR-007 | Settings dashboard | `widget/org.kde.juhradialmx/contents/ui/pages/` |
| FR-008 | Custom icons | `themes/shared-icons/`, `widget/.../components/` |
| FR-009 | Activities integration | `daemon/src/profiles.rs` (future) |
| FR-010 | Idle animations | `kwin-script/src/menu-renderer.ts` (future) |

---

## Validation Results

_Architecture validation completed via party mode consensus._

### Coherence Check

| Check | Status | Notes |
|-------|--------|-------|
| ADR consistency | ✅ Pass | All decisions use same D-Bus bus, JSON configs |
| Pattern alignment | ✅ Pass | Naming conventions applied uniformly |
| Component boundaries | ✅ Pass | Clear separation: daemon/kwin/widget |
| Dependency isolation | ✅ Pass | No circular dependencies |
| Build system | ✅ Pass | Makefile unifies all components |

### Coverage Check

| Requirement Type | Count | Covered | Coverage |
|------------------|-------|---------|----------|
| P0 Functional | 4 | 4 | 100% |
| P1 Functional | 4 | 4 | 100% |
| P2 Functional | 2 | 2 (future-proofed) | 100% |
| Non-Functional | 5 | 5 | 100% |

### Risk Assessment

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| KWin API changes | Medium | Pin to KWin 6.x, type definitions | Mitigated |
| Blur performance | High | First-class fallback to solid | Mitigated |
| macOS dev limitations | Medium | Linux VM, CI pipeline | Mitigated |
| HID++ compatibility | Low | Logitech protocol well-documented | Accepted |

### Readiness Verdict

**Architecture Status:** ✅ **READY FOR IMPLEMENTATION**

- All P0/P1 requirements have clear implementation paths
- Critical decisions (KWin Script, D-Bus design) are finalized
- Performance budgets are defined with fallback strategies
- Testing strategy accounts for cross-platform development
- Packaging approach is validated and spec file exists

---

## Completion Summary

### Deliverables

1. **Architecture Decision Document** (this file)
   - 5 ADRs covering storage, device access, IPC, QML structure, packaging
   - Implementation patterns for all three components
   - Complete project structure with file mapping
   - Validation results with 100% requirement coverage

2. **First Story Ready**
   - Architecture Spike story defined with acceptance criteria
   - Validates: evdev → Rust → D-Bus → KWin pipeline

### Handoff to Implementation

**Recommended Epic Sequence:**

1. **Epic 1: Foundation**
   - Architecture spike (validate pipeline)
   - Project scaffolding (create directory structure)
   - CI/CD setup (Linux runner, COPR integration)

2. **Epic 2: Core Loop (P0)**
   - FR-001: Gesture detection
   - FR-002: Radial menu display
   - FR-003: Action execution
   - FR-004: Per-app profiles

3. **Epic 3: Polish (P1)**
   - FR-005: Theme engine
   - FR-006: Haptic feedback
   - FR-007: Settings dashboard
   - FR-008: Custom icons

4. **Epic 4: Extras (P2)**
   - FR-009: Activities integration
   - FR-010: Idle animations

### Architecture Completion Certificate

```
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ARCHITECTURE DECISION DOCUMENT                              ║
║   Status: COMPLETE                                            ║
║                                                               ║
║   Project: JuhRadial MX                                       ║
║   Date: 2025-12-11                                            ║
║   Author: Winston (Architect) with Party Mode Panel           ║
║                                                               ║
║   Panel: Sally (UX), Amelia (Dev), Murat (Test), John (PM)    ║
║   Decision Method: Democratic consensus (unanimous votes)     ║
║                                                               ║
║   Ready for: Epic & Story creation workflow                   ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
```

---

_Document generated via BMAD Architecture Workflow with Party Mode consensus._
