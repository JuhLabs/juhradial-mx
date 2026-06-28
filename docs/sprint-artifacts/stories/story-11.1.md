# Story 11.1: Community Feedback Polish & Bug Fixes

Status: ready-for-dev

## Story

As a JuhRadial MX user,
I want the radial menu haptics, settings dashboard, and multi-device support to work flawlessly,
so that I have a premium experience that rivals Logi Options+ on Linux.

## Context

**Community Milestone:** 6 GitHub stars + $10 USD donation received! This story addresses user-reported issues and adds polish to capitalize on momentum.

**Issues Identified:**
1. Haptic vibration stopped working when hovering over radial menu slices
2. Scrolling in settings dashboard accidentally changes slider values
3. Sensitivity changes via scroll wheel not reflecting in settings UI
4. Settings may reset unexpectedly when applying changes
5. Two tabs not implemented (Logitech Flow / multi-device support)

## Acceptance Criteria

### AC1: Haptic Hover Feedback Restored
- [ ] Hovering over different slices in the radial menu triggers haptic feedback
- [ ] D-Bus `TriggerHaptic("slice_change")` call successfully reaches daemon
- [ ] Haptic works in both hold mode and toggle (tap) mode
- [ ] No regression in other haptic events (menu_appear, confirm)

### AC2: Settings Dashboard Scroll Isolation
- [ ] Scrolling the settings page does NOT change slider values
- [ ] Sliders only respond to direct click-drag interaction
- [ ] Sliders respond to arrow keys when focused
- [ ] Mouse wheel scrolls the page, not individual sliders

### AC3: Settings Persistence
- [ ] All settings changes are saved immediately to config.json
- [ ] Reopening settings dashboard shows previously saved values
- [ ] DPI, scroll speed, sensitivity values persist across app restarts
- [ ] Config file is written atomically (no partial writes on crash)

### AC4: Flow/Multi-Device Tabs (Foundation)
- [ ] "Devices" tab visible in settings navigation
- [ ] "Flow" tab visible in settings navigation
- [ ] Devices tab shows connected MX Master device info
- [ ] Flow tab shows placeholder for future multi-device configuration
- [ ] Tabs styled consistently with existing Logi Options+ inspired design

### AC5: GitHub Security Configuration
- [ ] SECURITY.md file created with responsible disclosure policy
- [ ] Private vulnerability reporting enabled
- [ ] Dependabot alerts enabled for Rust crates and Python deps
- [ ] CodeQL GitHub Action configured for automated scanning

## Tasks / Subtasks

### Task 1: Debug and Fix Haptic Hover Regression (AC: #1)
- [ ] 1.1 Add debug logging to `_trigger_haptic()` in `juhradial-overlay.py:335`
- [ ] 1.2 Verify `daemon_iface.isValid()` returns True during hover
- [ ] 1.3 Check D-Bus connection state when menu is displayed
- [ ] 1.4 Test haptic trigger path: overlay -> D-Bus -> daemon -> HID++
- [ ] 1.5 Fix the root cause (likely D-Bus interface validity or signal timing)
- [ ] 1.6 Verify haptics work in both hold mode and toggle mode

### Task 2: Fix Settings Scroll/Slider Event Propagation (AC: #2)
- [ ] 2.1 Identify all `Gtk.Scale` widgets inside `Gtk.ScrolledWindow` containers
- [ ] 2.2 Add `Gtk.EventControllerScroll` to ScrolledWindow with CAPTURE phase
- [ ] 2.3 Implement scroll event handler that stops propagation to sliders
- [ ] 2.4 Ensure sliders only respond to:
  - Direct click-drag
  - Arrow keys when focused
  - NOT mouse wheel scroll
- [ ] 2.5 Test all settings pages: ScrollPage, HapticsPage, SettingsPage

### Task 3: Fix Settings Persistence (AC: #3)
- [ ] 3.1 Audit all `config.set()` calls to ensure `config.save()` follows
- [ ] 3.2 Implement atomic file write for config.json (write to temp, then rename)
- [ ] 3.3 Add config reload verification on settings dashboard open
- [ ] 3.4 Test: Change DPI -> close app -> reopen -> verify DPI persisted
- [ ] 3.5 Test: Change scroll speed -> close settings -> reopen settings -> verify value

### Task 4: Implement Flow/Multi-Device Tabs Foundation (AC: #4)
- [ ] 4.1 Add "Devices" nav item to `TABS` list in settings_dashboard.py
- [ ] 4.2 Add "Flow" nav item to `TABS` list in settings_dashboard.py
- [ ] 4.3 Create `DevicesPage(Gtk.ScrolledWindow)` class with:
  - Device name display (e.g., "MX Master 3S")
  - Connection status (USB Receiver / Bluetooth)
  - Battery level display
  - Firmware version
- [ ] 4.4 Create `FlowPage(Gtk.ScrolledWindow)` class with:
  - "Coming Soon" placeholder card
  - Brief description of Flow functionality
  - Link to Logitech Flow documentation
- [ ] 4.5 Register both pages in `content_stack.add_named()`
- [ ] 4.6 Style tabs consistently with existing design

### Task 5: Configure GitHub Security Features (AC: #5)
- [ ] 5.1 Create `.github/SECURITY.md` with:
  - Supported versions table
  - Reporting vulnerabilities section
  - Responsible disclosure timeline
  - Contact information
- [ ] 5.2 Enable Private Vulnerability Reporting via GitHub UI
- [ ] 5.3 Enable Dependabot alerts via GitHub UI
- [ ] 5.4 Create `.github/workflows/codeql.yml` for code scanning:
  - Trigger on push to master and PRs
  - Scan Python and Rust code
  - Upload results to GitHub Security tab

## Dev Notes

### Haptic System Architecture
```
User hovers slice
    -> juhradial-overlay.py:_poll_cursor_position()
    -> Calculates new_slice from cursor position
    -> If new_slice != highlighted_slice AND new_slice >= 0
    -> Calls _trigger_haptic("slice_change")
    -> D-Bus call to daemon: TriggerHaptic(event)
    -> Daemon sends HID++ command to mouse
```

**Likely root cause:** The `daemon_iface` QDBusInterface may lose validity after menu appears. Check if D-Bus connection is being dropped or if the interface needs re-initialization.

### GTK4 Scroll Event Handling
GTK4 uses event controllers instead of signal handlers. To prevent scroll events from reaching sliders:

```python
# Add to ScrolledWindow initialization
scroll_controller = Gtk.EventControllerScroll.new(
    Gtk.EventControllerScrollFlags.VERTICAL
)
scroll_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
scroll_controller.connect('scroll', self._on_container_scroll)
scrolled_window.add_controller(scroll_controller)

def _on_container_scroll(self, controller, dx, dy):
    # Let the scrolled window handle it, don't propagate to children
    return False  # or handle manually
```

### Config Persistence Pattern
```python
def set(self, section, key, value, subkey=None):
    # ... existing logic ...
    self.save()  # Always save after set

def save(self):
    temp_path = self.config_path + '.tmp'
    with open(temp_path, 'w') as f:
        json.dump(self.data, f, indent=2)
    os.replace(temp_path, self.config_path)  # Atomic rename
```

### Project Structure Notes

**Files to modify:**
- `overlay/juhradial-overlay.py` - Haptic debug + fix
- `overlay/settings_dashboard.py` - Scroll isolation, persistence, new tabs
- `overlay/config.py` (if exists) - Atomic save
- `.github/SECURITY.md` - New file
- `.github/workflows/codeql.yml` - New file

### References

- [Source: overlay/juhradial-overlay.py#L335-L342] - _trigger_haptic method
- [Source: overlay/juhradial-overlay.py#L504-L508] - Slice change haptic trigger
- [Source: overlay/settings_dashboard.py#L2706] - ScrollPage class
- [Source: overlay/settings_dashboard.py#L2817-L2821] - Threshold slider
- [Source: overlay/settings_dashboard.py#L189] - config.save() call
- [GitHub Security Best Practices](https://docs.github.com/en/code-security)

## Dev Agent Record

### Context Reference
Party Mode discussion with full BMAD team on 2025-12-25. User reported 6 GitHub stars, $10 donation, and specific bugs.

### Agent Model Used
Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List
- Story drafted by Bob (Scrum Master) after Party Mode session
- Priority order: Bugs first (trust), then features (value), security last (release polish)

### File List
<!-- Will be populated during implementation -->

