.pragma library

// Key chords as the daemon presses them: "+"-joined X keysym names with the
// modifiers first ("ctrl+shift+Page_Up"), the spelling actions.rs maps to
// evdev codes for uinput and passes to xdotool on X11.

var MODS = ["ctrl", "alt", "shift", "super"]

// Keys a keyboard often lacks or the desktop grabs before the recorder sees
// them (Print opens the screenshot tool on most desktops).
var EXTRA_KEYS = ["F13", "F14", "F15", "F16", "F17", "F18", "F19", "F20", "F21", "F22",
                  "F23", "F24", "Print", "Insert", "Pause", "Menu", "Page_Up", "Page_Down",
                  "Home", "End", "XF86AudioPlay", "XF86AudioNext", "XF86AudioPrev",
                  "XF86AudioMute", "XF86AudioRaiseVolume", "XF86AudioLowerVolume"]

// evdev code -> key name, for keys whose Qt key depends on Shift and the
// layout (Shift+1 arrives as "!"): name the physical key instead.
var BY_EVDEV = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    12: "minus", 13: "equal", 26: "bracketleft", 27: "bracketright", 39: "semicolon",
    40: "apostrophe", 41: "grave", 43: "backslash", 51: "comma", 52: "period", 53: "slash"
}

var _named = null
function _namedKeys() {
    if (_named)
        return _named
    var m = {}
    m[Qt.Key_PageUp] = "Page_Up"; m[Qt.Key_PageDown] = "Page_Down"
    m[Qt.Key_Home] = "Home"; m[Qt.Key_End] = "End"; m[Qt.Key_Insert] = "Insert"
    m[Qt.Key_Delete] = "Delete"; m[Qt.Key_Print] = "Print"; m[Qt.Key_Pause] = "Pause"
    m[Qt.Key_Tab] = "Tab"; m[Qt.Key_Backtab] = "Tab"; m[Qt.Key_Return] = "Return"
    m[Qt.Key_Enter] = "Return"; m[Qt.Key_Space] = "space"; m[Qt.Key_Backspace] = "BackSpace"
    m[Qt.Key_Escape] = "Escape"; m[Qt.Key_Left] = "Left"; m[Qt.Key_Right] = "Right"
    m[Qt.Key_Up] = "Up"; m[Qt.Key_Down] = "Down"; m[Qt.Key_Menu] = "Menu"
    m[Qt.Key_VolumeUp] = "XF86AudioRaiseVolume"; m[Qt.Key_VolumeDown] = "XF86AudioLowerVolume"
    m[Qt.Key_VolumeMute] = "XF86AudioMute"; m[Qt.Key_MediaPlay] = "XF86AudioPlay"
    m[Qt.Key_MediaTogglePlayPause] = "XF86AudioPlay"; m[Qt.Key_MediaNext] = "XF86AudioNext"
    m[Qt.Key_MediaPrevious] = "XF86AudioPrev"
    m[Qt.Key_Comma] = "comma"; m[Qt.Key_Period] = "period"; m[Qt.Key_Slash] = "slash"
    m[Qt.Key_Semicolon] = "semicolon"; m[Qt.Key_Apostrophe] = "apostrophe"
    m[Qt.Key_BracketLeft] = "bracketleft"; m[Qt.Key_BracketRight] = "bracketright"
    m[Qt.Key_Backslash] = "backslash"; m[Qt.Key_QuoteLeft] = "grave"
    m[Qt.Key_Minus] = "minus"; m[Qt.Key_Equal] = "equal"
    _named = m
    return m
}

function isModifierKey(key) {
    return key === Qt.Key_Control || key === Qt.Key_Shift || key === Qt.Key_Alt
        || key === Qt.Key_Meta || key === Qt.Key_Super_L || key === Qt.Key_Super_R
        || key === Qt.Key_AltGr
}

// Held modifiers of a key event, in chord order.
function modsOf(modifiers) {
    var out = []
    if (modifiers & Qt.ControlModifier) out.push("ctrl")
    if (modifiers & Qt.AltModifier) out.push("alt")
    if (modifiers & Qt.ShiftModifier) out.push("shift")
    if (modifiers & Qt.MetaModifier) out.push("super")
    return out
}

// The key name for a Qt key event ("" = not a key the daemon can press).
function keyName(key, nativeScanCode) {
    if (key >= Qt.Key_A && key <= Qt.Key_Z)
        return String.fromCharCode(key).toLowerCase()
    if (key >= Qt.Key_0 && key <= Qt.Key_9)
        return String.fromCharCode(key)
    if (key >= Qt.Key_F1 && key <= Qt.Key_F24)
        return "F" + (key - Qt.Key_F1 + 1)
    var named = _namedKeys()[key]
    if (named)
        return named
    // xkb keycodes are evdev codes + 8 on X11 and Wayland alike.
    return BY_EVDEV[nativeScanCode - 8] || ""
}

function join(mods, key) {
    var ordered = MODS.filter(function (m) { return mods.indexOf(m) >= 0 })
    return key ? ordered.concat([key]).join("+") : ""
}

// {mods: [...], key: "..."} of a chord.
function split(chord) {
    var parts = (chord || "").split("+").filter(function (p) { return p !== "" })
    var mods = [], key = ""
    for (var i = 0; i < parts.length; i++) {
        var low = parts[i].toLowerCase()
        if (low === "control") low = "ctrl"
        if (low === "meta" || low === "win") low = "super"
        if (MODS.indexOf(low) >= 0) mods.push(low)
        else key = parts[i]
    }
    return { mods: mods, key: key }
}

function prettyKey(name) {
    var pretty = {
        ctrl: "Ctrl", alt: "Alt", shift: "Shift", super: "Super",
        Page_Up: "PgUp", Page_Down: "PgDn", BackSpace: "Backspace", Return: "Enter",
        space: "Space", Print: "Print Screen", Escape: "Esc",
        comma: ",", period: ".", slash: "/", semicolon: ";", apostrophe: "'",
        bracketleft: "[", bracketright: "]", backslash: "\\", grave: "`", minus: "-",
        equal: "=", plus: "+", Left: "←", Right: "→", Up: "↑", Down: "↓",
        KP_Add: "Num +", KP_Subtract: "Num -",
        XF86AudioPlay: "Play/Pause", XF86AudioNext: "Next Track", XF86AudioPrev: "Previous Track",
        XF86AudioMute: "Mute", XF86AudioRaiseVolume: "Volume Up", XF86AudioLowerVolume: "Volume Down"
    }
    if (pretty[name]) return pretty[name]
    if (/^[a-z]$/.test(name)) return name.toUpperCase()
    return name
}

// "ctrl+shift+Page_Up" -> "Ctrl + Shift + PgUp"
function pretty(chord) {
    var parts = (chord || "").split("+").filter(function (p) { return p !== "" })
    return parts.map(prettyKey).join(" + ")
}
