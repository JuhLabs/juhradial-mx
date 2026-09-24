// SPDX-License-Identifier: GPL-3.0
//! Seconds each application spent in front, so Settings can suggest MX Keypad
//! profiles for the apps a user actually uses. Kept in the config folder
//! (`app_usage.json`, class -> seconds); it never leaves the machine.

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::{Duration, Instant};

const SAVE_EVERY: Duration = Duration::from_secs(60);
/// A window left in front longer than this (away from the desk) stops counting.
const MAX_STRETCH: Duration = Duration::from_secs(30 * 60);

pub struct AppUsage {
    path: Option<PathBuf>,
    seconds: HashMap<String, u64>,
    current: Option<(String, Instant)>,
    saved_at: Instant,
}

impl AppUsage {
    pub fn load(path: Option<PathBuf>) -> Self {
        let seconds = path
            .as_ref()
            .and_then(|p| std::fs::read_to_string(p).ok())
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default();
        Self { path, seconds, current: None, saved_at: Instant::now() }
    }

    /// The window class now in front ("" = none); saves at most once a minute.
    pub fn focus(&mut self, class: &str, now: Instant) {
        if let Some((app, since)) = self.current.take() {
            let spent = now.saturating_duration_since(since).min(MAX_STRETCH);
            *self.seconds.entry(app).or_default() += spent.as_secs();
        }
        if !class.is_empty() {
            self.current = Some((class.to_ascii_lowercase(), now));
        }
        if now.saturating_duration_since(self.saved_at) >= SAVE_EVERY {
            self.save();
            self.saved_at = now;
        }
    }

    pub fn seconds(&self, class: &str) -> u64 {
        self.seconds.get(class).copied().unwrap_or(0)
    }

    fn save(&self) {
        let Some(path) = &self.path else { return };
        if let Ok(text) = serde_json::to_string(&self.seconds) {
            let tmp = path.with_extension("json.tmp");
            if std::fs::write(&tmp, text).is_ok() {
                let _ = std::fs::rename(&tmp, path);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counts_time_in_front_and_caps_idle_stretches() {
        let dir = std::env::temp_dir().join(format!("jrmx-usage-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("app_usage.json");
        let t0 = Instant::now();
        let mut usage = AppUsage::load(Some(path.clone()));
        usage.focus("Code", t0);
        usage.focus("firefox", t0 + Duration::from_secs(90));
        usage.focus("code", t0 + Duration::from_secs(90) + Duration::from_secs(3 * 3600));
        assert_eq!(usage.seconds("code"), 90);
        assert_eq!(usage.seconds("firefox"), MAX_STRETCH.as_secs());
        let saved: HashMap<String, u64> =
            serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(saved.get("code"), Some(&90));
        assert_eq!(AppUsage::load(Some(path)).seconds("firefox"), MAX_STRETCH.as_secs());
        let _ = std::fs::remove_dir_all(dir);
    }
}
