//! Directional gestures for the gesture button.
//!
//! Holding the gesture button and moving the mouse selects one of four
//! directional actions (eight with the optional diagonals); a press without
//! movement is a click. Two pieces live here:
//!
//! - [`classify`], the pure delta-to-direction rule shared by every input
//!   path and covered by unit tests.
//! - [`GestureTracker`], a lock-free cell shared between whichever handler
//!   owns the button press (HID++ hidraw for diverted buttons, evdev when the
//!   button is not diverted) and the evdev loop that sees the mouse's relative
//!   motion. The press owner calls [`GestureTracker::start`], the evdev loop
//!   feeds [`GestureTracker::accumulate`] for every `REL_X`/`REL_Y` while the
//!   tracker is active, and the owner reads the total with
//!   [`GestureTracker::finish`] on release. Nothing here touches the radial
//!   menu signals, so a directional press never shows or hides the overlay.
//!
//! SPDX-License-Identifier: GPL-3.0

use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU32, Ordering};
use std::sync::Arc;

/// Outcome of a gesture-button press.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GestureDirection {
    Up,
    Down,
    Left,
    Right,
    /// The diagonals, only when [`classify`] runs with them enabled.
    UpLeft,
    UpRight,
    DownLeft,
    DownRight,
    /// Movement stayed under the threshold.
    Click,
}

impl GestureDirection {
    pub fn is_diagonal(self) -> bool {
        matches!(
            self,
            GestureDirection::UpLeft
                | GestureDirection::UpRight
                | GestureDirection::DownLeft
                | GestureDirection::DownRight
        )
    }
}

/// Classify the cursor delta accumulated during a press.
///
/// Distances are compared squared so no float is involved. Below
/// `threshold_px` the press is a click. With `diagonals` off the dominant
/// axis wins and an exact diagonal resolves to the horizontal axis so the
/// result is deterministic. With `diagonals` on the plane splits into eight
/// 45 degree sectors centred on the eight directions: a drag within 22.5
/// degrees of an axis is that axis, anything else is the diagonal between
/// them (tan 22.5 degrees is 0.414, compared as 414/1000). Screen Y grows
/// downward, so a negative `dy` is an upward drag.
pub fn classify(dx: i32, dy: i32, threshold_px: u32, diagonals: bool) -> GestureDirection {
    // Magnitudes as u64: |i32::MIN|^2 * 2 = 2^63 and u32::MAX^2 both fit.
    let (dx_abs, dy_abs) = (u64::from(dx.unsigned_abs()), u64::from(dy.unsigned_abs()));
    let threshold = u64::from(threshold_px);
    if dx_abs * dx_abs + dy_abs * dy_abs < threshold * threshold {
        return GestureDirection::Click;
    }
    let horizontal = if diagonals { dy_abs * 1000 < dx_abs * 414 } else { dx_abs >= dy_abs };
    let vertical = if diagonals { dx_abs * 1000 < dy_abs * 414 } else { !horizontal };
    if horizontal {
        if dx < 0 {
            GestureDirection::Left
        } else {
            GestureDirection::Right
        }
    } else if vertical {
        if dy < 0 {
            GestureDirection::Up
        } else {
            GestureDirection::Down
        }
    } else {
        match (dx < 0, dy < 0) {
            (true, true) => GestureDirection::UpLeft,
            (false, true) => GestureDirection::UpRight,
            (true, false) => GestureDirection::DownLeft,
            (false, false) => GestureDirection::DownRight,
        }
    }
}

/// Cursor-delta accumulator for the press currently in flight.
#[derive(Debug, Default)]
pub struct GestureTracker {
    active: AtomicBool,
    dx: AtomicI32,
    dy: AtomicI32,
    /// Drag distance that makes the press a direction (0 = no tick).
    threshold_px: AtomicU32,
    /// The drag crossed the threshold during this press.
    crossed: AtomicBool,
}

/// Handle shared by the press owner and the evdev motion loop.
pub type SharedGestureTracker = Arc<GestureTracker>;

impl GestureTracker {
    /// Create a tracker wrapped for sharing across tasks.
    pub fn new_shared() -> SharedGestureTracker {
        Arc::new(Self::default())
    }

    /// Begin a press: clear the totals and start accumulating motion.
    pub fn start(&self) {
        self.dx.store(0, Ordering::Relaxed);
        self.dy.store(0, Ordering::Relaxed);
        self.crossed.store(false, Ordering::Relaxed);
        self.active.store(true, Ordering::Release);
    }

    /// The drag distance that turns a press into a direction. Crossing it
    /// plays one haptic tick per press, so the hand feels the moment the
    /// release stops being a click. 0 = no tick.
    pub fn set_threshold(&self, px: u32) {
        self.threshold_px.store(px, Ordering::Relaxed);
    }

    /// Whether the drag has crossed the threshold during this press.
    pub fn crossed(&self) -> bool {
        self.crossed.load(Ordering::Relaxed)
    }

    /// Whether a directional press is in flight.
    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    /// Add one relative-motion sample. Ignored while no press is in flight,
    /// so the evdev loop can call this unconditionally for every REL event.
    pub fn accumulate(&self, dx: i32, dy: i32) {
        if !self.is_active() {
            return;
        }
        if dx != 0 {
            self.dx.fetch_add(dx, Ordering::Relaxed);
        }
        if dy != 0 {
            self.dy.fetch_add(dy, Ordering::Relaxed);
        }
        let t = u64::from(self.threshold_px.load(Ordering::Relaxed));
        if t > 0 && !self.crossed.load(Ordering::Relaxed) {
            let x = u64::from(self.dx.load(Ordering::Relaxed).unsigned_abs());
            let y = u64::from(self.dy.load(Ordering::Relaxed).unsigned_abs());
            if x * x + y * y >= t * t && !self.crossed.swap(true, Ordering::Relaxed) {
                crate::actions::pulse(crate::hidpp::HapticEvent::GestureTick);
            }
        }
    }

    /// End the press and return the accumulated `(dx, dy)`.
    pub fn finish(&self) -> (i32, i32) {
        self.active.store(false, Ordering::Release);
        (
            self.dx.swap(0, Ordering::Relaxed),
            self.dy.swap(0, Ordering::Relaxed),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_each_cardinal_direction() {
        for diagonals in [false, true] {
            assert_eq!(classify(0, -40, 40, diagonals), GestureDirection::Up);
            assert_eq!(classify(0, 40, 40, diagonals), GestureDirection::Down);
            assert_eq!(classify(-40, 0, 40, diagonals), GestureDirection::Left);
            assert_eq!(classify(40, 0, 40, diagonals), GestureDirection::Right);
        }
    }

    #[test]
    fn below_threshold_is_click() {
        for diagonals in [false, true] {
            assert_eq!(classify(0, 0, 40, diagonals), GestureDirection::Click);
            assert_eq!(classify(20, 20, 40, diagonals), GestureDirection::Click);
            assert_eq!(classify(-39, 0, 40, diagonals), GestureDirection::Click);
        }
    }

    #[test]
    fn dominant_axis_wins_and_diagonal_is_horizontal() {
        assert_eq!(classify(50, -30, 40, false), GestureDirection::Right);
        assert_eq!(classify(-30, 50, 40, false), GestureDirection::Down);
        assert_eq!(classify(40, -40, 40, false), GestureDirection::Right);
        assert_eq!(classify(-40, 40, 40, false), GestureDirection::Left);
    }

    #[test]
    fn diagonals_take_the_45_degree_sectors_between_the_axes() {
        assert_eq!(classify(50, -30, 40, true), GestureDirection::UpRight);
        assert_eq!(classify(-30, 50, 40, true), GestureDirection::DownLeft);
        assert_eq!(classify(40, -40, 40, true), GestureDirection::UpRight);
        assert_eq!(classify(-40, 40, 40, true), GestureDirection::DownLeft);
        assert_eq!(classify(-60, -60, 40, true), GestureDirection::UpLeft);
        assert_eq!(classify(60, 60, 40, true), GestureDirection::DownRight);
        // Within 22.5 degrees of an axis stays on that axis: 100 by 41 is
        // 22.3 degrees, 100 by 42 is 22.8 degrees.
        assert_eq!(classify(100, 41, 40, true), GestureDirection::Right);
        assert_eq!(classify(100, 42, 40, true), GestureDirection::DownRight);
        assert_eq!(classify(-41, -100, 40, true), GestureDirection::Up);
        assert_eq!(classify(-42, -100, 40, true), GestureDirection::UpLeft);
        assert!(GestureDirection::UpLeft.is_diagonal() && !GestureDirection::Up.is_diagonal());
    }

    #[test]
    fn extreme_deltas_do_not_overflow() {
        for diagonals in [false, true] {
            assert_eq!(classify(i32::MIN, 0, 40, diagonals), GestureDirection::Left);
            assert_eq!(classify(0, i32::MAX, 40, diagonals), GestureDirection::Down);
            assert_eq!(classify(i32::MIN, i32::MIN, u32::MAX, diagonals), GestureDirection::Click);
        }
        assert_eq!(classify(i32::MIN, i32::MIN, 40, true), GestureDirection::UpLeft);
    }

    #[test]
    fn zero_threshold_never_clicks_on_movement() {
        assert_eq!(classify(1, 0, 0, false), GestureDirection::Right);
        assert_eq!(classify(0, 0, 0, false), GestureDirection::Right);
    }

    #[test]
    fn tracker_accumulates_only_while_active() {
        let tracker = GestureTracker::new_shared();
        tracker.accumulate(100, 100);
        assert!(!tracker.is_active());

        tracker.start();
        assert!(tracker.is_active());
        tracker.accumulate(5, -3);
        tracker.accumulate(7, 0);
        tracker.accumulate(0, -4);
        assert_eq!(tracker.finish(), (12, -7));
        assert!(!tracker.is_active());

        tracker.accumulate(50, 50);
        tracker.start();
        assert_eq!(tracker.finish(), (0, 0));
    }

    #[test]
    fn crossing_the_threshold_is_noticed_once_per_press() {
        let tracker = GestureTracker::new_shared();
        tracker.set_threshold(40);
        tracker.start();
        tracker.accumulate(20, 20);
        assert!(!tracker.crossed());
        tracker.accumulate(10, 10);
        assert!(tracker.crossed());
        tracker.accumulate(-60, 0); // back under: stays crossed
        assert!(tracker.crossed());
        tracker.finish();
        tracker.start();
        assert!(!tracker.crossed());
    }
}
