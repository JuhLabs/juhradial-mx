//! Macro file I/O with atomic writes
//!
//! Macros are stored as individual JSON files in `~/.config/juhradial/macros/`.
//! Each file is named `{id}.json`. All writes use atomic pattern (write .tmp,
//! then rename) to prevent corruption.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use super::types::MacroConfig;

// ============================================================================
// Constants
// ============================================================================

/// Subdirectory name for macro storage
const MACROS_DIR: &str = "macros";

/// File extension for macro files
const MACRO_EXT: &str = "json";

// ============================================================================
// Directory Management
// ============================================================================

/// Get the macros directory path: ~/.config/juhradial/macros/
pub fn macros_dir() -> Option<PathBuf> {
    dirs::config_dir().map(|p| p.join("juhradial").join(MACROS_DIR))
}

/// Create the macros directory if it does not exist
pub fn ensure_macros_dir() -> Result<PathBuf, StorageError> {
    let dir = macros_dir().ok_or(StorageError::NoConfigDir)?;

    if !dir.exists() {
        fs::create_dir_all(&dir).map_err(StorageError::IoError)?;
        tracing::info!(path = %dir.display(), "Created macros directory");
    }

    Ok(dir)
}

// ============================================================================
// ID Validation (prevent path traversal)
// ============================================================================

/// Validate that a macro ID is safe for use in file paths.
/// Only allows alphanumeric characters, hyphens, and underscores.
fn validate_id(id: &str) -> Result<(), StorageError> {
    if id.is_empty()
        || !id
            .chars()
            .all(|c| c.is_alphanumeric() || c == '-' || c == '_')
    {
        return Err(StorageError::InvalidId(id.to_string()));
    }
    Ok(())
}

// ============================================================================
// Load
// ============================================================================

/// Load all macros from the macros directory
///
/// Returns a HashMap keyed by macro id. Files that fail to parse are
/// logged as warnings and skipped.
pub fn load_all_macros() -> Result<HashMap<String, MacroConfig>, StorageError> {
    let dir = ensure_macros_dir()?;
    load_all_macros_from(&dir)
}

/// Load all macros from a specific directory (for testing)
pub fn load_all_macros_from(dir: &Path) -> Result<HashMap<String, MacroConfig>, StorageError> {
    let mut macros = HashMap::new();

    if !dir.exists() {
        return Ok(macros);
    }

    let entries = fs::read_dir(dir).map_err(StorageError::IoError)?;

    for entry in entries.flatten() {
        let path = entry.path();

        // Only process .json files
        if path.extension().and_then(|e| e.to_str()) != Some(MACRO_EXT) {
            continue;
        }

        match load_macro_file(&path) {
            Ok(config) => {
                tracing::debug!(id = %config.id, name = %config.name, "Loaded macro");
                macros.insert(config.id.clone(), config);
            }
            Err(e) => {
                tracing::warn!(path = %path.display(), error = %e, "Skipping invalid macro file");
            }
        }
    }

    tracing::info!(count = macros.len(), "Macros loaded");
    Ok(macros)
}

/// Load a single macro by id
pub fn load_macro(id: &str) -> Result<MacroConfig, StorageError> {
    validate_id(id)?;
    let dir = ensure_macros_dir()?;
    let path = dir.join(format!("{}.{}", id, MACRO_EXT));
    load_macro_file(&path)
}

/// Load a macro from a specific file path
fn load_macro_file(path: &Path) -> Result<MacroConfig, StorageError> {
    let contents = fs::read_to_string(path).map_err(StorageError::IoError)?;
    let config: MacroConfig = serde_json::from_str(&contents).map_err(StorageError::ParseError)?;
    Ok(config)
}

// ============================================================================
// Save (atomic write)
// ============================================================================

/// Save a macro to disk using atomic write pattern
///
/// Writes to a .tmp file first, then renames to the final path.
/// This prevents corruption if the process is interrupted.
pub fn save_macro(config: &MacroConfig) -> Result<(), StorageError> {
    let dir = ensure_macros_dir()?;
    save_macro_to(&dir, config)
}

/// Save a macro to a specific directory (for testing)
pub fn save_macro_to(dir: &Path, config: &MacroConfig) -> Result<(), StorageError> {
    validate_id(&config.id)?;
    let final_path = dir.join(format!("{}.{}", config.id, MACRO_EXT));
    let tmp_path = dir.join(format!("{}.{}.tmp", config.id, MACRO_EXT));

    // Serialize to pretty JSON
    let contents = serde_json::to_string_pretty(config).map_err(StorageError::ParseError)?;

    // Write to temp file
    fs::write(&tmp_path, &contents).map_err(StorageError::IoError)?;

    // Atomic rename
    fs::rename(&tmp_path, &final_path).map_err(StorageError::IoError)?;

    tracing::info!(id = %config.id, path = %final_path.display(), "Macro saved");
    Ok(())
}

// ============================================================================
// Delete
// ============================================================================

/// Delete a macro by id
pub fn delete_macro(id: &str) -> Result<(), StorageError> {
    let dir = ensure_macros_dir()?;
    delete_macro_from(&dir, id)
}

/// Delete a macro from a specific directory (for testing)
pub fn delete_macro_from(dir: &Path, id: &str) -> Result<(), StorageError> {
    validate_id(id)?;
    let path = dir.join(format!("{}.{}", id, MACRO_EXT));

    if !path.exists() {
        return Err(StorageError::NotFound(id.to_string()));
    }

    fs::remove_file(&path).map_err(StorageError::IoError)?;

    tracing::info!(id = %id, "Macro deleted");
    Ok(())
}

// ============================================================================
// Error Type
// ============================================================================

/// Storage error type
#[derive(Debug)]
pub enum StorageError {
    /// Could not determine config directory
    NoConfigDir,
    /// Macro not found
    NotFound(String),
    /// Invalid macro ID (path traversal attempt or illegal characters)
    InvalidId(String),
    /// I/O error
    IoError(std::io::Error),
    /// JSON parse error
    ParseError(serde_json::Error),
}

impl std::fmt::Display for StorageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StorageError::NoConfigDir => write!(f, "Could not determine config directory"),
            StorageError::NotFound(id) => write!(f, "Macro not found: {}", id),
            StorageError::InvalidId(id) => write!(f, "Invalid macro ID: {}", id),
            StorageError::IoError(e) => write!(f, "I/O error: {}", e),
            StorageError::ParseError(e) => write!(f, "Parse error: {}", e),
        }
    }
}

impl std::error::Error for StorageError {}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::macros::types::{MacroAction, RepeatMode};

    fn test_macro() -> MacroConfig {
        MacroConfig {
            id: "test-macro-1".to_string(),
            name: "Test Copy".to_string(),
            description: "Simulates Ctrl+C".to_string(),
            repeat_mode: RepeatMode::Once,
            repeat_count: 1,
            actions: vec![
                MacroAction::KeyDown("ctrl".to_string()),
                MacroAction::KeyDown("c".to_string()),
                MacroAction::Delay(50),
                MacroAction::KeyUp("c".to_string()),
                MacroAction::KeyUp("ctrl".to_string()),
            ],
            sequence_actions: None,
            standard_delay_ms: 50,
            use_standard_delay: true,
            assigned_trigger: None,
        }
    }

    #[test]
    fn test_save_and_load_macro() {
        let dir = tempfile::tempdir().unwrap();
        let config = test_macro();

        // Save
        save_macro_to(dir.path(), &config).unwrap();

        // Verify file exists
        let file_path = dir.path().join("test-macro-1.json");
        assert!(file_path.exists());

        // Load
        let loaded = load_macro_file(&file_path).unwrap();
        assert_eq!(loaded.id, "test-macro-1");
        assert_eq!(loaded.name, "Test Copy");
        assert_eq!(loaded.actions.len(), 5);
    }

    #[test]
    fn test_load_all_macros() {
        let dir = tempfile::tempdir().unwrap();

        // Save two macros
        let m1 = test_macro();
        let mut m2 = test_macro();
        m2.id = "test-macro-2".to_string();
        m2.name = "Test Paste".to_string();

        save_macro_to(dir.path(), &m1).unwrap();
        save_macro_to(dir.path(), &m2).unwrap();

        // Load all
        let macros = load_all_macros_from(dir.path()).unwrap();
        assert_eq!(macros.len(), 2);
        assert!(macros.contains_key("test-macro-1"));
        assert!(macros.contains_key("test-macro-2"));
    }

    #[test]
    fn test_delete_macro() {
        let dir = tempfile::tempdir().unwrap();
        let config = test_macro();

        save_macro_to(dir.path(), &config).unwrap();
        assert!(dir.path().join("test-macro-1.json").exists());

        delete_macro_from(dir.path(), "test-macro-1").unwrap();
        assert!(!dir.path().join("test-macro-1.json").exists());
    }

    #[test]
    fn test_delete_nonexistent_macro() {
        let dir = tempfile::tempdir().unwrap();
        let result = delete_macro_from(dir.path(), "nonexistent");
        assert!(result.is_err());
    }

    #[test]
    fn test_load_all_empty_dir() {
        let dir = tempfile::tempdir().unwrap();
        let macros = load_all_macros_from(dir.path()).unwrap();
        assert!(macros.is_empty());
    }

    #[test]
    fn test_atomic_write_creates_no_tmp() {
        let dir = tempfile::tempdir().unwrap();
        let config = test_macro();

        save_macro_to(dir.path(), &config).unwrap();

        // The .tmp file should not remain after successful rename
        let tmp_path = dir.path().join("test-macro-1.json.tmp");
        assert!(!tmp_path.exists());
    }

    #[test]
    fn test_storage_error_display() {
        let err = StorageError::NotFound("abc".to_string());
        assert!(format!("{}", err).contains("abc"));

        let err = StorageError::NoConfigDir;
        assert!(format!("{}", err).contains("config directory"));
    }
}
