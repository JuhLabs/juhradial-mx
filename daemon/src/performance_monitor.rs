//! Performance Monitor Module (Story 4.4)
//!
//! Monitors frame times to detect GPU performance issues and automatically
//! disable blur effects when the system can't maintain 60fps.

use std::collections::VecDeque;
use std::time::{Duration, Instant};

/// Target frame time for 60fps (16.67ms)
pub const TARGET_FRAME_TIME_MS: f64 = 1000.0 / 60.0;

/// Number of consecutive slow frames before disabling blur
pub const SLOW_FRAME_THRESHOLD: usize = 3;

/// Size of the frame time buffer for rolling average
pub const FRAME_BUFFER_SIZE: usize = 10;

/// Blur mode setting
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum BlurMode {
    /// Automatically detect based on performance
    #[default]
    Auto,
    /// Always enable blur (ignore performance issues)
    ForceOn,
    /// Always disable blur (for performance or preference)
    ForceOff,
}

impl BlurMode {
    /// Parse from string (for config files)
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "on" | "forceon" | "force_on" | "enabled" => BlurMode::ForceOn,
            "off" | "forceoff" | "force_off" | "disabled" => BlurMode::ForceOff,
            _ => BlurMode::Auto,
        }
    }
}

/// Performance metrics for a single frame
#[derive(Debug, Clone, Copy)]
pub struct FrameMetrics {
    /// Time taken to render the frame
    pub render_time: Duration,
    /// Timestamp when frame was recorded
    pub timestamp: Instant,
}

/// Performance monitor for tracking frame times and blur decisions
#[derive(Debug)]
pub struct PerformanceMonitor {
    /// Circular buffer of recent frame times
    frame_times: VecDeque<FrameMetrics>,
    /// Count of consecutive slow frames
    consecutive_slow_frames: usize,
    /// Whether blur has been auto-disabled
    blur_disabled: bool,
    /// Manual blur mode override
    blur_mode: BlurMode,
}

impl Default for PerformanceMonitor {
    fn default() -> Self {
        Self::new()
    }
}

impl PerformanceMonitor {
    /// Create a new performance monitor
    pub fn new() -> Self {
        Self {
            frame_times: VecDeque::with_capacity(FRAME_BUFFER_SIZE),
            consecutive_slow_frames: 0,
            blur_disabled: false,
            blur_mode: BlurMode::Auto,
        }
    }

    /// Set the blur mode (manual override)
    pub fn set_blur_mode(&mut self, mode: BlurMode) {
        self.blur_mode = mode;
        tracing::debug!(mode = ?mode, "Blur mode set");
    }

    /// Get the current blur mode
    pub fn blur_mode(&self) -> BlurMode {
        self.blur_mode
    }

    /// Record a frame's render time
    ///
    /// This should be called after each frame is rendered with the
    /// time it took to render.
    pub fn record_frame(&mut self, render_time: Duration) {
        let metrics = FrameMetrics {
            render_time,
            timestamp: Instant::now(),
        };

        // Add to buffer (remove oldest if full)
        if self.frame_times.len() >= FRAME_BUFFER_SIZE {
            self.frame_times.pop_front();
        }
        self.frame_times.push_back(metrics);

        // Check if this frame was slow
        let frame_time_ms = render_time.as_secs_f64() * 1000.0;
        let is_slow = frame_time_ms > TARGET_FRAME_TIME_MS;

        if is_slow {
            self.consecutive_slow_frames += 1;
            tracing::trace!(
                frame_time_ms = frame_time_ms,
                consecutive = self.consecutive_slow_frames,
                "Slow frame detected"
            );

            // Check if we should disable blur
            if self.consecutive_slow_frames >= SLOW_FRAME_THRESHOLD && !self.blur_disabled {
                self.blur_disabled = true;
                tracing::warn!(
                    consecutive = self.consecutive_slow_frames,
                    avg_frame_time_ms = self.average_frame_time_ms(),
                    "Auto-disabling blur due to performance"
                );
            }
        } else {
            // Reset consecutive counter on fast frame
            self.consecutive_slow_frames = 0;
        }
    }

    /// Check if blur should be disabled based on current settings and performance
    pub fn should_disable_blur(&self) -> bool {
        match self.blur_mode {
            BlurMode::ForceOn => false,
            BlurMode::ForceOff => true,
            BlurMode::Auto => self.blur_disabled,
        }
    }

    /// Get the effective blur radius considering performance
    ///
    /// Returns 0 if blur is disabled, otherwise returns the theme blur radius.
    pub fn get_effective_blur_radius(&self, theme_blur_radius: u8) -> u8 {
        if self.should_disable_blur() {
            0
        } else {
            theme_blur_radius
        }
    }

    /// Calculate the average frame time in milliseconds
    pub fn average_frame_time_ms(&self) -> f64 {
        if self.frame_times.is_empty() {
            return 0.0;
        }

        let total: Duration = self.frame_times.iter().map(|m| m.render_time).sum();
        total.as_secs_f64() * 1000.0 / self.frame_times.len() as f64
    }

    /// Get the current FPS estimate
    pub fn estimated_fps(&self) -> f64 {
        let avg_ms = self.average_frame_time_ms();
        if avg_ms > 0.0 {
            1000.0 / avg_ms
        } else {
            0.0
        }
    }

    /// Get the number of frames in the buffer
    pub fn frame_count(&self) -> usize {
        self.frame_times.len()
    }

    /// Get the number of consecutive slow frames
    pub fn consecutive_slow_frames(&self) -> usize {
        self.consecutive_slow_frames
    }

    /// Check if blur was auto-disabled
    pub fn is_blur_auto_disabled(&self) -> bool {
        self.blur_disabled
    }

    /// Reset the performance monitor (e.g., after user changes settings)
    pub fn reset(&mut self) {
        self.frame_times.clear();
        self.consecutive_slow_frames = 0;
        self.blur_disabled = false;
        tracing::debug!("Performance monitor reset");
    }

    /// Force re-enable blur (for testing or user action)
    pub fn re_enable_blur(&mut self) {
        self.blur_disabled = false;
        self.consecutive_slow_frames = 0;
        tracing::info!("Blur re-enabled");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_blur_mode_default() {
        assert_eq!(BlurMode::default(), BlurMode::Auto);
    }

    #[test]
    fn test_blur_mode_from_str() {
        assert_eq!(BlurMode::from_str("auto"), BlurMode::Auto);
        assert_eq!(BlurMode::from_str("on"), BlurMode::ForceOn);
        assert_eq!(BlurMode::from_str("off"), BlurMode::ForceOff);
        assert_eq!(BlurMode::from_str("ForceOn"), BlurMode::ForceOn);
        assert_eq!(BlurMode::from_str("force_off"), BlurMode::ForceOff);
        assert_eq!(BlurMode::from_str("unknown"), BlurMode::Auto);
    }

    #[test]
    fn test_new_monitor() {
        let monitor = PerformanceMonitor::new();
        assert_eq!(monitor.frame_count(), 0);
        assert_eq!(monitor.consecutive_slow_frames(), 0);
        assert!(!monitor.is_blur_auto_disabled());
        assert_eq!(monitor.blur_mode(), BlurMode::Auto);
    }

    #[test]
    fn test_record_fast_frame() {
        let mut monitor = PerformanceMonitor::new();

        // Record a fast frame (10ms)
        monitor.record_frame(Duration::from_millis(10));

        assert_eq!(monitor.frame_count(), 1);
        assert_eq!(monitor.consecutive_slow_frames(), 0);
        assert!(!monitor.should_disable_blur());
    }

    #[test]
    fn test_record_slow_frames_triggers_blur_disable() {
        let mut monitor = PerformanceMonitor::new();

        // Record slow frames (20ms each, above 16.67ms threshold)
        for _ in 0..3 {
            monitor.record_frame(Duration::from_millis(20));
        }

        assert_eq!(monitor.consecutive_slow_frames(), 3);
        assert!(monitor.is_blur_auto_disabled());
        assert!(monitor.should_disable_blur());
    }

    #[test]
    fn test_fast_frame_resets_counter() {
        let mut monitor = PerformanceMonitor::new();

        // Two slow frames
        monitor.record_frame(Duration::from_millis(20));
        monitor.record_frame(Duration::from_millis(20));
        assert_eq!(monitor.consecutive_slow_frames(), 2);

        // One fast frame resets
        monitor.record_frame(Duration::from_millis(10));
        assert_eq!(monitor.consecutive_slow_frames(), 0);
    }

    #[test]
    fn test_force_on_ignores_performance() {
        let mut monitor = PerformanceMonitor::new();
        monitor.set_blur_mode(BlurMode::ForceOn);

        // Record 10 slow frames
        for _ in 0..10 {
            monitor.record_frame(Duration::from_millis(30));
        }

        // Blur should NOT be disabled due to ForceOn
        assert!(!monitor.should_disable_blur());
    }

    #[test]
    fn test_force_off_always_disables() {
        let mut monitor = PerformanceMonitor::new();
        monitor.set_blur_mode(BlurMode::ForceOff);

        // Even with fast frames, blur should be disabled
        monitor.record_frame(Duration::from_millis(5));

        assert!(monitor.should_disable_blur());
    }

    #[test]
    fn test_effective_blur_radius() {
        let mut monitor = PerformanceMonitor::new();

        // Normal case - returns theme value
        assert_eq!(monitor.get_effective_blur_radius(24), 24);

        // Force off - returns 0
        monitor.set_blur_mode(BlurMode::ForceOff);
        assert_eq!(monitor.get_effective_blur_radius(24), 0);

        // Force on - returns theme value even if auto-disabled
        monitor.set_blur_mode(BlurMode::ForceOn);
        monitor.blur_disabled = true; // Simulate auto-disable
        assert_eq!(monitor.get_effective_blur_radius(24), 24);
    }

    #[test]
    fn test_average_frame_time() {
        let mut monitor = PerformanceMonitor::new();

        monitor.record_frame(Duration::from_millis(10));
        monitor.record_frame(Duration::from_millis(20));

        let avg = monitor.average_frame_time_ms();
        assert!((avg - 15.0).abs() < 0.1); // Should be ~15ms average
    }

    #[test]
    fn test_estimated_fps() {
        let mut monitor = PerformanceMonitor::new();

        // 10ms frames = 100 FPS
        for _ in 0..5 {
            monitor.record_frame(Duration::from_millis(10));
        }

        let fps = monitor.estimated_fps();
        assert!((fps - 100.0).abs() < 1.0);
    }

    #[test]
    fn test_frame_buffer_limit() {
        let mut monitor = PerformanceMonitor::new();

        // Record more frames than buffer size
        for _ in 0..20 {
            monitor.record_frame(Duration::from_millis(10));
        }

        assert_eq!(monitor.frame_count(), FRAME_BUFFER_SIZE);
    }

    #[test]
    fn test_reset() {
        let mut monitor = PerformanceMonitor::new();

        // Build up some state
        for _ in 0..5 {
            monitor.record_frame(Duration::from_millis(20));
        }

        monitor.reset();

        assert_eq!(monitor.frame_count(), 0);
        assert_eq!(monitor.consecutive_slow_frames(), 0);
        assert!(!monitor.is_blur_auto_disabled());
    }

    #[test]
    fn test_re_enable_blur() {
        let mut monitor = PerformanceMonitor::new();

        // Trigger auto-disable
        for _ in 0..5 {
            monitor.record_frame(Duration::from_millis(20));
        }
        assert!(monitor.is_blur_auto_disabled());

        // Re-enable
        monitor.re_enable_blur();
        assert!(!monitor.is_blur_auto_disabled());
        assert_eq!(monitor.consecutive_slow_frames(), 0);
    }

    #[test]
    fn test_target_frame_time() {
        // 60fps = 16.67ms per frame
        assert!((TARGET_FRAME_TIME_MS - 16.67).abs() < 0.01);
    }
}
