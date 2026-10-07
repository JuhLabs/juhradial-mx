---
title: "Coming from logiops, Solaar or Logi Options+"
description: "Move from logiops (logid), Solaar or Logi Options+ to JuhRadial MX on Linux: where each setting lives, and why two tools should not divert the same buttons."
---

# Coming from logiops, Solaar or Logi Options+

## Run one tool at a time

JuhRadial MX, logiops and Solaar all tell the mouse to send certain buttons to the computer instead of handling them itself (HID++ calls this diverting). The setting lives in the mouse, so the last program to write it wins, and two of them running together take the buttons from each other.

Before the first start of JuhRadial MX, stop the other tool:

```bash
# logiops
sudo systemctl disable --now logid

# Solaar: quit it from its tray icon and remove it from your autostart apps
```

Solaar can stay installed for the things JuhRadial MX does not do, such as pairing a device with a receiver. Start it when you need it and quit it afterwards.

## From logiops

| In `logid.cfg` | In JuhRadial MX |
|---|---|
| `buttons` with a `cid` and an action | **Settings → Buttons**: click the button on the picture of the mouse. Every control the mouse reports is listed. |
| `Gestures` on the gesture button | **Settings → Buttons → Directional gestures**: up, down, left and right, with diagonals if you want them, and the plain press keeps its own action. |
| `Keypress` actions | A shortcut on a button, a ring slice or a keypad key. F13 to F24 can be used too. |
| `CycleDPI`, `ChangeDPI` | DPI steps on a button, and the presets in **Settings → Point & Scroll**. |
| `ToggleSmartShift`, `smartshift` | The wheel mode button and the SmartShift threshold in **Settings → Point & Scroll**. |
| `hiresscroll` | Hi-res and natural scrolling in **Settings → Point & Scroll**. |
| `thumbwheel` | The thumb wheel modes (horizontal scroll, volume, zoom) in **Settings → Point & Scroll**. |
| `ChangeHost` | Easy-Switch targets on a button or a slice, and **Settings → Easy-Switch**. |
| One config file per machine | `~/.config/juhradial/config.json`, written by Settings. **Backup** exports the whole setup as one zip. |

There is no importer for `logid.cfg`; the table is the map for doing it by hand, which takes a few minutes for a typical file.

## From Solaar

| In Solaar | In JuhRadial MX |
|---|---|
| Device settings (DPI, SmartShift, scroll) | **Settings → Point & Scroll**. They are applied again after a wake, a reconnect or a trip to another computer. |
| Key/Button Diversion and Rules | **Settings → Buttons** for what a button does, and **App profiles** for a different answer per application. |
| Rules that run a command or press keys | A command or shortcut action, or a macro for a sequence. |
| Change Host | **Settings → Easy-Switch**, or an Easy-Switch action on a button. |
| Battery in the tray | The tray tooltip, the Dashboard and a low-battery notice. |
| Pairing and unpairing | Not in JuhRadial MX: keep Solaar for that. |

## From Logi Options+ (dual boot or a new machine)

Nothing is read from a Logi Options+ account or backup. Settings that live in the mouse itself, such as the Easy-Switch pairings, come along with the mouse. [A Logi Options+ alternative for Linux](logi-options-plus-alternative.md) lists what each feature is called here.
