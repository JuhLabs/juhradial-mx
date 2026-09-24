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
    let result = (|| {
        while !tx.is_closed() && !stop.load(Ordering::Relaxed) {
            let cfg = config.read().map(|c| c.keypad.clone()).unwrap_or_default();
            if !cfg.enabled { break; }
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
                    for button in &next {
                        if !pages.contains(button) && cfg.page_count() > 0 {
                            let count = u16::from(cfg.page_count());
                            let page = u16::from(cfg.page_index());
                            let next_page = match button {
                                PageButton::Left => (page + count - 1) % count,
                                PageButton::Right => (page + 1) % count,
                            };
                            let _ = set_page(config, next_page as u8);
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
        let c = KeypadConfig { pages: vec![KeypadPage { name: "Work".into(), keys }], ..Default::default() };
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

    #[test]
    fn page_selection_is_bounded() {
        let c = crate::config::new_shared_config();
        assert!(set_page(&c, 0).is_err());
        c.write().unwrap().keypad.pages = vec![KeypadPage {
            name: "Page".into(), keys: std::array::from_fn(|_| KeypadKey::default()),
        }];
        assert!(set_page(&c, 0).is_ok());
        assert!(set_page(&c, 1).is_err());
        c.write().unwrap().keypad.active_page = 200;
        assert_eq!(status(&c).2, 0);
    }
}
