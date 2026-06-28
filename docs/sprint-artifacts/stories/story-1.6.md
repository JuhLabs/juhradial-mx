# Story 1.6: Setup udev Rules and systemd Service

## Story Info
- **Epic:** 1 - Foundation & Architecture Spike
- **Story ID:** 1.6
- **Priority:** P0 (Critical)
- **Estimate:** S (Small)
- **Status:** Complete

## Story
As a developer,
I want udev rules and a systemd user service template,
So that the daemon can run automatically without root privileges.

## Acceptance Criteria

### AC1: udev Rules File
**Given** I am preparing the packaging structure
**When** I create `packaging/udev/99-juhradialmx.rules`
**Then** the file contains rules for Logitech vendor ID 0x046d
**And** the rules set MODE="0660" and GROUP="input"

### AC2: systemd Service File
**Given** I am creating the systemd service
**When** I create `packaging/systemd/juhradialmx-daemon.service`
**Then** the service file contains `Type=simple`, `ExecStart=/usr/bin/juhradiald`, `Restart=on-failure`, `RestartSec=5s`
**And** the `[Install]` section includes `WantedBy=default.target`

### AC3: Auto-Restart on Crash
**Given** the daemon crashes
**When** systemd detects the process has exited with an error
**Then** systemd automatically restarts the daemon within 5 seconds

## Dev Notes

### Architecture Reference
From `docs/architecture.md`:
- udev rules for non-root input device access
- systemd user service with auto-restart
- User added to `input` group during install

### File Locations
- udev rules: `/etc/udev/rules.d/99-juhradialmx.rules` (installed)
- systemd service: `/usr/lib/systemd/user/juhradialmx-daemon.service` (installed)
- Source files in `packaging/` directory

## Tasks

- [x] 1. Verify/update udev rules file
  - [x] 1.1 Confirm rules exist in packaging/udev/
  - [x] 1.2 Verify Logitech vendor ID rules
  - [x] 1.3 Verify MODE and GROUP settings
  - [x] 1.4 Add installation instructions as comments

- [x] 2. Create systemd user service file
  - [x] 2.1 Create packaging/systemd/juhradialmx-daemon.service
  - [x] 2.2 Set Type=simple
  - [x] 2.3 Set ExecStart path
  - [x] 2.4 Configure Restart=on-failure
  - [x] 2.5 Set RestartSec=5s
  - [x] 2.6 Add WantedBy=default.target

- [x] 3. Add service management documentation
  - [x] 3.1 Document service enable/start commands
  - [x] 3.2 Document status checking
  - [x] 3.3 Document log viewing

## Testing Requirements

- udev rules file has correct syntax
- systemd service file passes validation
- Service configuration matches acceptance criteria
- Documentation is clear and accurate

## Definition of Done
- [x] All tasks completed
- [x] All acceptance criteria verified
- [x] Files pass syntax validation
- [x] Code reviewed
- [x] Story marked complete in sprint-status.yaml

---

## Dev Agent Record

### Agent Model Used
Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References
No issues encountered.

### Completion Notes
Story 1.6 completed - udev rules and systemd service setup:

**udev Rules (AC1):**
- Already created in Story 1.4 at `/packaging/udev/99-juhradialmx.rules`
- Contains Logitech vendor ID 0x046d rules
- MODE="0660", GROUP="input" for non-root access
- TAG+="uaccess" for systemd-logind integration
- Covers USB, Bluetooth, and Bolt receiver variants

**systemd Service (AC2):**
- Created `/packaging/systemd/juhradialmx-daemon.service`
- Type=simple, ExecStart=/usr/bin/juhradiald
- Restart=on-failure, RestartSec=5s
- WantedBy=default.target
- Includes security hardening (NoNewPrivileges, ProtectSystem, etc.)
- Resource limits (MemoryMax=100M, CPUQuota=50%)
- Embedded documentation for installation and management

**Auto-Restart (AC3):**
- Restart=on-failure ensures daemon restarts on crash
- RestartSec=5s provides 5-second delay before restart
- StartLimitBurst=5 prevents infinite restart loops

### File List
**Verified (from Story 1.4):**
- `/packaging/udev/99-juhradialmx.rules`

**Created:**
- `/packaging/systemd/juhradialmx-daemon.service`

### Change Log
| Date | Change | Author |
|------|--------|--------|
| 2025-12-12 | Story 1.6 completed - systemd service file created | James (Dev Agent) |
