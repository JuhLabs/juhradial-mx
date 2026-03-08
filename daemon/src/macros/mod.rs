//! Macro system for JuhRadial MX
//!
//! Provides macro recording, playback, and storage for automating
//! keyboard/mouse sequences. Supports five repeat modes:
//!
//! - **Once** - play through the action list once
//! - **WhileHolding** - loop while trigger button is held
//! - **Toggle** - first trigger starts, second trigger stops
//! - **RepeatN** - loop N times then stop
//! - **Sequence** - separate actions for press/hold/release phases
//!
//! ## Architecture
//!
//! - `types` - Core data structures (MacroAction, RepeatMode, MacroConfig)
//! - `engine` - Playback engine (dedicated thread, precise timing)
//! - `recorder` - Event recording from evdev
//! - `storage` - File I/O with atomic writes
//! - `dpi` - DPI profile management for gaming mode

pub mod dpi;
pub mod engine;
pub mod recorder;
pub mod storage;
pub mod triggers;
pub mod types;

// Re-export commonly used types at the module level
pub use dpi::{DpiManager, DpiProfile};
pub use engine::MacroEngine;
pub use recorder::MacroRecorder;
pub use storage::{delete_macro, load_all_macros, load_macro, save_macro};
pub use triggers::{TriggerMap, SharedTriggerMap};
pub use types::{
    events_to_actions, MacroAction, MacroConfig, MacroEvent, PlaybackState, RepeatMode,
    SequenceActions,
};
