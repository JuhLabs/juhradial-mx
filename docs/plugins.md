# Plugins

A plugin adds actions to JuhRadial MX without touching its code. It is a folder in `~/.config/juhradial/plugins/` (or `$XDG_CONFIG_HOME/juhradial/plugins/`) with a `plugin.json` that declares one or more actions. Every action runs one of three ways: a shell command, a D-Bus method call, or a script shipped in the plugin folder.

Plugin actions appear in the slice action picker (**Settings → Buttons → Radial menu**, pick a slice, then **Action**) under the plugin's name, and **Settings → Settings → Plugins** lists every installed plugin with its action count, or the reason it did not load. Both read the folder when you open them, so a new or edited plugin needs no restart.

!!! warning "Plugins run as you"
    A plugin action runs with your user's rights, exactly like an `exec` slice in `config.json`. Install plugins you have read or trust. JuhRadial never runs a plugin by itself: an action runs only when you pick it for a slice and select that slice. Backups made with **Settings → Backup** do not include plugins, so a restored archive can never add runnable code.

## Folder layout

```text
~/.config/juhradial/plugins/
└── quick-note/
    ├── plugin.json
    └── save-clipboard.sh
```

The folder name is part of every action's address: an action is referred to as `<folder>/<action id>`, for example `quick-note/save-clipboard`. Folder names use letters, digits, `-`, `_` and `.`, and do not start with a dot.

## plugin.json

```json
{
  "schema": 1,
  "name": "Quick note",
  "version": "1.0.0",
  "description": "Append the clipboard to a notes file",
  "author": "You",
  "actions": [
    {
      "id": "save-clipboard",
      "label": "Clipboard to note",
      "icon": "document-save-symbolic",
      "script": "save-clipboard.sh",
      "args": ["Notes/inbox.md"]
    }
  ]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | no (default 1) | Manifest format. This release reads schema 1; a newer schema is reported, not guessed at. |
| `name` | yes | Shown in Settings and as the prefix in the action picker. |
| `version`, `description`, `author` | no | Shown in Settings → Plugins. |
| `actions` | yes | One or more actions (up to 64). |

Each action:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | 1 to 64 characters of `a-z`, `0-9`, `-`, `_`; unique within the plugin. |
| `label` | yes | The slice label when the action is picked. |
| `icon` | no | An icon name (`document-save-symbolic`), or a `.png`/`.svg` file in the plugin folder given as a relative path. |
| `description` | no | Free text for your own reference. |
| `exec` | one of three | A command line, run with `sh -c` (pipes, `$HOME`, `||` fallbacks work). |
| `dbus` | one of three | `{ "service", "path", "interface", "method", "args" }`, sent on the session bus. `args` may hold strings, booleans and numbers (whole numbers go as int32, others as double). |
| `script` | one of three | A file inside the plugin folder (relative path, no `..`, symlinks pointing outside are refused), started directly with the plugin folder as working directory. Make it executable (`chmod +x`). |
| `args` | no | Arguments for a `script` action. |

Unknown fields are an error, so a typo such as `"exce"` is reported instead of silently doing nothing.

## Examples

The repository ships two examples in `examples/plugins/`. Copy a folder into your plugins folder to try it:

```bash
mkdir -p ~/.config/juhradial/plugins
cp -r examples/plugins/quick-note ~/.config/juhradial/plugins/
```

**screenshot-tools** (two `exec` actions): a region capture to the clipboard and a full-screen capture saved to `~/Pictures`, using Spectacle on KDE and GNOME Screenshot elsewhere.

**quick-note** (a `script` and a `dbus` action): "Clipboard to note" appends the clipboard text to `~/Notes/inbox.md` with a timestamp; "Haptic tap" calls the JuhRadial daemon's `TriggerHapticPattern` over D-Bus for one confirmation pulse on an MX Master 4.

## For tools and scripts

The daemon exposes the same registry on its D-Bus interface (`org.kde.juhradialmx`, path `/org/kde/juhradialmx/Daemon`):

- `ListPlugins() → s`: JSON array of plugins with their actions (`ref`, `id`, `label`, `icon`, `kind` and its parameters) and `error` for folders that failed to load.
- `RunPluginAction(s ref) → b`: runs `<folder>/<id>`; false when it does not exist or could not start (the journal says why).

```bash
gdbus call --session --dest org.kde.juhradialmx --object-path /org/kde/juhradialmx/Daemon \
  --method org.kde.juhradialmx.Daemon.RunPluginAction quick-note/haptic-tap
```

## Current limits

Plugin actions can be bound to radial slices. Physical buttons, quick links and the keypad editor use the fixed action list in this release.
