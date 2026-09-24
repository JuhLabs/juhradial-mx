//! Declarative plugins: `~/.config/juhradial/plugins/<name>/plugin.json`.
//!
//! A plugin is a folder with a manifest that declares actions. Each action
//! runs one of three ways, the same ones the radial menu already knows:
//!
//! - `exec`: a shell command line (run with `sh -c`, like an exec slice);
//! - `dbus`: a D-Bus method call (`service`, `path`, `interface`, `method`,
//!   optional `args`), sent with dbus-send like a D-Bus slice;
//! - `script`: a program inside the plugin folder (relative path, no `..`),
//!   started with optional `args` and the plugin folder as working directory.
//!
//! Manifests are read on every `ListPlugins` / `RunPluginAction` call, so a
//! plugin dropped into the folder shows up in Settings without a restart. An
//! action is addressed as `<folder>/<action id>`. Plugins run as the user,
//! exactly like an exec slice in config.json; nothing here elevates anything.

use std::collections::HashSet;
use std::fs;
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::actions::{Action, ActionError, ActionExecutor, ActionType, DBusCall};

/// Folder under the config dir that holds one sub-folder per plugin.
pub const PLUGINS_DIR: &str = "plugins";
/// Manifest file name inside a plugin folder.
pub const MANIFEST: &str = "plugin.json";
/// Newest manifest schema this build reads.
pub const SCHEMA: u32 = 1;

/// Upper bounds that keep a broken or hostile folder cheap to scan.
const MAX_PLUGINS: usize = 64;
const MAX_ACTIONS: usize = 64;
const MAX_MANIFEST_BYTES: u64 = 256 * 1024;

/// `plugin.json` as written by a plugin author.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ManifestFile {
    #[serde(default = "default_schema")]
    schema: u32,
    name: String,
    #[serde(default)]
    version: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    author: String,
    actions: Vec<ActionFile>,
}

fn default_schema() -> u32 {
    SCHEMA
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ActionFile {
    id: String,
    label: String,
    #[serde(default)]
    icon: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    exec: Option<String>,
    #[serde(default)]
    dbus: Option<DBusCall>,
    #[serde(default)]
    script: Option<String>,
    #[serde(default)]
    args: Vec<String>,
}

/// How an action runs.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Run {
    Exec { command: String },
    Dbus { call: DBusCall },
    Script { program: PathBuf, args: Vec<String> },
}

/// One validated action, as listed for Settings.
#[derive(Debug, Clone, Serialize)]
pub struct PluginAction {
    /// `<folder>/<id>`, what a slice stores as its command.
    #[serde(rename = "ref")]
    pub reference: String,
    pub id: String,
    pub label: String,
    /// Icon name, or an absolute path when the manifest names a file in the
    /// plugin folder.
    pub icon: String,
    pub description: String,
    #[serde(flatten)]
    pub run: Run,
}

/// One plugin folder: its actions, or why it could not be loaded.
#[derive(Debug, Clone, Serialize)]
pub struct Plugin {
    pub folder: String,
    pub name: String,
    pub version: String,
    pub description: String,
    pub author: String,
    pub actions: Vec<PluginAction>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// `~/.config/juhradial/plugins` (XDG aware).
pub fn plugins_dir() -> PathBuf {
    crate::profiles::get_config_dir().join(PLUGINS_DIR)
}

/// Every plugin folder under `dir`, sorted by folder name. Folders whose
/// manifest is missing or invalid are listed with `error` set and no actions,
/// so Settings can say what is wrong instead of silently hiding them.
pub fn load_all(dir: &Path) -> Vec<Plugin> {
    let Ok(entries) = fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut folders: Vec<PathBuf> = entries
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_dir())
        .filter(|p| p.file_name().and_then(|n| n.to_str()).is_some_and(valid_folder_name))
        .collect();
    folders.sort();
    folders.truncate(MAX_PLUGINS);
    folders.iter().map(|p| load_one(p)).collect()
}

fn load_one(folder: &Path) -> Plugin {
    let name = folder
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default()
        .to_string();
    let failed = |error: String| Plugin {
        folder: name.clone(),
        name: name.clone(),
        version: String::new(),
        description: String::new(),
        author: String::new(),
        actions: Vec::new(),
        error: Some(error),
    };
    let manifest_path = folder.join(MANIFEST);
    match fs::metadata(&manifest_path) {
        Ok(m) if m.len() > MAX_MANIFEST_BYTES => return failed(format!("{} is too large", MANIFEST)),
        Ok(_) => {}
        Err(_) => return failed(format!("no {}", MANIFEST)),
    }
    let text = match fs::read_to_string(&manifest_path) {
        Ok(t) => t,
        Err(e) => return failed(e.to_string()),
    };
    let manifest: ManifestFile = match serde_json::from_str(&text) {
        Ok(m) => m,
        Err(e) => return failed(format!("invalid {}: {}", MANIFEST, e)),
    };
    if manifest.schema > SCHEMA {
        return failed(format!("schema {} is newer than this build reads ({})", manifest.schema, SCHEMA));
    }
    let mut actions = Vec::new();
    let mut seen = HashSet::new();
    for action in manifest.actions.into_iter().take(MAX_ACTIONS) {
        match validate_action(folder, &name, action) {
            Ok(a) if seen.insert(a.id.clone()) => actions.push(a),
            Ok(a) => return failed(format!("duplicate action id \"{}\"", a.id)),
            Err(e) => return failed(e),
        }
    }
    Plugin {
        folder: name,
        name: manifest.name,
        version: manifest.version,
        description: manifest.description,
        author: manifest.author,
        actions,
        error: None,
    }
}

fn validate_action(folder: &Path, folder_name: &str, a: ActionFile) -> Result<PluginAction, String> {
    if !valid_action_id(&a.id) {
        return Err(format!("action id \"{}\" must be 1-64 of a-z, 0-9, - and _", a.id));
    }
    if a.label.trim().is_empty() {
        return Err(format!("action \"{}\" has no label", a.id));
    }
    let run = match (a.exec, a.dbus, a.script) {
        (Some(command), None, None) if !command.trim().is_empty() => {
            if !a.args.is_empty() {
                return Err(format!("action \"{}\": args belong to script actions", a.id));
            }
            Run::Exec { command }
        }
        (None, Some(call), None) => {
            if !a.args.is_empty() {
                return Err(format!("action \"{}\": dbus arguments go in dbus.args", a.id));
            }
            if call.service.is_empty() || call.path.is_empty() || call.interface.is_empty() || call.method.is_empty() {
                return Err(format!("action \"{}\": dbus needs service, path, interface and method", a.id));
            }
            // dbus-send carries strings, booleans, int32 and double; anything
            // else would be dropped from the call without a word.
            if call.args.iter().any(|v| !(v.is_string() || v.is_boolean() || v.is_number())) {
                return Err(format!("action \"{}\": dbus args may only be strings, booleans or numbers", a.id));
            }
            Run::Dbus { call }
        }
        (None, None, Some(script)) => Run::Script {
            program: script_path(folder, &script).map_err(|e| format!("action \"{}\": {}", a.id, e))?,
            args: a.args,
        },
        _ => return Err(format!("action \"{}\" needs exactly one of exec, dbus or script", a.id)),
    };
    Ok(PluginAction {
        reference: format!("{}/{}", folder_name, a.id),
        icon: icon_for(folder, &a.icon),
        id: a.id,
        label: a.label,
        description: a.description,
        run,
    })
}

/// A script must be a regular file inside the plugin folder.
fn script_path(folder: &Path, script: &str) -> Result<PathBuf, String> {
    let rel = Path::new(script);
    if script.is_empty() || rel.is_absolute() || rel.components().any(|c| !matches!(c, Component::Normal(_))) {
        return Err(format!("script \"{}\" must be a relative path inside the plugin folder", script));
    }
    let path = folder.join(rel);
    let real = path.canonicalize().map_err(|_| format!("script \"{}\" not found", script))?;
    let root = folder.canonicalize().map_err(|e| e.to_string())?;
    if !real.starts_with(&root) || !real.is_file() {
        return Err(format!("script \"{}\" must be a file inside the plugin folder", script));
    }
    Ok(real)
}

/// An icon file shipped in the plugin folder becomes an absolute path (the
/// overlay draws user icons from paths); anything else is an icon name.
fn icon_for(folder: &Path, icon: &str) -> String {
    let rel = Path::new(icon);
    let looks_like_file = icon.ends_with(".png") || icon.ends_with(".svg");
    if looks_like_file && !rel.is_absolute() && rel.components().all(|c| matches!(c, Component::Normal(_))) {
        let path = folder.join(rel);
        if path.is_file() {
            return path.to_string_lossy().into_owned();
        }
    }
    if icon.is_empty() {
        "application-x-executable-symbolic".to_string()
    } else {
        icon.to_string()
    }
}

fn valid_folder_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && !name.starts_with('.')
        && name.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
}

fn valid_action_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '-' | '_'))
}

/// Find `<folder>/<id>` among the plugins in `dir`.
pub fn find(dir: &Path, reference: &str) -> Option<PluginAction> {
    let (folder, id) = reference.split_once('/')?;
    if !valid_folder_name(folder) || !valid_action_id(id) {
        return None;
    }
    let plugin = load_one(&dir.join(folder));
    plugin.actions.into_iter().find(|a| a.id == id)
}

/// Run a plugin action. Errors name the reason (unknown reference, spawn
/// failure); the caller logs them.
pub async fn run(dir: &Path, reference: &str) -> Result<(), ActionError> {
    let action = find(dir, reference).ok_or(ActionError::InvalidAction)?;
    tracing::info!(plugin_action = %reference, "Running plugin action");
    match action.run {
        Run::Exec { command } => execute(ActionType::Command(command)).await,
        Run::Dbus { call } => execute(ActionType::DBus(call)).await,
        Run::Script { program, args } => {
            let cwd = program.parent().map(Path::to_path_buf).unwrap_or_default();
            crate::actions::spawn_program(&program, &args, &cwd)
        }
    }
}

async fn execute(action_type: ActionType) -> Result<(), ActionError> {
    ActionExecutor::execute(&Action { action_type, label: None, icon: None }).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn plugin(dir: &Path, folder: &str, manifest: &str) -> PathBuf {
        let p = dir.join(folder);
        fs::create_dir_all(&p).unwrap();
        fs::write(p.join(MANIFEST), manifest).unwrap();
        p
    }

    #[test]
    fn loads_exec_dbus_and_script_actions() {
        let tmp = tempfile::tempdir().unwrap();
        let folder = plugin(tmp.path(), "tools", r#"{
            "name": "Tools", "version": "1.0", "description": "d", "author": "a",
            "actions": [
                {"id": "shot", "label": "Region shot", "icon": "camera-photo-symbolic", "exec": "spectacle -r"},
                {"id": "dnd", "label": "Do not disturb", "dbus": {"service": "org.freedesktop.Notifications",
                    "path": "/org/freedesktop/Notifications", "interface": "org.freedesktop.Notifications",
                    "method": "Inhibit", "args": ["juhradial", "dnd", true, 3]}},
                {"id": "tidy", "label": "Tidy", "icon": "tidy.svg", "script": "bin/tidy.sh", "args": ["--all"]}
            ]}"#);
        fs::create_dir_all(folder.join("bin")).unwrap();
        fs::write(folder.join("bin/tidy.sh"), "#!/bin/sh\n").unwrap();
        fs::set_permissions(folder.join("bin/tidy.sh"), fs::Permissions::from_mode(0o755)).unwrap();
        fs::write(folder.join("tidy.svg"), "<svg/>").unwrap();

        let plugins = load_all(tmp.path());
        assert_eq!(plugins.len(), 1);
        let p = &plugins[0];
        assert!(p.error.is_none(), "{:?}", p.error);
        assert_eq!((p.name.as_str(), p.version.as_str()), ("Tools", "1.0"));
        let refs: Vec<&str> = p.actions.iter().map(|a| a.reference.as_str()).collect();
        assert_eq!(refs, ["tools/shot", "tools/dnd", "tools/tidy"]);
        assert!(matches!(p.actions[0].run, Run::Exec { .. }));
        assert!(matches!(p.actions[1].run, Run::Dbus { .. }));
        match &p.actions[2].run {
            Run::Script { program, args } => {
                assert!(program.ends_with("bin/tidy.sh"));
                assert_eq!(args, &["--all"]);
            }
            other => panic!("{:?}", other),
        }
        assert!(p.actions[2].icon.ends_with("tools/tidy.svg"), "shipped icon becomes a path");
        assert_eq!(p.actions[0].icon, "camera-photo-symbolic");

        let json = serde_json::to_value(&plugins).unwrap();
        assert_eq!(json[0]["actions"][0]["ref"], "tools/shot");
        assert_eq!(json[0]["actions"][0]["kind"], "exec");
        assert!(json[0].get("error").is_none());
    }

    #[test]
    fn broken_plugins_are_listed_with_the_reason() {
        let tmp = tempfile::tempdir().unwrap();
        plugin(tmp.path(), "a-bad-json", "{nope");
        plugin(tmp.path(), "b-two-kinds", r#"{"name": "x", "actions": [{"id": "x", "label": "X", "exec": "true", "script": "s"}]}"#);
        plugin(tmp.path(), "c-escape", r#"{"name": "x", "actions": [{"id": "x", "label": "X", "script": "../../bin/sh"}]}"#);
        plugin(tmp.path(), "d-bad-id", r#"{"name": "x", "actions": [{"id": "Bad Id", "label": "X", "exec": "true"}]}"#);
        plugin(tmp.path(), "e-dupe", r#"{"name": "x", "actions": [{"id": "x", "label": "X", "exec": "a"}, {"id": "x", "label": "Y", "exec": "b"}]}"#);
        plugin(tmp.path(), "f-newer", r#"{"schema": 99, "name": "x", "actions": []}"#);
        plugin(tmp.path(), "g-unknown-key", r#"{"name": "x", "actions": [{"id": "x", "label": "X", "exec": "a", "sudo": true}]}"#);
        plugin(tmp.path(), "h2-dbus-array-arg", r#"{"name": "x", "actions": [{"id": "x", "label": "X", "dbus": {"service": "a", "path": "/a", "interface": "i", "method": "m", "args": [[1]]}}]}"#);
        plugin(tmp.path(), "h-dbus-partial", r#"{"name": "x", "actions": [{"id": "x", "label": "X", "dbus": {"service": "a", "path": "", "interface": "i", "method": "m"}}]}"#);
        fs::create_dir_all(tmp.path().join("i-no-manifest")).unwrap();
        fs::create_dir_all(tmp.path().join(".hidden")).unwrap();

        let plugins = load_all(tmp.path());
        let folders: Vec<&str> = plugins.iter().map(|p| p.folder.as_str()).collect();
        assert_eq!(folders.len(), 10, "{:?}", folders);
        assert!(!folders.contains(&".hidden"));
        for p in &plugins {
            assert!(p.error.is_some(), "{} should fail", p.folder);
            assert!(p.actions.is_empty());
        }
        let err = |f: &str| plugins.iter().find(|p| p.folder == f).unwrap().error.clone().unwrap();
        assert!(err("b-two-kinds").contains("exactly one"));
        assert!(err("c-escape").contains("inside the plugin folder"));
        assert!(err("e-dupe").contains("duplicate"));
        assert!(err("f-newer").contains("newer"));
        assert!(err("i-no-manifest").contains("no plugin.json"));
        assert!(err("h2-dbus-array-arg").contains("strings, booleans or numbers"));
    }

    #[test]
    fn symlinked_script_outside_the_folder_is_refused() {
        let tmp = tempfile::tempdir().unwrap();
        let folder = plugin(tmp.path(), "sneaky", r#"{"name": "x", "actions": [{"id": "x", "label": "X", "script": "run"}]}"#);
        std::os::unix::fs::symlink("/bin/sh", folder.join("run")).unwrap();
        let p = &load_all(tmp.path())[0];
        assert!(p.error.as_deref().unwrap_or("").contains("inside the plugin folder"), "{:?}", p.error);
    }

    #[test]
    fn find_resolves_folder_and_id_and_refuses_traversal() {
        let tmp = tempfile::tempdir().unwrap();
        plugin(tmp.path(), "tools", r#"{"name": "T", "actions": [{"id": "shot", "label": "S", "exec": "true"}]}"#);
        assert_eq!(find(tmp.path(), "tools/shot").unwrap().label, "S");
        assert!(find(tmp.path(), "tools/nope").is_none());
        assert!(find(tmp.path(), "nope/shot").is_none());
        assert!(find(tmp.path(), "../tools/shot").is_none());
        assert!(find(tmp.path(), "tools").is_none());
        assert!(find(tmp.path(), "").is_none());
    }

    #[test]
    fn missing_plugins_dir_lists_nothing() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(load_all(&tmp.path().join("absent")).is_empty());
    }

    #[test]
    fn the_shipped_example_plugins_load_cleanly() {
        let examples = Path::new(env!("CARGO_MANIFEST_DIR")).join("../examples/plugins");
        let plugins = load_all(&examples);
        assert!(plugins.len() >= 2, "examples/plugins holds the documented examples");
        for p in &plugins {
            assert!(p.error.is_none(), "{}: {:?}", p.folder, p.error);
            assert!(!p.actions.is_empty(), "{} declares actions", p.folder);
        }
    }

    #[tokio::test]
    async fn run_rejects_unknown_references() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(matches!(run(tmp.path(), "x/y").await, Err(ActionError::InvalidAction)));
    }

    #[tokio::test]
    async fn run_starts_a_script_in_its_folder() {
        let tmp = tempfile::tempdir().unwrap();
        let folder = plugin(tmp.path(), "touch", r#"{"name": "T", "actions": [{"id": "go", "label": "Go", "script": "go.sh", "args": ["done"]}]}"#);
        fs::write(folder.join("go.sh"), "#!/bin/sh\n: > \"$1\"\n").unwrap();
        fs::set_permissions(folder.join("go.sh"), fs::Permissions::from_mode(0o755)).unwrap();
        run(tmp.path(), "touch/go").await.unwrap();
        for _ in 0..50 {
            if folder.join("done").exists() {
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        panic!("script did not run in its plugin folder");
    }
}
