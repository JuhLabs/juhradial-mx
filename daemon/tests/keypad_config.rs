use juhradiald::config::{ButtonAction, Config};

#[test]
fn keypad_defaults_are_enabled_and_inert() {
    let c: Config = serde_json::from_str("{}").unwrap();
    assert!(c.keypad.enabled);
    assert_eq!(c.keypad.active_page, 0);
    assert!(c.keypad.pages.is_empty());
}

#[test]
fn keypad_reuses_button_and_custom_action_schema() {
    let mut keys = vec![serde_json::json!({"action":"none"}); 9];
    keys[0] = serde_json::json!({"action":"copy", "label":"Copy", "icon":"edit-copy"});
    keys[1] = serde_json::json!({"action":"custom", "custom":{"kind":"shortcut", "value":"ctrl+shift+p"}});
    keys[2] = serde_json::json!({"action":"lock_screen"});
    for (at, kind) in ["command", "url", "macro", "plugin"].iter().enumerate() {
        keys[at + 3] = serde_json::json!({"action":"custom", "custom":{"kind":kind, "value":"example"}});
    }
    let value = serde_json::json!({"keypad":{"enabled":false,"active_page":0,"pages":[{"name":"Work","keys":keys}]}});
    let c: Config = serde_json::from_value(value).unwrap();
    assert!(!c.keypad.enabled);
    let page = &c.keypad.pages[0];
    assert_eq!(page.keys[0].action, ButtonAction::Copy);
    assert_eq!(page.keys[1].custom.value, "ctrl+shift+p");
    assert_eq!(page.keys[2].action, ButtonAction::LockScreen);
    for (at, kind) in ["command", "url", "macro", "plugin"].iter().enumerate() {
        assert_eq!(page.keys[at + 3].custom.kind, *kind);
    }
    let again: Config = serde_json::from_str(&serde_json::to_string(&c).unwrap()).unwrap();
    assert_eq!(again.keypad, c.keypad);
}

#[test]
fn keypad_rejects_wrong_grid_size_and_unknown_actions() {
    assert!(serde_json::from_str::<Config>(r#"{"keypad":{"pages":[{"name":"Bad","keys":[]}]}}"#).is_err());
    let keys = vec![serde_json::json!({"action":"invented"}); 9];
    assert!(serde_json::from_value::<Config>(serde_json::json!({"keypad":{"pages":[{"name":"Bad","keys":keys}]}})).is_err());
}
