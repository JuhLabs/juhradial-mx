//! Export and import of the user's configuration as one zip archive.
//!
//! `juhradiald --export FILE` collects `config.json`, `profiles.json` and the
//! files under `macros/`, `icons/` and `themes/` in the config directory into
//! FILE next to a `manifest.json`. `juhradiald --import FILE` checks that FILE
//! is such an archive, stages every entry in memory, keeps a `.bak` copy of the
//! two JSON files it replaces and writes everything atomically, so a damaged or
//! tampered archive changes nothing. Flow pairing keys (`flow_keys/`), UI state
//! and scratch files (`.tmp`, `.bak`, `.bad`) never leave the machine. The
//! Settings app's Backup card runs these two commands.

use std::fmt;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipArchive, ZipWriter};

/// Name of the archive's manifest entry.
pub const MANIFEST: &str = "manifest.json";

/// Archive format this build writes and the newest it reads.
pub const FORMAT: u32 = 1;

const APP: &str = "juhradial-mx";

/// Top-level files that are exported and imported.
/// ui_state.json holds the Settings look (theme, icon style), so a restore
/// comes back in the same colours.
const FILES: [&str; 3] = ["config.json", "profiles.json", "ui_state.json"];

/// Directories whose regular files are exported and imported, one level deep.
const DIRS: [&str; 3] = ["macros", "icons", "themes"];

/// Largest single entry accepted on import (icons are a few hundred KB).
const MAX_ENTRY_BYTES: u64 = 32 * 1024 * 1024;

/// `manifest.json` inside the archive.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    pub app: String,
    pub format: u32,
    pub version: String,
    pub created: String,
    pub files: Vec<String>,
}

/// What an import wrote.
#[derive(Debug)]
pub struct ImportReport {
    /// App version recorded in the archive's manifest.
    pub version: String,
    /// Archive entries written, in archive order.
    pub files: Vec<String>,
    /// `.bak` file names created next to the files they preserve.
    pub backed_up: Vec<String>,
}

#[derive(Debug)]
pub enum BackupError {
    Io(io::Error),
    Zip(zip::result::ZipError),
    /// The file is not a JuhRadial backup (no or foreign manifest, no files).
    NotABackup(String),
    /// The archive was written by a newer format than this build reads.
    Unsupported(u32),
    /// An entry name outside the accepted set (also catches zip-slip paths).
    InvalidEntry(String),
    /// An entry with the right name but unusable content.
    InvalidFile(String, String),
}

impl fmt::Display for BackupError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            BackupError::Io(e) => write!(f, "I/O error: {}", e),
            BackupError::Zip(e) => write!(f, "zip error: {}", e),
            BackupError::NotABackup(why) => write!(f, "not a JuhRadial backup: {}", why),
            BackupError::Unsupported(v) => write!(
                f,
                "backup format {} is newer than this build understands ({})",
                v, FORMAT
            ),
            BackupError::InvalidEntry(name) => {
                write!(f, "refusing archive entry \"{}\"", name)
            }
            BackupError::InvalidFile(name, why) => write!(f, "{}: {}", name, why),
        }
    }
}

impl std::error::Error for BackupError {}

impl From<io::Error> for BackupError {
    fn from(e: io::Error) -> Self {
        BackupError::Io(e)
    }
}

impl From<zip::result::ZipError> for BackupError {
    fn from(e: zip::result::ZipError) -> Self {
        BackupError::Zip(e)
    }
}

// ============================================================================
// Export
// ============================================================================

/// Write every exportable file under `config_dir` to the zip at `dest` and
/// return the archive-relative names written (manifest excluded).
pub fn export(config_dir: &Path, dest: &Path) -> Result<Vec<String>, BackupError> {
    let names = exportable_files(config_dir);
    let manifest = Manifest {
        app: APP.to_string(),
        format: FORMAT,
        version: env!("CARGO_PKG_VERSION").to_string(),
        created: utc_now(),
        files: names.clone(),
    };
    let manifest_json = serde_json::to_string_pretty(&manifest).map_err(io::Error::other)?;

    let mut zip = ZipWriter::new(fs::File::create(dest)?);
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    zip.start_file(MANIFEST, options)?;
    zip.write_all(manifest_json.as_bytes())?;
    for name in &names {
        zip.start_file(name.as_str(), options)?;
        let mut src = fs::File::open(config_dir.join(name))?;
        io::copy(&mut src, &mut zip)?;
    }
    zip.finish()?;
    Ok(names)
}

/// Archive-relative names of everything `export` ships, in a stable order.
fn exportable_files(config_dir: &Path) -> Vec<String> {
    let mut names: Vec<String> = FILES
        .iter()
        .filter(|f| config_dir.join(f).is_file())
        .map(|f| f.to_string())
        .collect();
    for dir in DIRS {
        let Ok(entries) = fs::read_dir(config_dir.join(dir)) else {
            continue;
        };
        let mut found: Vec<String> = entries
            .flatten()
            .filter(|e| e.path().is_file())
            .filter_map(|e| e.file_name().into_string().ok())
            .filter(|n| !is_scratch(n))
            .map(|n| format!("{}/{}", dir, n))
            .collect();
        found.sort();
        names.extend(found);
    }
    names
}

/// Editor and writer leftovers that must not travel.
fn is_scratch(name: &str) -> bool {
    name.starts_with('.')
        || name.ends_with(".tmp")
        || name.ends_with(".bak")
        || name.ends_with(".bad")
}

// ============================================================================
// Import
// ============================================================================

/// Restore the archive at `src` into `config_dir`.
///
/// Every entry is validated and read before anything is written: the archive
/// must carry a JuhRadial manifest of a known format, entry names must be one
/// of the accepted files or `<dir>/<file>` for the known directories (which
/// rules out absolute and `..` paths), and every `.json` entry must parse as a
/// JSON object. `config.json` and `profiles.json` are copied to `.bak` before
/// being replaced; files on disk that the archive does not mention are left
/// alone.
pub fn import(config_dir: &Path, src: &Path) -> Result<ImportReport, BackupError> {
    let mut archive = ZipArchive::new(fs::File::open(src)?)?;
    let manifest = read_manifest(&mut archive)?;
    if manifest.app != APP {
        return Err(BackupError::NotABackup(format!(
            "made by \"{}\"",
            manifest.app
        )));
    }
    if manifest.format > FORMAT {
        return Err(BackupError::Unsupported(manifest.format));
    }

    let mut staged: Vec<(PathBuf, String, Vec<u8>)> = Vec::new();
    for index in 0..archive.len() {
        let entry = archive.by_index(index)?;
        if entry.is_dir() {
            continue;
        }
        let name = entry.name().to_string();
        if name == MANIFEST {
            continue;
        }
        let relative = accepted_path(&name)?;
        if entry.size() > MAX_ENTRY_BYTES {
            return Err(BackupError::InvalidFile(name, "entry too large".into()));
        }
        let mut data = Vec::with_capacity(entry.size() as usize);
        entry.take(MAX_ENTRY_BYTES + 1).read_to_end(&mut data)?;
        if data.len() as u64 > MAX_ENTRY_BYTES {
            return Err(BackupError::InvalidFile(name, "entry too large".into()));
        }
        if name.ends_with(".json") {
            check_json_object(&name, &data)?;
        }
        staged.push((relative, name, data));
    }
    if staged.is_empty() {
        return Err(BackupError::NotABackup(
            "the archive holds no configuration files".into(),
        ));
    }

    fs::create_dir_all(config_dir)?;
    let mut backed_up = Vec::new();
    for file in FILES {
        let current = config_dir.join(file);
        if current.is_file() && staged.iter().any(|(_, name, _)| name == file) {
            let bak = format!("{}.bak", file);
            fs::copy(&current, config_dir.join(&bak))?;
            backed_up.push(bak);
        }
    }

    let mut files = Vec::with_capacity(staged.len());
    for (relative, name, data) in &staged {
        let dest = config_dir.join(relative);
        if let Some(parent) = dest.parent() {
            fs::create_dir_all(parent)?;
        }
        write_atomic(&dest, data)?;
        files.push(name.clone());
    }

    Ok(ImportReport {
        version: manifest.version,
        files,
        backed_up,
    })
}

fn read_manifest<R: Read + io::Seek>(archive: &mut ZipArchive<R>) -> Result<Manifest, BackupError> {
    let mut entry = archive
        .by_name(MANIFEST)
        .map_err(|_| BackupError::NotABackup(format!("no {} in the archive", MANIFEST)))?;
    let mut text = String::new();
    entry.read_to_string(&mut text)?;
    serde_json::from_str(&text)
        .map_err(|e| BackupError::NotABackup(format!("unreadable {}: {}", MANIFEST, e)))
}

/// The config-relative path an entry may be written to, or why it may not.
fn accepted_path(name: &str) -> Result<PathBuf, BackupError> {
    let refuse = || BackupError::InvalidEntry(name.to_string());
    if name.is_empty() || name.contains('\\') || name.contains('\0') {
        return Err(refuse());
    }
    let parts: Vec<&str> = Path::new(name)
        .components()
        .map(|c| match c {
            Component::Normal(s) => s.to_str(),
            _ => None,
        })
        .collect::<Option<Vec<_>>>()
        .ok_or_else(refuse)?;
    let accepted = match parts.as_slice() {
        [file] => FILES.contains(file),
        [dir, file] => {
            DIRS.contains(dir)
                && safe_file_name(file)
                && (*dir == "icons" || file.ends_with(".json"))
        }
        _ => false,
    };
    if !accepted {
        return Err(refuse());
    }
    Ok(parts.iter().collect())
}

fn safe_file_name(name: &str) -> bool {
    !is_scratch(name)
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | ' '))
}

fn check_json_object(name: &str, data: &[u8]) -> Result<(), BackupError> {
    match serde_json::from_slice::<serde_json::Value>(data) {
        Ok(value) if value.is_object() => Ok(()),
        Ok(_) => Err(BackupError::InvalidFile(
            name.to_string(),
            "not a JSON object".into(),
        )),
        Err(e) => Err(BackupError::InvalidFile(name.to_string(), e.to_string())),
    }
}

/// Write `data` to a sibling `.tmp` and rename it over `dest`.
fn write_atomic(dest: &Path, data: &[u8]) -> io::Result<()> {
    let file_name = dest
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| io::Error::other("destination has no file name"))?;
    let tmp = dest.with_file_name(format!("{}.tmp", file_name));
    {
        let mut file = fs::File::create(&tmp)?;
        file.write_all(data)?;
        file.sync_all()?;
    }
    fs::rename(&tmp, dest)
}

// ============================================================================
// Timestamps (RFC 3339 UTC without a date crate)
// ============================================================================

fn utc_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format_utc(secs)
}

/// `YYYY-MM-DDTHH:MM:SSZ` for a Unix timestamp (civil-from-days, Gregorian).
fn format_utc(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let (hour, min, sec) = (rem / 3_600, (rem % 3_600) / 60, rem % 60);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        year, month, day, hour, min, sec
    )
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn write(dir: &Path, rel: &str, body: &str) {
        let path = dir.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, body).unwrap();
    }

    fn populated_config_dir() -> tempfile::TempDir {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path();
        write(dir, "config.json", r#"{"theme": "vaporwave", "haptics": {"intensity": 40}}"#);
        write(dir, "profiles.json", r#"{"version": 1, "profiles": []}"#);
        write(dir, "macros/abc-123.json", r#"{"id": "abc-123", "name": "m"}"#);
        write(dir, "icons/firefox.png", "PNGDATA");
        write(dir, "themes/mine.json", r#"{"name": "mine"}"#);
        write(dir, "flow_keys/private.key", "SECRET");
        write(dir, "ui_state.json", r#"{"settings_theme": 3}"#);
        write(dir, "config.json.bak", "{}");
        write(dir, "macros/.partial.json.tmp", "{}");
        tmp
    }

    fn zip_with(entries: &[(&str, &[u8])]) -> tempfile::NamedTempFile {
        let file = tempfile::NamedTempFile::new().unwrap();
        let mut zip = ZipWriter::new(file.reopen().unwrap());
        let options = SimpleFileOptions::default();
        for (name, body) in entries {
            zip.start_file(*name, options).unwrap();
            zip.write_all(body).unwrap();
        }
        zip.finish().unwrap();
        file
    }

    fn manifest_json(app: &str, format: u32) -> Vec<u8> {
        format!(
            r#"{{"app": "{}", "format": {}, "version": "0.0.0", "created": "2026-01-01T00:00:00Z", "files": []}}"#,
            app, format
        )
        .into_bytes()
    }

    #[test]
    fn export_ships_config_profiles_and_dirs_only() {
        let src = populated_config_dir();
        let out = tempfile::NamedTempFile::new().unwrap();
        let names = export(src.path(), out.path()).unwrap();
        assert_eq!(
            names,
            vec![
                "config.json",
                "profiles.json",
                "ui_state.json",
                "macros/abc-123.json",
                "icons/firefox.png",
                "themes/mine.json"
            ]
        );
        let mut archive = ZipArchive::new(fs::File::open(out.path()).unwrap()).unwrap();
        let entries: Vec<String> = (0..archive.len())
            .map(|i| archive.by_index(i).unwrap().name().to_string())
            .collect();
        assert!(entries.contains(&MANIFEST.to_string()));
        assert!(!entries.iter().any(|n| n.contains("flow_keys")));
        assert!(entries.iter().any(|n| n == "ui_state.json"), "the look travels with a backup");
        assert!(!entries.iter().any(|n| n.ends_with(".bak") || n.ends_with(".tmp")));
        let manifest = read_manifest(&mut archive).unwrap();
        assert_eq!(manifest.app, APP);
        assert_eq!(manifest.format, FORMAT);
        assert_eq!(manifest.version, env!("CARGO_PKG_VERSION"));
        assert_eq!(manifest.files, names);
        assert!(manifest.created.ends_with('Z'));
    }

    #[test]
    fn export_from_an_empty_config_dir_writes_a_manifest_only() {
        let tmp = tempfile::tempdir().unwrap();
        let out = tempfile::NamedTempFile::new().unwrap();
        assert!(export(tmp.path(), out.path()).unwrap().is_empty());
        let mut archive = ZipArchive::new(fs::File::open(out.path()).unwrap()).unwrap();
        assert_eq!(archive.len(), 1);
        assert!(read_manifest(&mut archive).unwrap().files.is_empty());
    }

    #[test]
    fn round_trip_restores_every_file_and_keeps_bak_copies() {
        let src = populated_config_dir();
        let out = tempfile::NamedTempFile::new().unwrap();
        export(src.path(), out.path()).unwrap();

        let dst = tempfile::tempdir().unwrap();
        write(dst.path(), "config.json", r#"{"theme": "old"}"#);
        write(dst.path(), "profiles.json", r#"{"version": 1, "profiles": [1]}"#);
        write(dst.path(), "macros/keep-me.json", r#"{"id": "keep-me"}"#);

        let report = import(dst.path(), out.path()).unwrap();
        assert_eq!(report.files.len(), 6);
        assert_eq!(report.backed_up, vec!["config.json.bak", "profiles.json.bak"]);
        assert_eq!(report.version, env!("CARGO_PKG_VERSION"));

        let cfg = fs::read_to_string(dst.path().join("config.json")).unwrap();
        assert!(cfg.contains("vaporwave"));
        assert_eq!(
            fs::read_to_string(dst.path().join("config.json.bak")).unwrap(),
            r#"{"theme": "old"}"#
        );
        assert!(fs::read_to_string(dst.path().join("profiles.json.bak"))
            .unwrap()
            .contains("[1]"));
        assert_eq!(
            fs::read_to_string(dst.path().join("icons/firefox.png")).unwrap(),
            "PNGDATA"
        );
        assert!(dst.path().join("macros/abc-123.json").is_file());
        assert!(dst.path().join("macros/keep-me.json").is_file(), "untouched extras stay");
        assert!(dst.path().join("themes/mine.json").is_file());
        assert!(!dst.path().join("flow_keys").exists());
        assert!(!dst.path().join("config.json.tmp").exists(), "temp file renamed away");
    }

    #[test]
    fn import_into_a_fresh_dir_makes_no_bak_files() {
        let src = populated_config_dir();
        let out = tempfile::NamedTempFile::new().unwrap();
        export(src.path(), out.path()).unwrap();
        let dst = tempfile::tempdir().unwrap();
        let target = dst.path().join("juhradial");
        let report = import(&target, out.path()).unwrap();
        assert!(report.backed_up.is_empty());
        assert!(target.join("config.json").is_file());
    }

    #[test]
    fn import_refuses_archives_without_a_manifest() {
        let archive = zip_with(&[("config.json", b"{}")]);
        let dst = tempfile::tempdir().unwrap();
        let err = import(dst.path(), archive.path()).unwrap_err();
        assert!(matches!(err, BackupError::NotABackup(_)), "{}", err);
        assert!(!dst.path().join("config.json").exists());
    }

    #[test]
    fn import_refuses_foreign_and_newer_manifests() {
        let dst = tempfile::tempdir().unwrap();
        let foreign = zip_with(&[
            (MANIFEST, &manifest_json("other-app", FORMAT)),
            ("config.json", b"{}"),
        ]);
        assert!(matches!(
            import(dst.path(), foreign.path()).unwrap_err(),
            BackupError::NotABackup(_)
        ));
        let newer = zip_with(&[
            (MANIFEST, &manifest_json(APP, FORMAT + 1)),
            ("config.json", b"{}"),
        ]);
        assert!(matches!(
            import(dst.path(), newer.path()).unwrap_err(),
            BackupError::Unsupported(v) if v == FORMAT + 1
        ));
        let empty = zip_with(&[(MANIFEST, &manifest_json(APP, FORMAT))]);
        assert!(matches!(
            import(dst.path(), empty.path()).unwrap_err(),
            BackupError::NotABackup(_)
        ));
    }

    #[test]
    fn import_refuses_paths_outside_the_config_set() {
        for bad in [
            "../config.json",
            "/etc/passwd",
            "macros/../../evil.json",
            "flow_keys/private.key",
            "macros/nested/deep.json",
            "macros/notjson.txt",
            "icons/.hidden.png",
            "icons/evil.png.tmp",
            "macros\\win.json",
            "themes/a b\u{0}.json",
            "backup.json",
        ] {
            assert!(
                matches!(accepted_path(bad), Err(BackupError::InvalidEntry(_))),
                "{} must be refused",
                bad
            );
        }
        assert_eq!(accepted_path("config.json").unwrap(), PathBuf::from("config.json"));
        assert_eq!(
            accepted_path("macros/ab-1_2.json").unwrap(),
            Path::new("macros").join("ab-1_2.json")
        );
        assert_eq!(
            accepted_path("icons/org.mozilla.firefox.png").unwrap(),
            Path::new("icons").join("org.mozilla.firefox.png")
        );
    }

    #[test]
    fn import_writes_nothing_when_one_entry_is_bad() {
        let dst = tempfile::tempdir().unwrap();
        write(dst.path(), "config.json", r#"{"theme": "old"}"#);
        let archive = zip_with(&[
            (MANIFEST, &manifest_json(APP, FORMAT)),
            ("config.json", br#"{"theme": "new"}"#),
            ("profiles.json", b"not json at all"),
        ]);
        let err = import(dst.path(), archive.path()).unwrap_err();
        assert!(matches!(err, BackupError::InvalidFile(ref n, _) if n == "profiles.json"), "{}", err);
        assert_eq!(
            fs::read_to_string(dst.path().join("config.json")).unwrap(),
            r#"{"theme": "old"}"#
        );
        assert!(!dst.path().join("config.json.bak").exists());

        let traversal = zip_with(&[
            (MANIFEST, &manifest_json(APP, FORMAT)),
            ("config.json", br#"{"theme": "new"}"#),
            ("../escape.json", b"{}"),
        ]);
        assert!(matches!(
            import(dst.path(), traversal.path()).unwrap_err(),
            BackupError::InvalidEntry(_)
        ));
        assert_eq!(
            fs::read_to_string(dst.path().join("config.json")).unwrap(),
            r#"{"theme": "old"}"#
        );
        assert!(!dst.path().parent().unwrap().join("escape.json").exists());

        let array = zip_with(&[
            (MANIFEST, &manifest_json(APP, FORMAT)),
            ("config.json", b"[1, 2]"),
        ]);
        assert!(matches!(
            import(dst.path(), array.path()).unwrap_err(),
            BackupError::InvalidFile(_, _)
        ));
    }

    #[test]
    fn import_skips_directory_entries() {
        let dst = tempfile::tempdir().unwrap();
        let file = tempfile::NamedTempFile::new().unwrap();
        let mut zip = ZipWriter::new(file.reopen().unwrap());
        let options = SimpleFileOptions::default();
        zip.start_file(MANIFEST, options).unwrap();
        zip.write_all(&manifest_json(APP, FORMAT)).unwrap();
        zip.add_directory("macros/", options).unwrap();
        zip.start_file("macros/m.json", options).unwrap();
        zip.write_all(br#"{"id": "m"}"#).unwrap();
        zip.finish().unwrap();
        let report = import(dst.path(), file.path()).unwrap();
        assert_eq!(report.files, vec!["macros/m.json"]);
    }

    #[test]
    fn utc_timestamps_are_rfc3339() {
        assert_eq!(format_utc(0), "1970-01-01T00:00:00Z");
        assert_eq!(format_utc(1_709_164_800), "2024-02-29T00:00:00Z");
        assert_eq!(format_utc(1_790_176_800), "2026-09-23T15:20:00Z");
        assert_eq!(format_utc(951_782_400), "2000-02-29T00:00:00Z");
    }
}
