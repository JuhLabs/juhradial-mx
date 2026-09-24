// SPDX-License-Identifier: GPL-3.0
//! MX Keypad worker. All HID I/O is independent of the mouse event loops.

use crate::config::{Config, KeypadConfig, KeypadKey, SharedConfig};
use mx_keypad::{Input, KeySet, KeyWindow, Keypad, PageButton};
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::mpsc::{self, UnboundedReceiver, UnboundedSender};

static CONNECTED: AtomicBool = AtomicBool::new(false);
static NAME: Mutex<String> = Mutex::new(String::new());
static REVISION: AtomicU64 = AtomicU64::new(0);
/// Lowercased class of the focused window (the daemon's focus tracker).
static FOCUSED_APP: Mutex<String> = Mutex::new(String::new());
const BLACK: &[u8] = include_bytes!("../../crates/mx-keypad/tests/fixtures/black.jpg");

pub enum Event {
    Connection(bool),
    Pressed(u8, u8),
    Action { binding: KeypadKey, pressed: bool },
}

pub fn status(config: &SharedConfig) -> (bool, String, u8, u8) {
    let c = config.read().map(|c| c.keypad.clone()).unwrap_or_default();
    (CONNECTED.load(Ordering::Relaxed), NAME.lock().map(|s| s.clone()).unwrap_or_default(),
        c.page_index(), c.page_count())
}

pub fn set_page(config: &SharedConfig, page: u8) -> Result<(), String> {
    let mut c = config.write().map_err(|e| e.to_string())?;
    if page >= c.keypad.page_count() { return Err("Keypad page is out of range".into()); }
    c.keypad.active_page = page;
    refresh();
    Ok(())
}

pub fn refresh() { REVISION.fetch_add(1, Ordering::Relaxed); }

/// Follow window focus: pages with `apps` show while one of them is in front.
pub fn set_focused_app(class: &str) {
    if let Ok(mut app) = FOCUSED_APP.lock() { *app = class.to_ascii_lowercase(); }
}

fn focused_app() -> String {
    FOCUSED_APP.lock().map(|a| a.clone()).unwrap_or_default()
}

/// Pages shown for `app`: its own pages, else the general ones (no apps),
/// else every page, so the keypad is never blank.
pub fn visible_pages(config: &KeypadConfig, app: &str) -> Vec<u8> {
    let indexed = || config.pages.iter().enumerate().take(usize::from(u8::MAX)).map(|(i, p)| (i as u8, p));
    let own: Vec<u8> = indexed().filter(|(_, p)| !app.is_empty() && p.apps.iter().any(|a| a.eq_ignore_ascii_case(app))).map(|(i, _)| i).collect();
    if !own.is_empty() { return own; }
    let general: Vec<u8> = indexed().filter(|(_, p)| p.apps.is_empty()).map(|(i, _)| i).collect();
    if !general.is_empty() { return general; }
    indexed().map(|(i, _)| i).collect()
}

/// The page a page button turns to, within the pages shown for the app.
fn turn_page(visible: &[u8], current: u8, button: PageButton) -> Option<u8> {
    if visible.is_empty() { return None; }
    let at = visible.iter().position(|&p| p == current).unwrap_or(0);
    let n = visible.len();
    Some(match button {
        PageButton::Left => visible[(at + n - 1) % n],
        PageButton::Right => visible[(at + 1) % n],
    })
}

pub struct Worker(Arc<AtomicBool>);

impl Drop for Worker {
    fn drop(&mut self) { self.0.store(true, Ordering::Relaxed); }
}

pub fn start(config: SharedConfig) -> (Worker, UnboundedReceiver<Event>) {
    let (tx, rx) = mpsc::unbounded_channel();
    let stop = Arc::new(AtomicBool::new(false));
    let worker = Worker(stop.clone());
    tokio::task::spawn_blocking(move || {
        while !tx.is_closed() && !stop.load(Ordering::Relaxed) {
            let enabled = config.read().map(|c| c.keypad.enabled).unwrap_or(false);
            if enabled {
                for device in mx_keypad::discover().unwrap_or_default() {
                    if tx.is_closed() { return; }
                    match Keypad::open(&device.path) {
                        Ok(mut keypad) => {
                            if let Ok(mut name) = NAME.lock() { *name = device.name; }
                            if let Err(error) = connected(&mut keypad, &config, &tx, &stop) {
                                tracing::debug!(%error, "MX Keypad disconnected or unavailable");
                            }
                            // Only the allowed feature report, including when disabled.
                            let _ = keypad.reset_to_logo();
                            if CONNECTED.swap(false, Ordering::Relaxed) { let _ = tx.send(Event::Connection(false)); }
                            break;
                        }
                        Err(error) => tracing::debug!(%error, "Cannot open MX Keypad"),
                    }
                }
            }
            std::thread::sleep(Duration::from_millis(2500));
        }
    });
    (worker, rx)
}

fn plates_dir(config: &SharedConfig) -> std::path::PathBuf {
    config.read().ok().and_then(|c| c.config_path.as_ref().and_then(|p| p.parent().map(Path::to_path_buf)))
        .or_else(Config::default_config_dir).unwrap_or_default().join("keypad/plates")
}

fn push_plates(keypad: &mut Keypad, dir: &Path, page: u8, configured: bool) -> io::Result<()> {
    for key in 1..=9 {
        let data = if configured {
            std::fs::read(dir.join(format!("p{page}-k{key}.jpg"))).ok()
                .filter(|b| b.len() <= 65535 && b.starts_with(&[0xff, 0xd8]) && b.ends_with(&[0xff, 0xd9]))
        } else { None };
        keypad.write_image(KeyWindow::new(key).unwrap(), data.as_deref().unwrap_or(BLACK))?;
    }
    Ok(())
}

/// Snapshots keep a release paired with its press across reloads and page turns.
#[derive(Default)]
struct HeldKeys {
    previous: KeySet,
    bindings: [Option<KeypadKey>; 9],
}

impl HeldKeys {
    fn update(&mut self, keys: KeySet, config: &KeypadConfig, tx: &UnboundedSender<Event>) {
        let diff = keys.diff(self.previous);
        for key in diff.up {
            if let Some(binding) = self.bindings[key as usize - 1].take() {
                let _ = tx.send(Event::Action { binding, pressed: false });
            }
        }
        let page = config.page_index();
        for key in diff.down {
            let _ = tx.send(Event::Pressed(page, key));
            if let Some(p) = config.pages.get(page as usize) {
                let binding = p.keys[key as usize - 1].clone();
                self.bindings[key as usize - 1] = Some(binding.clone());
                let _ = tx.send(Event::Action { binding, pressed: true });
            }
        }
        self.previous = keys;
    }

    fn release_all(&mut self, tx: &UnboundedSender<Event>) {
        self.update(KeySet::default(), &KeypadConfig::default(), tx);
    }
}

fn connected(keypad: &mut Keypad, config: &SharedConfig, tx: &UnboundedSender<Event>, stop: &AtomicBool) -> io::Result<()> {
    keypad.init()?;
    CONNECTED.store(true, Ordering::Relaxed);
    let _ = tx.send(Event::Connection(true));
    let dir = plates_dir(config);
    let mut held = HeldKeys::default();
    let mut pages = Vec::new();
    let mut shown = None;
    let mut revision = u64::MAX;
    let mut app = None;
    let result = (|| {
        while !tx.is_closed() && !stop.load(Ordering::Relaxed) {
            let mut cfg = config.read().map(|c| c.keypad.clone()).unwrap_or_default();
            if !cfg.enabled { break; }
            // A focus change brings up the new app's own pages (or leaves them).
            let focused = focused_app();
            if app.as_ref() != Some(&focused) {
                let visible = visible_pages(&cfg, &focused);
                if !visible.contains(&cfg.page_index()) {
                    if let Some(&first) = visible.first() {
                        let _ = set_page(config, first);
                        cfg.active_page = first;
                    }
                }
                app = Some(focused);
            }
            let next_revision = REVISION.load(Ordering::Relaxed);
            if shown.as_ref() != Some(&cfg) || revision != next_revision {
                push_plates(keypad, &dir, cfg.page_index(), !cfg.pages.is_empty())?;
                shown = Some(cfg.clone());
                revision = next_revision;
            }
            let Some(data) = keypad.read_report(Duration::from_millis(100))? else { continue };
            match mx_keypad::parse_input(&data) {
                Some(Input::Keys(keys)) => held.update(keys, &cfg, tx),
                Some(Input::Pages(next)) => {
                    let visible = visible_pages(&cfg, app.as_deref().unwrap_or(""));
                    for button in &next {
                        if !pages.contains(button) {
                            if let Some(next_page) = turn_page(&visible, cfg.page_index(), *button) {
                                let _ = set_page(config, next_page);
                            }
                        }
                    }
                    pages = next;
                }
                None => {}
            }
        }
        Ok(())
    })();
    held.release_all(tx);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{ButtonAction, KeypadPage};

    #[test]
    fn release_uses_press_binding_after_page_edit_and_disconnect() {
        let (tx, mut rx) = mpsc::unbounded_channel();
        let mut held = HeldKeys::default();
        let mut keys = std::array::from_fn(|_| KeypadKey::default());
        keys[0].action = ButtonAction::DpiShift;
        let c = KeypadConfig { pages: vec![KeypadPage { name: "Work".into(), keys, apps: Vec::new() }], ..Default::default() };
        let Some(Input::Keys(pressed)) = mx_keypad::parse_input(&[0x13, 0xff, 2, 0, 0, 1, 1, 0]) else { panic!() };
        held.update(pressed, &c, &tx);
        held.update(pressed, &KeypadConfig::default(), &tx);
        assert!(matches!(rx.try_recv(), Ok(Event::Pressed(0, 1))));
        assert!(matches!(rx.try_recv(), Ok(Event::Action { pressed: true, .. })));
        assert!(rx.try_recv().is_err());
        held.release_all(&tx);
        let Event::Action { binding, pressed } = rx.try_recv().unwrap() else { panic!() };
        assert!(!pressed);
        assert_eq!(binding.action, ButtonAction::DpiShift);
    }

    fn page(name: &str, apps: &[&str]) -> KeypadPage {
        KeypadPage { name: name.into(), keys: std::array::from_fn(|_| KeypadKey::default()),
                     apps: apps.iter().map(|a| a.to_string()).collect() }
    }

    #[test]
    fn app_pages_replace_the_general_ones_while_the_app_is_in_front() {
        let c = KeypadConfig {
            pages: vec![page("Home", &[]), page("Code", &["code"]), page("Code 2", &["code"]),
                        page("Web", &["firefox", "google-chrome"]), page("Tools", &[])],
            ..Default::default()
        };
        assert_eq!(visible_pages(&c, "code"), [1, 2]);
        assert_eq!(visible_pages(&c, "Google-Chrome"), [3]);
        assert_eq!(visible_pages(&c, "konsole"), [0, 4]);
        assert_eq!(visible_pages(&c, ""), [0, 4]);
        let only_apps = KeypadConfig { pages: vec![page("Code", &["code"])], ..Default::default() };
        assert_eq!(visible_pages(&only_apps, "konsole"), [0], "never a blank keypad");
        assert_eq!(turn_page(&[1, 2], 2, PageButton::Right), Some(1));
        assert_eq!(turn_page(&[1, 2], 1, PageButton::Left), Some(2));
        assert_eq!(turn_page(&[0, 4], 3, PageButton::Right), Some(4));
        assert_eq!(turn_page(&[], 0, PageButton::Right), None);
    }

    #[test]
    fn page_selection_is_bounded() {
        let c = crate::config::new_shared_config();
        assert!(set_page(&c, 0).is_err());
        c.write().unwrap().keypad.pages = vec![page("Page", &[])];
        assert!(set_page(&c, 0).is_ok());
        assert!(set_page(&c, 1).is_err());
        c.write().unwrap().keypad.active_page = 200;
        assert_eq!(status(&c).2, 0);
    }
}
