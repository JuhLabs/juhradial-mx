# Story 3.1: Implement Profile Configuration Schema

Status: done

## Story

As a developer,
I want a well-defined JSON schema for profile configuration,
So that profiles are validated and consistent.

## Acceptance Criteria

### AC1: Configuration File Location
**Given** I am defining the profile system
**When** I create the configuration schema
**Then** the profile configuration file is located at `~/.config/juhradial/profiles.json`
**And** the schema defines: default profile, application-specific profiles, 8 slice actions per profile

### AC2: Default Profile Creation on First Start
**Given** the profiles.json file does not exist
**When** the daemon starts
**Then** it creates profiles.json with a default profile containing common actions (copy, paste, undo, etc.)

## Tasks / Subtasks

- [x] Task 1: Define JSON Schema for profiles.json (AC: 1)
  - [x] 1.1 Create ProfilesConfig struct wrapping Vec<Profile>
  - [x] 1.2 Ensure Profile struct matches schema (name, window_class, slices[8], center, icon, description)
  - [x] 1.3 Add version field for future migrations
  - [x] 1.4 Add serde annotations for proper JSON serialization

- [x] Task 2: Implement profiles.json file path resolution (AC: 1)
  - [x] 2.1 Create function to get config directory (~/.config/juhradial/)
  - [x] 2.2 Create function to get profiles.json path
  - [x] 2.3 Handle XDG_CONFIG_HOME environment variable
  - [x] 2.4 Create directory if it doesn't exist

- [x] Task 3: Implement ProfileManager::load() (AC: 1, 2)
  - [x] 3.1 Read profiles.json file if exists
  - [x] 3.2 Deserialize JSON to ProfilesConfig
  - [x] 3.3 Validate each profile has 8 slices
  - [x] 3.4 Build window_class to profile mapping
  - [x] 3.5 Return error if JSON is malformed

- [x] Task 4: Implement default profile creation (AC: 2)
  - [x] 4.1 Create create_default_profiles_config() function
  - [x] 4.2 Use get_default_actions() from actions.rs for slices
  - [x] 4.3 Write JSON file to ~/.config/juhradial/profiles.json
  - [x] 4.4 Log profile creation with tracing

- [x] Task 5: Integrate with daemon startup (AC: 2)
  - [x] 5.1 Check if profiles.json exists on startup
  - [x] 5.2 If not exists, create default profiles.json
  - [x] 5.3 Load profiles into ProfileManager
  - [x] 5.4 Log loaded profile count

- [x] Task 6: Add unit tests
  - [x] 6.1 Test ProfilesConfig serialization/deserialization
  - [x] 6.2 Test default profile creation
  - [x] 6.3 Test load from valid JSON file
  - [x] 6.4 Test load failure on malformed JSON
  - [x] 6.5 Test config directory creation

## Dev Notes

### Implementation Approach

The profile schema builds on existing `Profile` and `Action` structs in `daemon/src/profiles.rs` and `daemon/src/actions.rs`. Key implementation:

1. **ProfilesConfig wrapper** - Top-level struct containing version and profiles array
2. **Path resolution** - Use `dirs` crate or manual XDG handling
3. **First-run detection** - Check file existence before attempting load
4. **Default creation** - Use existing `get_default_actions()` function

### Architecture Compliance

From `docs/architecture.md`:

**ADR-001: Configuration Storage**
- Pure JSON files with schema validation
- Configuration at: `~/.config/juhradial/`
- Hot-reload via inotify file watching (future story)

**Naming Conventions:**
- JSON config keys: `snake_case` (e.g., `"window_class"`, `"default_profile"`)
- Rust types: `PascalCase` (e.g., `ProfilesConfig`, `ProfileManager`)

### JSON Schema Design

```json
{
  "version": 1,
  "profiles": [
    {
      "name": "default",
      "window_class": null,
      "icon": "🎯",
      "description": "Default profile with common shortcuts",
      "slices": [
        { "type": "shortcut", "value": "ctrl+c", "label": "Copy", "icon": "📋" },
        { "type": "shortcut", "value": "ctrl+v", "label": "Paste", "icon": "📄" },
        ...
      ],
      "center": null
    },
    {
      "name": "firefox",
      "window_class": "firefox",
      "icon": "🦊",
      "description": "Firefox browser profile",
      "slices": [...],
      "center": null
    }
  ]
}
```

### Existing Code Integration

**Files to modify:**
- `daemon/src/profiles.rs` - Add ProfilesConfig, implement load/save
- `daemon/src/main.rs` - Integrate profile loading on startup

**Files for reference (do not modify):**
- `daemon/src/actions.rs:258-309` - `get_default_actions()` provides 8 default slice actions
- `daemon/src/actions.rs:57-70` - Action struct with action_type, label, icon

### Project Structure Notes

- Alignment with architecture: JSON config at `~/.config/juhradial/profiles.json`
- Uses existing serde derives on Profile and Action structs
- No external schema validator needed - Rust serde provides validation

### Testing Standards

From architecture:
- Unit test coverage: 80%+ for daemon logic
- Use `#[cfg(test)]` module pattern
- Test both success and failure paths

### References

- [Source: docs/epics.md#Story-3.1] - Acceptance criteria
- [Source: docs/architecture.md#ADR-001] - Configuration storage decision
- [Source: docs/architecture.md#Implementation-Patterns] - Naming conventions
- [Source: daemon/src/actions.rs:258-309] - Default actions implementation
- [Source: daemon/src/profiles.rs:8-44] - Existing Profile struct

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

### Completion Notes List

- Implemented ProfilesConfig struct with version field (v1) for schema versioning
- Created get_config_dir() and get_profiles_path() with XDG_CONFIG_HOME support
- ProfileManager::load_or_create() handles first-run scenario automatically
- Default profile uses get_default_actions() for 8 common shortcuts (Copy, Paste, Undo, Redo, Select All, Cut, Save, Close)
- Added 15 unit tests covering serialization, loading, validation, and error paths
- Integrated profile loading into daemon main.rs with graceful fallback on errors
- Added tempfile dev dependency for test isolation

**Code Review Fixes Applied:**
- Fixed unused profile_manager variable in main.rs (prefixed with `_`, added comment about Story 3.2/3.3 usage)
- Added version migration warning when loaded file has different schema version
- Changed `load_from_path(&PathBuf)` to `load_from_path(&Path)` per Rust conventions
- Removed unused `std::io::Read` import in tests
- Fixed `test_ensure_config_dir` to properly verify directory creation
- Marked `test_xdg_config_home` as `#[ignore]` to prevent test pollution (run with `--ignored`)

### File List

- `daemon/src/profiles.rs` - MODIFIED: Complete rewrite with ProfilesConfig, path resolution, load/save logic, 15 unit tests
- `daemon/src/main.rs` - MODIFIED: Added ProfileManager import and load_or_create() call on startup (lines 80-102)
- `daemon/Cargo.toml` - MODIFIED: Added tempfile = "3" dev dependency
