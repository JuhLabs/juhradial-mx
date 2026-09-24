// SPDX-License-Identifier: GPL-3.0
//! MX Keypad worker. All HID I/O is independent of the mouse event loops.

use crate::config::{Config, KeypadConfig, KeypadKey, SharedConfig};
use mx_keypad::{Input, KeySet, KeyWindow, Keypad, PageButton};
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
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

fn read_jpeg(path: &Path) -> Option<Vec<u8>> {
    std::fs::read(path).ok()
        .filter(|b| b.len() <= 65535 && b.starts_with(&[0xff, 0xd8]) && b.ends_with(&[0xff, 0xd9]))
}

/// Upper bounds for one animated key (Settings renders at most this many).
const MAX_FRAMES: usize = 240;
const MIN_FRAME: Duration = Duration::from_millis(33);
const MAX_FRAME: Duration = Duration::from_secs(10);
/// Longest wait for a key report when no frame is due.
const IDLE_READ: Duration = Duration::from_millis(100);

/// An animated key (a GIF or animated WebP picture): the JPEG frames Settings
/// rendered next to its plate (`p{page}-k{key}-aNNN.jpg`) with their delays in
/// ms (`p{page}-k{key}.anim`, one per line). The device takes a small key
/// image in about half a millisecond, so nine keys at 30 fps are cheap.
struct Animation {
    frames: Vec<Vec<u8>>,
    delays: Vec<Duration>,
    next: usize,
    due: Instant,
}

fn load_animation(dir: &Path, page: u8, key: u8) -> Option<Animation> {
    let manifest = std::fs::read_to_string(dir.join(format!("p{page}-k{key}.anim"))).ok()?;
    let mut delays: Vec<Duration> = manifest.lines().take(MAX_FRAMES)
        .map_while(|line| line.trim().parse::<u64>().ok())
        .map(|ms| Duration::from_millis(ms).clamp(MIN_FRAME, MAX_FRAME)).collect();
    let frames: Vec<Vec<u8>> = (0..delays.len())
        .map_while(|i| read_jpeg(&dir.join(format!("p{page}-k{key}-a{i:03}.jpg")))).collect();
    if frames.len() < 2 { return None; }
    delays.truncate(frames.len());
    // The plate (frame 0) is on the key already; frame 1 follows its delay.
    Some(Animation { frames, due: Instant::now() + delays[0], delays, next: 1 })
}

fn push_plates(keypad: &mut Keypad, dir: &Path, page: u8, configured: bool) -> io::Result<Vec<Option<Animation>>> {
    let mut animations = Vec::with_capacity(9);
    for key in 1..=9 {
        let data = if configured { read_jpeg(&dir.join(format!("p{page}-k{key}.jpg"))) } else { None };
        keypad.write_image(KeyWindow::new(key).unwrap(), data.as_deref().unwrap_or(BLACK))?;
        animations.push(if configured && data.is_some() { load_animation(dir, page, key) } else { None });
    }
    Ok(animations)
}

/// How long the read may wait: until the next frame is due, at most IDLE_READ.
fn next_wait(animations: &[Option<Animation>], now: Instant) -> Duration {
    animations.iter().flatten().map(|a| a.due.saturating_duration_since(now)).min()
        .map_or(IDLE_READ, |d| d.min(IDLE_READ))
}

/// Show every frame that is due. The next one is timed from now, so a late
/// tick (a slow page push) never makes a key race through frames.
fn play_due(keypad: &mut Keypad, animations: &mut [Option<Animation>]) -> io::Result<()> {
    let now = Instant::now();
    for (i, slot) in animations.iter_mut().enumerate() {
        let Some(anim) = slot.as_mut().filter(|a| a.due <= now) else { continue };
        keypad.write_image(KeyWindow::new(i as u8 + 1).unwrap(), &anim.frames[anim.next])?;
        anim.due = now + anim.delays[anim.next];
        anim.next = (anim.next + 1) % anim.frames.len();
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
    let mut animations: Vec<Option<Animation>> = Vec::new();
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
            if shown.as_ref().map(|s: &KeypadConfig| s.brightness) != Some(cfg.brightness) {
                if let Some(percent) = cfg.brightness.filter(|p| (1..=100).contains(p)) {
                    if let Err(error) = keypad.set_brightness(percent) {
                        tracing::debug!(%error, "MX Keypad brightness not applied");
                    }
                }
            }
            if shown.as_ref() != Some(&cfg) || revision != next_revision {
                animations = push_plates(keypad, &dir, cfg.page_index(), !cfg.pages.is_empty())?;
                shown = Some(cfg.clone());
                revision = next_revision;
            }
            let report = keypad.read_report(next_wait(&animations, Instant::now()))?;
            play_due(keypad, &mut animations)?;
            let Some(data) = report else { continue };
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

    #[test]
    fn animated_keys_load_bounded_frames_and_wait_for_the_next_one() {
        let dir = std::env::temp_dir().join(format!("keypad-anim-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        // Delays are clamped to 33 ms..10 s; a missing frame ends the loop.
        std::fs::write(dir.join("p2-k5.anim"), "0\n120\n99999\n40\n").unwrap();
        for i in 0..3 { std::fs::write(dir.join(format!("p2-k5-a{i:03}.jpg")), BLACK).unwrap(); }
        let anim = load_animation(&dir, 2, 5).unwrap();
        assert_eq!(anim.frames.len(), 3);
        assert_eq!(anim.delays, [MIN_FRAME, Duration::from_millis(120), MAX_FRAME]);
        assert_eq!(anim.next, 1);
        // One frame is a still picture; a broken frame or no manifest is none.
        std::fs::write(dir.join("p2-k6.anim"), "50\n50\n").unwrap();
        std::fs::write(dir.join("p2-k6-a000.jpg"), BLACK).unwrap();
        std::fs::write(dir.join("p2-k6-a001.jpg"), b"not a jpeg").unwrap();
        assert!(load_animation(&dir, 2, 6).is_none());
        assert!(load_animation(&dir, 2, 7).is_none());
        let now = Instant::now();
        assert_eq!(next_wait(&[None, None], now), IDLE_READ);
        let soon = Animation { frames: vec![], delays: vec![], next: 0, due: now + Duration::from_millis(20) };
        assert_eq!(next_wait(&[None, Some(soon)], now), Duration::from_millis(20));
        let late = Animation { frames: vec![], delays: vec![], next: 0, due: now };
        assert_eq!(next_wait(&[Some(late)], now + Duration::from_millis(5)), Duration::ZERO);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
