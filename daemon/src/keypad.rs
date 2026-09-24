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
/// The session's lock screen is up (screen_lock.rs follows logind).
static SCREEN_LOCKED: AtomicBool = AtomicBool::new(false);
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

pub fn set_screen_locked(locked: bool) { SCREEN_LOCKED.store(locked, Ordering::Relaxed); }

/// Live key images set over D-Bus (SetKeypadKeyImage), by (page, key):
/// runtime only, they win over the rendered plate until cleared.
type KeyImages = Vec<((u8, u8), Vec<u8>)>;
static KEY_IMAGES: Mutex<KeyImages> = Mutex::new(Vec::new());
/// Keys whose live image changed; the worker repaints only these, so other
/// keys keep their animation running.
static DIRTY_KEYS: Mutex<Vec<(u8, u8)>> = Mutex::new(Vec::new());

fn mark_dirty(page: u8, key: u8) {
    if let Ok(mut dirty) = DIRTY_KEYS.lock() {
        if !dirty.contains(&(page, key)) { dirty.push((page, key)); }
    }
}

fn take_dirty() -> Vec<(u8, u8)> {
    DIRTY_KEYS.lock().map(|mut d| std::mem::take(&mut *d)).unwrap_or_default()
}

/// Show `jpeg` (a 118 x 118 baseline JPEG, at most 64 KB) on a key.
pub fn set_key_image(page: u8, key: u8, jpeg: Vec<u8>) -> Result<(), String> {
    if !(1..=9).contains(&key) {
        return Err("Key must be 1..9".into());
    }
    if jpeg.len() > 65535 || !jpeg.starts_with(&[0xff, 0xd8]) || !jpeg.ends_with(&[0xff, 0xd9]) {
        return Err("The image must be a JPEG of at most 64 KB (118 x 118 pixels)".into());
    }
    let mut images = KEY_IMAGES.lock().map_err(|e| e.to_string())?;
    images.retain(|(at, _)| *at != (page, key));
    images.push(((page, key), jpeg));
    drop(images);
    mark_dirty(page, key);
    Ok(())
}

/// Give a key its own plate back.
pub fn clear_key_image(page: u8, key: u8) {
    if !(1..=9).contains(&key) { return; }
    if let Ok(mut images) = KEY_IMAGES.lock() { images.retain(|(at, _)| *at != (page, key)); }
    mark_dirty(page, key);
}

/// The state a multistate key shows now, by (page, key); 0 = its own.
static KEY_STATES: Mutex<Vec<((u8, u8), u8)>> = Mutex::new(Vec::new());

fn key_state(page: u8, key: u8) -> u8 {
    KEY_STATES.lock().ok().and_then(|s| s.iter().find(|(at, _)| *at == (page, key)).map(|(_, n)| *n)).unwrap_or(0)
}

fn set_key_state(page: u8, key: u8, state: u8) {
    if let Ok(mut states) = KEY_STATES.lock() {
        states.retain(|(at, _)| *at != (page, key));
        if state > 0 { states.push(((page, key), state)); }
    }
}

fn key_image(page: u8, key: u8) -> Option<Vec<u8>> {
    KEY_IMAGES.lock().ok()?.iter().find(|(at, _)| *at == (page, key)).map(|(_, j)| j.clone())
}

/// A "page" key action waiting for the keypad worker.
static REQUESTED_PAGE: Mutex<Option<String>> = Mutex::new(None);

/// Show a page by name, or "next" / "previous" within the pages shown now.
pub fn request_page(target: &str) {
    if let Ok(mut t) = REQUESTED_PAGE.lock() { *t = Some(target.trim().to_string()); }
}

/// The page a "page" action lands on.
fn page_for_request(config: &KeypadConfig, app: &str, target: &str) -> Option<u8> {
    let current = config.page_index();
    match target.to_ascii_lowercase().as_str() {
        "next" => turn_page(&visible_pages(config, app), current, PageButton::Right),
        "previous" => turn_page(&visible_pages(config, app), current, PageButton::Left),
        _ => config.pages.iter().take(usize::from(u8::MAX))
            .position(|p| p.name.trim().eq_ignore_ascii_case(target)).map(|i| i as u8),
    }
}

/// Follow window focus: pages with `apps` show while one of them is in front.
pub fn set_focused_app(class: &str) {
    if let Ok(mut app) = FOCUSED_APP.lock() { *app = class.to_ascii_lowercase(); }
}

/// Lowercased class of the window in front ("" before the first focus).
pub fn focused_app() -> String {
    FOCUSED_APP.lock().map(|a| a.clone()).unwrap_or_default()
}

/// Pages shown for `app`: its own pages, else the general ones (no apps),
/// else every page, so the keypad is never blank. Folders only open from a
/// key, so they stay out unless there is nothing else.
pub fn visible_pages(config: &KeypadConfig, app: &str) -> Vec<u8> {
    let all = || config.pages.iter().enumerate().take(usize::from(u8::MAX)).map(|(i, p)| (i as u8, p));
    if all().all(|(_, p)| p.folder) { return all().map(|(i, _)| i).collect(); }
    let indexed = || all().filter(|(_, p)| !p.folder);
    let own: Vec<u8> = indexed().filter(|(_, p)| !app.is_empty() && p.apps.iter().any(|a| a.eq_ignore_ascii_case(app))).map(|(i, _)| i).collect();
    if !own.is_empty() { return own; }
    let general: Vec<u8> = indexed().filter(|(_, p)| p.apps.is_empty()).map(|(i, _)| i).collect();
    if !general.is_empty() { return general; }
    indexed().map(|(i, _)| i).collect()
}

/// Holding the left page key this long peeks at the general pages while an
/// app's own pages are up (Options+ has the same gesture).
const PEEK_AFTER: Duration = Duration::from_millis(450);

/// The left page key is down: when, the page before, and whether it peeks.
struct Peek { since: Instant, from: u8, active: bool }

/// The first general page (no apps), when the app's own pages hide it.
fn peek_target(config: &KeypadConfig, visible: &[u8]) -> Option<u8> {
    let general = config.pages.iter().take(usize::from(u8::MAX)).position(|p| p.apps.is_empty())? as u8;
    (!visible.contains(&general)).then_some(general)
}

/// Where releasing a peek or leaving a folder lands: the page it came from
/// while that is still shown (focus may have moved meanwhile), else the first
/// shown page.
fn return_to(visible: &[u8], from: Option<u8>) -> Option<u8> {
    from.filter(|p| visible.contains(p)).or_else(|| visible.first().copied())
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

/// Paint one key (live image, else the plate of the state it shows, else
/// black) and load its animation.
fn push_key(keypad: &mut Keypad, dir: &Path, page: u8, key: u8, configured: bool) -> io::Result<Option<Animation>> {
    let live = key_image(page, key);
    let state = key_state(page, key);
    let other = if configured && state > 0 { read_jpeg(&dir.join(format!("p{page}-k{key}-s{state}.jpg"))) } else { None };
    let own = if configured && other.is_none() { read_jpeg(&dir.join(format!("p{page}-k{key}.jpg"))) } else { None };
    let data = other.as_deref().or(own.as_deref());
    keypad.write_image(KeyWindow::new(key).unwrap(), live.as_deref().or(data).unwrap_or(BLACK))?;
    Ok(if own.is_some() && live.is_none() { load_animation(dir, page, key) } else { None })
}

fn push_plates(keypad: &mut Keypad, dir: &Path, page: u8, configured: bool) -> io::Result<Vec<Option<Animation>>> {
    (1..=9).map(|key| push_key(keypad, dir, page, key, configured)).collect()
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
                let slot = &p.keys[key as usize - 1];
                // A multistate key runs the state it shows, then turns.
                let count = 1 + slot.states.len().min(usize::from(u8::MAX) - 1);
                let shown = usize::from(key_state(page, key)) % count;
                let binding = if shown == 0 { slot.clone() } else { slot.states[shown - 1].clone() };
                if count > 1 {
                    set_key_state(page, key, ((shown + 1) % count) as u8);
                    mark_dirty(page, key);
                }
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
    let mut peek: Option<Peek> = None;
    // The page a folder was opened from.
    let mut opener: Option<u8> = None;
    let mut blank = false;
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
            let requested = REQUESTED_PAGE.lock().ok().and_then(|mut t| t.take());
            if let Some(page) = requested.and_then(|t| page_for_request(&cfg, app.as_deref().unwrap_or(""), &t)) {
                let is_folder = |p: u8| cfg.pages.get(p as usize).is_some_and(|p| p.folder);
                opener = if !is_folder(page) { None } else if is_folder(cfg.page_index()) { opener } else { Some(cfg.page_index()) };
                let _ = set_page(config, page);
                cfg.active_page = page;
            }
            // Locked screen: blank keys, the panel dimmed (only when the user
            // set a level, which unlock restores) and no key does anything:
            // a text key must never type into the lock screen.
            if SCREEN_LOCKED.load(Ordering::Relaxed) && cfg.dim_on_lock {
                if !blank {
                    held.release_all(tx);
                    peek = None;
                    pages.clear();
                    animations.clear();
                    for key in 1..=9 { keypad.write_image(KeyWindow::new(key).unwrap(), BLACK)?; }
                    if cfg.brightness.is_some() { let _ = keypad.set_brightness(1); }
                    shown = None; // unlock repaints and restores the level
                    blank = true;
                }
                keypad.read_report(IDLE_READ)?;
                continue;
            }
            blank = false;
            let next_revision = REVISION.load(Ordering::Relaxed);
            if shown.as_ref().map(|s: &KeypadConfig| s.brightness) != Some(cfg.brightness) {
                if let Some(percent) = cfg.brightness.filter(|p| (1..=100).contains(p)) {
                    if let Err(error) = keypad.set_brightness(percent) {
                        tracing::debug!(%error, "MX Keypad brightness not applied");
                    }
                }
            }
            let dirty = take_dirty();
            if shown.as_ref() != Some(&cfg) || revision != next_revision {
                animations = push_plates(keypad, &dir, cfg.page_index(), !cfg.pages.is_empty())?;
                shown = Some(cfg.clone());
                revision = next_revision;
            } else {
                for (page, key) in dirty.into_iter().filter(|&(page, _)| page == cfg.page_index()) {
                    animations[key as usize - 1] = push_key(keypad, &dir, page, key, !cfg.pages.is_empty())?;
                }
            }
            if let Some(held) = peek.as_mut().filter(|p| !p.active && p.since.elapsed() >= PEEK_AFTER) {
                let visible = visible_pages(&cfg, app.as_deref().unwrap_or(""));
                if let Some(general) = peek_target(&cfg, &visible) {
                    let _ = set_page(config, general);
                }
                held.active = true;
                continue;
            }
            let mut wait = next_wait(&animations, Instant::now());
            if let Some(held) = peek.as_ref().filter(|p| !p.active) {
                wait = wait.min(PEEK_AFTER.saturating_sub(held.since.elapsed()));
            }
            let report = keypad.read_report(wait)?;
            play_due(keypad, &mut animations)?;
            let Some(data) = report else { continue };
            match mx_keypad::parse_input(&data) {
                Some(Input::Keys(keys)) => held.update(keys, &cfg, tx),
                Some(Input::Pages(next)) => {
                    let visible = visible_pages(&cfg, app.as_deref().unwrap_or(""));
                    let in_folder = cfg.pages.get(cfg.page_index() as usize).is_some_and(|p| p.folder);
                    let fresh: Vec<PageButton> = next.iter().copied().filter(|b| !pages.contains(b)).collect();
                    if in_folder && !fresh.is_empty() {
                        if let Some(back) = return_to(&visible, opener.take()) {
                            let _ = set_page(config, back);
                        }
                    }
                    for button in fresh.iter().filter(|_| !in_folder) {
                        // Left key while an app's pages hide the general
                        // ones: a tap turns on release, a hold peeks.
                        if *button == PageButton::Left && peek_target(&cfg, &visible).is_some() {
                            peek = Some(Peek { since: Instant::now(), from: cfg.page_index(), active: false });
                            continue;
                        }
                        if let Some(next_page) = turn_page(&visible, cfg.page_index(), *button) {
                            let _ = set_page(config, next_page);
                        }
                    }
                    if pages.contains(&PageButton::Left) && !next.contains(&PageButton::Left) {
                        if let Some(held) = peek.take() {
                            let back = if held.active { return_to(&visible, Some(held.from)) } else {
                                turn_page(&visible, cfg.page_index(), PageButton::Left)
                            };
                            if let Some(page) = back {
                                let _ = set_page(config, page);
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
        let c = KeypadConfig { pages: vec![KeypadPage { name: "Work".into(), keys, apps: Vec::new(), folder: false }], ..Default::default() };
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
        KeypadPage { name: name.into(), keys: std::array::from_fn(|_| KeypadKey::default()), folder: false,
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
    fn live_key_images_are_checked_and_replace_only_their_key() {
        assert!(set_key_image(0, 10, BLACK.to_vec()).is_err());
        assert!(set_key_image(0, 1, b"not a jpeg".to_vec()).is_err());
        assert!(set_key_image(7, 3, BLACK.to_vec()).is_ok());
        assert_eq!(key_image(7, 3).as_deref(), Some(BLACK));
        assert_eq!(key_image(7, 4), None);
        clear_key_image(7, 3);
        clear_key_image(7, 0);
        assert_eq!(key_image(7, 3), None);
        let dirty = take_dirty();
        assert_eq!(dirty.iter().filter(|&&k| k == (7, 3)).count(), 1, "one repaint of that key only");
        assert!(!dirty.contains(&(7, 4)) && !dirty.contains(&(7, 0)));
    }

    /// A device double: the worker's end of a datagram pair (one report per
    /// datagram, like hidraw) and the test's end.
    fn fake_keypad() -> (Keypad, std::os::unix::net::UnixDatagram) {
        let (worker, device) = std::os::unix::net::UnixDatagram::pair().unwrap();
        (Keypad::from_file(std::fs::File::from(std::os::fd::OwnedFd::from(worker))), device)
    }

    /// Reports the worker sent within `wait`: (first image packets by key, brightness levels).
    fn sent(device: &std::os::unix::net::UnixDatagram, wait: Duration) -> (Vec<u8>, Vec<u8>) {
        device.set_read_timeout(Some(wait)).unwrap();
        let (mut keys, mut levels) = (Vec::new(), Vec::new());
        let mut buf = vec![0u8; 8192];
        while let Ok(n) = device.recv(&mut buf) {
            let r = &buf[..n];
            if r[0] == 0x14 && r[4] & 0x80 != 0 {
                let x = u16::from_be_bytes([r[9], r[10]]);
                let y = u16::from_be_bytes([r[11], r[12]]);
                keys.push(((y - 6) / 158 * 3 + (x - 23) / 158 + 1) as u8);
            } else if r[..4] == [0x11, 0xff, 0x0f, 0x2b] {
                levels.push(r[5]);
            }
        }
        (keys, levels)
    }

    /// A worker on a fake keypad. Worker tests share process-wide state (lock,
    /// requested page), so they run one at a time.
    struct FakeWorker {
        device: std::os::unix::net::UnixDatagram,
        config: SharedConfig,
        rx: UnboundedReceiver<Event>,
        stop: Arc<AtomicBool>,
        thread: Option<std::thread::JoinHandle<io::Result<()>>>,
        _serial: std::sync::MutexGuard<'static, ()>,
    }

    static WORKER_TESTS: Mutex<()> = Mutex::new(());

    impl FakeWorker {
        fn start(pages: Vec<KeypadPage>, brightness: Option<u8>, locked: bool) -> Self {
            let serial = WORKER_TESTS.lock().unwrap_or_else(|e| e.into_inner());
            set_screen_locked(locked);
            let (mut keypad, device) = fake_keypad();
            let config = crate::config::new_shared_config();
            {
                let mut c = config.write().unwrap();
                c.config_path = Some(std::env::temp_dir().join(format!("jrmx-worker-{}/config.json", std::process::id())));
                c.keypad.pages = pages;
                c.keypad.brightness = brightness;
            }
            let (tx, rx) = mpsc::unbounded_channel();
            let stop = Arc::new(AtomicBool::new(false));
            let (worker_stop, worker_config) = (stop.clone(), config.clone());
            let thread = std::thread::spawn(move || connected(&mut keypad, &worker_config, &tx, &worker_stop));
            FakeWorker { device, config, rx, stop, thread: Some(thread), _serial: serial }
        }

        fn events(&mut self, wait: Duration) -> Vec<Event> {
            std::thread::sleep(wait);
            std::iter::from_fn(|| self.rx.try_recv().ok()).collect()
        }

        fn page(&self) -> u8 { self.config.read().unwrap().keypad.page_index() }

        /// Let the worker run while reading what it sends: a unix datagram
        /// queue holds only a few reports, and a full one stalls its writes.
        fn settle(&self) -> (Vec<u8>, Vec<u8>) { sent(&self.device, Duration::from_millis(250)) }
    }

    impl Drop for FakeWorker {
        fn drop(&mut self) {
            set_screen_locked(false);
            self.stop.store(true, Ordering::Relaxed);
            if let Some(thread) = self.thread.take() { let _ = thread.join(); }
        }
    }

    const PRESS_1: [u8; 8] = [0x13, 0xff, 2, 0, 0, 1, 1, 0];
    const RELEASE_ALL: [u8; 7] = [0x13, 0xff, 2, 0, 0, 1, 0];
    const RIGHT_DOWN: [u8; 8] = [0x11, 0xff, 0x0b, 0, 0x01, 0xa2, 0, 0];
    const BUTTONS_UP: [u8; 6] = [0x11, 0xff, 0x0b, 0, 0, 0];

    #[test]
    fn a_locked_screen_blanks_the_keys_and_no_key_runs_until_unlock() {
        let mut keys: [KeypadKey; 9] = std::array::from_fn(|_| KeypadKey::default());
        keys[0].action = ButtonAction::DpiShift;
        let mut w = FakeWorker::start(vec![KeypadPage { name: "Work".into(), keys, apps: Vec::new(), folder: false }], Some(80), true);

        let (blanked, levels) = sent(&w.device, Duration::from_millis(400));
        assert_eq!(blanked, (1..=9).collect::<Vec<u8>>(), "every key goes blank");
        assert_eq!(levels, [1], "the level the user set dips while locked");
        w.device.send(&PRESS_1).unwrap();
        w.device.send(&RELEASE_ALL).unwrap();
        let events = w.events(Duration::from_millis(300));
        assert!(events.iter().all(|e| matches!(e, Event::Connection(_))), "no key acts on a locked screen");

        set_screen_locked(false);
        let (painted, levels) = sent(&w.device, Duration::from_millis(400));
        assert_eq!(painted, (1..=9).collect::<Vec<u8>>(), "unlock paints the page again");
        assert_eq!(levels, [80], "and restores the user's level");
        w.device.send(&PRESS_1).unwrap();
        let pressed = w.events(Duration::from_millis(300)).into_iter()
            .any(|e| matches!(e, Event::Action { pressed: true, ref binding } if binding.action == ButtonAction::DpiShift));
        assert!(pressed, "keys work again after unlock");
    }

    #[test]
    fn a_folder_opens_from_a_key_and_either_page_button_goes_back() {
        let mut tools = page("Tools", &[]);
        tools.folder = true;
        let c = KeypadConfig { pages: vec![page("Home", &[]), tools.clone(), page("Media", &[])], ..Default::default() };
        assert_eq!(visible_pages(&c, ""), [0, 2], "folders stay out of the page buttons");
        assert_eq!(page_for_request(&c, "", "tools"), Some(1), "a page key still opens one");

        let w = FakeWorker::start(c.pages.clone(), None, false);
        w.config.write().unwrap().keypad.active_page = 2;
        w.settle();
        request_page("Tools");
        w.settle();
        assert_eq!(w.page(), 1);
        w.device.send(&RIGHT_DOWN).unwrap();
        w.device.send(&BUTTONS_UP).unwrap();
        w.settle();
        assert_eq!(w.page(), 2, "back to the page it was opened from, not the next one");
        w.device.send(&RIGHT_DOWN).unwrap();
        w.device.send(&BUTTONS_UP).unwrap();
        w.settle();
        assert_eq!(w.page(), 0, "outside a folder the buttons turn pages again (Tools skipped)");
    }

    #[test]
    fn a_multistate_key_runs_the_state_it_shows_and_repaints_only_itself() {
        let mut keys: [KeypadKey; 9] = std::array::from_fn(|_| KeypadKey::default());
        keys[4].action = ButtonAction::DpiShift;
        keys[4].states = vec![KeypadKey { action: ButtonAction::Copy, ..Default::default() }];
        set_key_state(0, 5, 0);
        let mut w = FakeWorker::start(vec![KeypadPage { name: "Work".into(), keys, apps: Vec::new(), folder: false }], None, false);
        w.settle();
        let press_5 = [0x13, 0xff, 2, 0, 0, 1, 5, 0];
        let mut runs = Vec::new();
        for _ in 0..3 {
            w.device.send(&press_5).unwrap();
            w.device.send(&RELEASE_ALL).unwrap();
            let (painted, _) = w.settle();
            assert_eq!(painted, [5], "only the key that turned is repainted");
            runs.extend(w.events(Duration::ZERO).into_iter().filter_map(|e| match e {
                Event::Action { pressed: true, binding } => Some(binding.action),
                _ => None,
            }));
        }
        assert_eq!(runs, [ButtonAction::DpiShift, ButtonAction::Copy, ButtonAction::DpiShift]);
        set_key_state(0, 5, 0);
    }

    #[test]
    fn a_peek_returns_to_its_page_only_while_that_page_is_shown() {
        assert_eq!(return_to(&[1, 2], Some(2)), Some(2));
        assert_eq!(return_to(&[0, 4], Some(2)), Some(0), "focus moved to an app without that page");
        assert_eq!(return_to(&[0, 4], None), Some(0));
        assert_eq!(return_to(&[], Some(2)), None);
    }

    #[test]
    fn peeking_needs_general_pages_hidden_by_the_app() {
        let mut c = KeypadConfig { pages: vec![page("Home", &[]), page("Code", &["code"])], ..KeypadConfig::default() };
        let in_code = visible_pages(&c, "code");
        assert_eq!(peek_target(&c, &in_code), Some(0));
        assert_eq!(peek_target(&c, &visible_pages(&c, "")), None);
        c.pages = vec![page("Code", &["code"])];
        assert_eq!(peek_target(&c, &visible_pages(&c, "code")), None);
    }

    #[test]
    fn page_keys_go_by_name_or_step_within_the_shown_pages() {
        let mut c = KeypadConfig {
            pages: vec![page("Home", &[]), page("Code", &["code"]), page("Media", &[]), page("Code 2", &["code"])],
            ..KeypadConfig::default()
        };
        assert_eq!(page_for_request(&c, "", "media"), Some(2));
        assert_eq!(page_for_request(&c, "", "Nope"), None);
        assert_eq!(page_for_request(&c, "", "next"), Some(2));
        c.active_page = 1;
        assert_eq!(page_for_request(&c, "code", "next"), Some(3));
        assert_eq!(page_for_request(&c, "code", "previous"), Some(3));
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
