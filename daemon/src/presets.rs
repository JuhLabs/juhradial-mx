//! Desktop-environment-portable action presets
//!
//! A preset is a semantic intent ("show the desktop", "lock the screen") that
//! resolves to a concrete [`Action`] for the running desktop environment. This
//! lets one button assignment do the right thing on KDE, GNOME, Hyprland, and
//! generic X11/Wayland without the UI hard-coding shortcuts.
//!
//! Resolution reuses the existing `actions.rs` primitives: the resolved
//! [`Action`] is run through [`ActionExecutor::execute`], which already knows how
//! to invoke kglobalaccel (KWin), spawn shell commands, and synthesize keys.
//!
//! SPDX-License-Identifier: GPL-3.0

use crate::actions::{detect_desktop, Action, ActionError, ActionExecutor, ActionType};
use crate::config::ButtonAction;

/// A desktop-portable semantic action.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Preset {
    ShowDesktop,
    SwitchDesktopLeft,
    SwitchDesktopRight,
    TaskSwitcher,
    CloseWindow,
    LockScreen,
    Calculator,
}

impl Preset {
    /// Parse the snake_case preset id used over D-Bus and in config.
    pub fn from_name(name: &str) -> Option<Preset> {
        Some(match name {
            "show_desktop" => Preset::ShowDesktop,
            "switch_desktop_left" => Preset::SwitchDesktopLeft,
            "switch_desktop_right" => Preset::SwitchDesktopRight,
            "task_switcher" => Preset::TaskSwitcher,
            "close_window" => Preset::CloseWindow,
            "lock_screen" => Preset::LockScreen,
            "calculator" => Preset::Calculator,
            _ => return None,
        })
    }

    /// The snake_case preset id.
    pub fn as_str(&self) -> &'static str {
        match self {
            Preset::ShowDesktop => "show_desktop",
            Preset::SwitchDesktopLeft => "switch_desktop_left",
            Preset::SwitchDesktopRight => "switch_desktop_right",
            Preset::TaskSwitcher => "task_switcher",
            Preset::CloseWindow => "close_window",
            Preset::LockScreen => "lock_screen",
            Preset::Calculator => "calculator",
        }
    }

    /// Map a config [`ButtonAction`] to its preset, if it is one.
    pub fn from_button_action(action: ButtonAction) -> Option<Preset> {
        Some(match action {
            ButtonAction::ShowDesktop => Preset::ShowDesktop,
            ButtonAction::SwitchDesktopLeft => Preset::SwitchDesktopLeft,
            ButtonAction::SwitchDesktopRight => Preset::SwitchDesktopRight,
            ButtonAction::TaskSwitcher => Preset::TaskSwitcher,
            ButtonAction::CloseWindow => Preset::CloseWindow,
            ButtonAction::LockScreen => Preset::LockScreen,
            ButtonAction::Calculator => Preset::Calculator,
            _ => return None,
        })
    }
}

fn shortcut(keys: &str) -> Action {
    Action { action_type: ActionType::Shortcut(keys.to_string()), label: None, icon: None }
}

fn command(cmd: &str) -> Action {
    Action { action_type: ActionType::Command(cmd.to_string()), label: None, icon: None }
}

fn kwin(name: &str) -> Action {
    Action { action_type: ActionType::KWin(name.to_string()), label: None, icon: None }
}

/// Resolve a preset to a concrete [`Action`] for a desktop environment.
///
/// `de` is one of the strings returned by [`detect_desktop`] ("kde", "gnome",
/// "hyprland", "sway", "cosmic", "unknown"). Unmatched desktops use the generic
/// fallback arm, which favours portable keyboard shortcuts and `loginctl`.
pub fn resolve(preset: Preset, de: &str) -> Action {
    match preset {
        // KDE has a dedicated "Show Desktop" kwin shortcut; elsewhere Super+D is
        // the de-facto binding.
        Preset::ShowDesktop => match de {
            "kde" => kwin("Show Desktop"),
            _ => shortcut("super+d"),
        },
        Preset::SwitchDesktopLeft => match de {
            "kde" => kwin("Switch to Previous Desktop"),
            "hyprland" => command("hyprctl dispatch workspace e-1"),
            _ => shortcut("ctrl+alt+Left"),
        },
        Preset::SwitchDesktopRight => match de {
            "kde" => kwin("Switch to Next Desktop"),
            "hyprland" => command("hyprctl dispatch workspace e+1"),
            _ => shortcut("ctrl+alt+Right"),
        },
        // Alt+Tab is universal across X11/Wayland compositors.
        Preset::TaskSwitcher => shortcut("alt+Tab"),
        Preset::CloseWindow => match de {
            "kde" => kwin("Window Close"),
            "hyprland" => command("hyprctl dispatch killactive"),
            _ => shortcut("alt+F4"),
        },
        // logind lock works on any systemd session regardless of DE.
        Preset::LockScreen => command("loginctl lock-session"),
        // Launch whichever calculator is installed; sh runs the chain.
        Preset::Calculator => command("kcalc || gnome-calculator || qalculate-gtk || xcalc"),
    }
}

/// Resolve and execute a preset for the current desktop environment.
///
/// Reuses [`ActionExecutor::execute`], so kglobalaccel/dbus/key-synthesis are
/// all handled by the existing primitives. Callers on the zbus executor must
/// drive this off-thread (the KWin/dbus arms block on `dbus-send`).
pub async fn execute_preset(preset: Preset) -> Result<(), ActionError> {
    let de = detect_desktop();
    let action = resolve(preset, de);
    tracing::info!(preset = preset.as_str(), de, "Executing preset");
    ActionExecutor::execute(&action).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn name_roundtrip() {
        for name in [
            "show_desktop",
            "switch_desktop_left",
            "switch_desktop_right",
            "task_switcher",
            "close_window",
            "lock_screen",
            "calculator",
        ] {
            let p = Preset::from_name(name).unwrap();
            assert_eq!(p.as_str(), name);
        }
        assert!(Preset::from_name("bogus").is_none());
    }

    #[test]
    fn button_action_mapping() {
        assert_eq!(Preset::from_button_action(ButtonAction::LockScreen), Some(Preset::LockScreen));
        assert_eq!(Preset::from_button_action(ButtonAction::Copy), None);
    }

    #[test]
    fn kde_uses_kwin_shortcut() {
        match resolve(Preset::ShowDesktop, "kde").action_type {
            ActionType::KWin(name) => assert_eq!(name, "Show Desktop"),
            other => panic!("expected KWin, got {:?}", other),
        }
    }

    #[test]
    fn hyprland_uses_hyprctl() {
        match resolve(Preset::SwitchDesktopRight, "hyprland").action_type {
            ActionType::Command(cmd) => assert!(cmd.contains("hyprctl")),
            other => panic!("expected Command, got {:?}", other),
        }
    }

    #[test]
    fn generic_fallback_is_keyboard() {
        match resolve(Preset::SwitchDesktopLeft, "unknown").action_type {
            ActionType::Shortcut(keys) => assert_eq!(keys, "ctrl+alt+Left"),
            other => panic!("expected Shortcut, got {:?}", other),
        }
    }

    #[test]
    fn lock_is_portable_loginctl() {
        match resolve(Preset::LockScreen, "gnome").action_type {
            ActionType::Command(cmd) => assert!(cmd.contains("loginctl")),
            other => panic!("expected Command, got {:?}", other),
        }
    }
}
