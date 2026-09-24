//! App profiles "Try now": for a short time the daemon acts as if another app
//! were in front, so its buttons, ring, pointer settings and keypad pages can
//! be tried from Settings without switching windows. Real focus changes wait
//! until the trial ends; then the app really in front comes back.

use std::sync::OnceLock;
use std::time::Duration;
use tokio::sync::mpsc::{UnboundedReceiver, UnboundedSender};
use tokio::time::Instant;

/// The longest a trial may hold (Settings asks for a minute).
pub const MAX_TRIAL: Duration = Duration::from_secs(300);

type Trial = Option<(String, Duration)>;
static TRIALS: OnceLock<UnboundedSender<Trial>> = OnceLock::new();

/// Act as if `class` were in front for `seconds` (capped at MAX_TRIAL).
pub fn start(class: &str, seconds: u32) -> bool {
    let class = class.trim().to_lowercase();
    if class.is_empty() || seconds == 0 {
        return false;
    }
    let length = Duration::from_secs(u64::from(seconds)).min(MAX_TRIAL);
    TRIALS.get().is_some_and(|tx| tx.send(Some((class, length))).is_ok())
}

/// End a trial now (the app really in front comes back).
pub fn stop() -> bool {
    TRIALS.get().is_some_and(|tx| tx.send(None).is_ok())
}

/// The focus the daemon acts on: the tracker's classes, or a trial's.
pub struct FocusSource {
    real: UnboundedReceiver<String>,
    trials: UnboundedReceiver<Trial>,
    last_real: String,
    until: Option<Instant>,
}

impl FocusSource {
    /// Wrap the tracker's channel; start() and stop() reach this source.
    pub fn new(real: UnboundedReceiver<String>) -> Self {
        let (tx, trials) = tokio::sync::mpsc::unbounded_channel();
        let _ = TRIALS.set(tx);
        Self::with_trials(real, trials)
    }

    fn with_trials(real: UnboundedReceiver<String>, trials: UnboundedReceiver<Trial>) -> Self {
        Self { real, trials, last_real: String::new(), until: None }
    }

    pub fn in_trial(&self) -> bool {
        self.until.is_some()
    }

    /// The next class to act on; None when the tracker's channel closed.
    pub async fn next(&mut self) -> Option<String> {
        loop {
            let until = self.until;
            tokio::select! {
                real = self.real.recv() => {
                    let class = real?;
                    self.last_real = class.clone();
                    if self.until.is_none() {
                        return Some(class);
                    }
                }
                Some(trial) = self.trials.recv() => match trial {
                    Some((class, length)) => {
                        self.until = Some(Instant::now() + length);
                        return Some(class);
                    }
                    None => {
                        if self.until.take().is_some() {
                            return Some(self.last_real.clone());
                        }
                    }
                },
                () = async { tokio::time::sleep_until(until.unwrap_or_else(Instant::now)).await }, if until.is_some() => {
                    self.until = None;
                    return Some(self.last_real.clone());
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn a_trial_holds_its_app_then_the_real_one_returns() {
        let (real_tx, real_rx) = tokio::sync::mpsc::unbounded_channel();
        let (trial_tx, trial_rx) = tokio::sync::mpsc::unbounded_channel();
        let mut focus = FocusSource::with_trials(real_rx, trial_rx);
        real_tx.send("konsole".to_string()).unwrap();
        assert_eq!(focus.next().await.as_deref(), Some("konsole"));
        trial_tx.send(Some(("firefox".to_string(), Duration::from_millis(80)))).unwrap();
        assert_eq!(focus.next().await.as_deref(), Some("firefox"));
        assert!(focus.in_trial());
        // A real focus change during the trial waits for its end.
        real_tx.send("org.kde.dolphin".to_string()).unwrap();
        assert_eq!(focus.next().await.as_deref(), Some("org.kde.dolphin"));
        assert!(!focus.in_trial());
        // Stopping early brings the real app back; a stray stop does nothing.
        trial_tx.send(Some(("code".to_string(), Duration::from_secs(60)))).unwrap();
        assert_eq!(focus.next().await.as_deref(), Some("code"));
        trial_tx.send(None).unwrap();
        assert_eq!(focus.next().await.as_deref(), Some("org.kde.dolphin"));
        trial_tx.send(None).unwrap();
        real_tx.send("kate".to_string()).unwrap();
        assert_eq!(focus.next().await.as_deref(), Some("kate"));
        drop(real_tx);
        assert_eq!(focus.next().await, None);
    }
}
