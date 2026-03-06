# JuhFlow - macOS Companion for JuhRadial MX

Cross-machine cursor flow between macOS and Linux with MX Master 4 Easy-Switch automation.

## What It Does

- **Edge detection**: Monitors cursor position at 120Hz, triggers handoff when cursor hits the configured screen edge
- **Velocity-based instant trigger**: Fast flicks (>3000 px/s) switch instantly, slow approaches use 100ms dwell
- **MX Master 4 Easy-Switch**: Automatically switches the mouse between Mac (BLE) and Linux (Bolt receiver) via Logi Options+ agent IPC
- **Bluetooth toggle**: Briefly disables Mac Bluetooth after Easy-Switch to prevent BLE auto-reconnection
- **Encrypted bridge**: X25519 + AES-256-GCM TCP connection to Linux JuhRadial MX
- **Clipboard sync**: Bidirectional clipboard transfer on switch
- **Flow indicator**: Glowing pill overlay on the screen edge showing handoff zone (PyObjC NSWindow)
- **UDP discovery**: Auto-discovers Linux peers on LAN

## Architecture

```
Mac (JuhFlow)                          Linux (JuhRadial MX)
─────────────                          ────────────────────
Edge Detector (120Hz Quartz)           Edge Detector
    ↓                                      ↓
Encrypted TCP Bridge  ←──────────→  Encrypted TCP Bridge
    ↓                                      ↓
Logi Agent IPC (Unix socket)         HID++ via Bolt receiver
    ↓                                      ↓
MX Master 4 Easy-Switch              MX Master 4 Easy-Switch
    ↓
BT toggle (blueutil)
```

## Files

| File | Purpose |
|------|---------|
| `juhflow_app.py` | Main app — edge detection, bridge client, Logi agent IPC, Easy-Switch |
| `juhflow_crypto.py` | X25519 + AES-256-GCM crypto (mirrors Linux `overlay/flow/crypto.py`) |
| `flow_indicator.py` | PyObjC overlay window — glowing pill on screen edge with breathing glow |
| `JuhFlowGUI.swift` | SwiftUI native GUI — power button, direction picker, channel picker, layout preview |
| `JuhFlow.app/` | Compiled .app bundle (macOS only) |
| `probe_logi.py` | Debug tool — queries Logi Options+ agent routes and endpoints |
| `probe_settings.py` | Debug tool — queries sensitivity/scroll settings from agent |

## Logi Options+ Agent IPC Protocol (Reverse-Engineered)

### Connection
- Unix socket: `/tmp/logitech_kiros_agent-{hash}` (glob: `/tmp/logitech_kiros_agent-*`)

### Frame Format (Send)
```
[4 bytes LE: total_size = proto_name_len + payload_len + 8]
[4 bytes BE: proto_name_len]
[proto_name bytes: "json"]
[4 bytes BE: payload_len]
[payload bytes: JSON UTF-8]
```

### Frame Format (Receive)
State machine: START(4B skip) -> PROTO_HEADER(4B BE len) -> PROTO_PAYLOAD(name) -> MSG_HEADER(4B BE len) -> PAYLOAD(data)

### JSON Message Format
```json
{
  "msgId": "string",
  "verb": "get|set|subscribe|broadcast|remove|options",
  "path": "/path/to/resource",
  "payload": { "@type": "type.googleapis.com/...", ...fields... }
}
```

### Key Endpoints

**Easy-Switch Channel Switch (CONFIRMED WORKING)**
```
SET /change_host/{deviceId}/host
payload: {
  "@type": "type.googleapis.com/logi.protocol.devices.ChangeHost",
  "host": 0  // 0-based host index (channel 1 = index 0)
}
```
IMPORTANT: Field is `"host"` (0-based), NOT `"hostIndex"`. The `@type` must be `devices.ChangeHost`.

**List Devices**
```
GET /devices/list
-> payload.deviceInfos[]: { id, pid, displayName, connectionType, state, ... }
```

**Get Easy-Switch Hosts**
```
GET /devices/{deviceId}/easy_switch
-> payload.hosts[]: { index, paired, connected, busType, name, os }
```

**Get All Routes**
```
GET /routes
-> payload.route[]: { verb, path, payload, exampleJson, endpoint }
```

**Sensitivity/Scroll Endpoints (device must be ACTIVE — routes register dynamically)**
```
GET/SET /mouse/{deviceId}/pointer_speed
GET/SET /smartshift/{deviceId}/params     — { isEnabled, sensitivity, mode, isScrollForceEnabled, scrollForce }
GET/SET /scrollwheel/{deviceId}/params    — { speed, dir: "NATURAL"|"STANDARD", isSmooth }
GET/SET /thumbwheel/{deviceId}/params     — { speed, dir, isSmooth }
```

### Device IDs
- MX Master 4: `dev00000000` (PID: 0xB042, BLE)
- MX Keys S: `dev00000001` (PID: 0xB378, BLE)

## Channel Mapping (Julian's Setup)
- Channel 1 (host index 0): Linux/JuhLabs via BLEPRO (Bolt receiver)
- Channel 2 (host index 1): MacBook M4 via BLE
- Channel 3 (host index 2): Samsung phone via BLE

## Building the SwiftUI GUI (macOS only)

```bash
swiftc -parse-as-library -framework SwiftUI -framework AppKit -o JuhFlowGUI JuhFlowGUI.swift

# Create .app bundle
mkdir -p JuhFlow.app/Contents/MacOS
cp JuhFlowGUI JuhFlow.app/Contents/MacOS/
# Info.plist goes in JuhFlow.app/Contents/
```

## Python Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install cryptography pyobjc-framework-Quartz pyobjc-framework-Cocoa
```

Also needs `blueutil` (Homebrew): `brew install blueutil`

## Running

```bash
# Via GUI (no terminal window)
open JuhFlow.app

# Via CLI
.venv/bin/python3 juhflow_app.py --ip 192.168.68.74 --cli --direction left --mac-channel 2 --linux-channel 1
```

## Key Design Decisions

1. **BT toggle after Easy-Switch**: The Logi agent sends the HID++ ChangeHost command successfully, but Mac's BLE stack auto-reconnects the device before it can switch to the Bolt receiver. Toggling BT off for 1.5s via `blueutil --power 0/1` breaks the connection cleanly.

2. **NSApplication event loop in CLI mode**: Required for the PyObjC overlay indicator window to display. The main thread runs `NSApp.run()` with `NSApplicationActivationPolicyAccessory` (no dock icon), all JuhFlow logic runs in background threads.

3. **`performSelectorOnMainThread`**: Used to dispatch overlay window show/hide from background threads to the main thread (required by AppKit).

4. **Edge detector `active` flag**: Prevents edge detection while cursor is on Linux. Set to `False` on outgoing edge hit, `True` on incoming edge hit from Linux.

5. **Velocity instant trigger**: Cursor hitting the edge at >3000 px/s skips the 100ms dwell timer entirely for near-instant switching. Matches the Linux side.

6. **TCP_NODELAY**: Set on the bridge socket to minimize latency for edge hit messages.

7. **Arrival edge = linux_direction**: When cursor returns from Linux, it lands on the same edge Linux is on (e.g., Linux on left → cursor arrives on left edge of Mac).

## Flow Indicator (flow_indicator.py)

The overlay is a transparent NSWindow with:
- 3px blue pill (#4696FF) flush against the screen edge
- 4-layer tight aura glow (max 10px spread, up to 55% alpha)
- Dark stroke outline (0.8px, 40% black) for contrast on any background
- Penguin emoji icon above the pill
- Subtle opacity oscillation (70%–100%) via NSTimer at 30fps
- Click-through (`ignoresMouseEvents`), always on top, no shadow, no dock icon
- Shows when bridge connects, hides when disconnected
