import QtQuick
import QtQuick.Layouts
import "../components"

// Devices: what is connected to this computer and how it is doing (link,
// battery), the MX Keys S (found even before its support is on; backlight
// mode, level and stay-on time read back from the keyboard), battery alerts,
// About this mouse (unit id, firmware, features, its own settings) and the
// Advanced generic-mode switch behind a confirmation.
Item {
    id: page
    anchors.fill: parent

    readonly property string _ic: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/"
    property int bump: 0
    function cfg(path, def) { page.bump; return Backend.get(path, def) }

    // ---- live state ----
    readonly property bool service: Backend.daemonAvailable
    readonly property bool primed: Backend.primed || !service
    readonly property string link: Backend.linkState
    readonly property bool reachable: service && link === "connected"
    readonly property string via: ({ bolt: qsTr("Bolt receiver"), unifying: qsTr("Unifying receiver"),
                                     bluetooth: qsTr("Bluetooth"), usb: qsTr("USB cable") })[Backend.transport] || ""
    readonly property string linkText: {
        if (!service) return qsTr("Service not running")
        switch (link) {
        case "connected": return via ? qsTr("Connected via %1").arg(via) : qsTr("Connected")
        case "asleep": return qsTr("Asleep. Move it to wake it")
        case "away": return qsTr("On another computer")
        default: return qsTr("Not found")
        }
    }
    function batteryWord(pct, charging) {
        if (charging) return qsTr("Charging")
        if (pct >= 100) return qsTr("Full")
        var sev = Theme.batterySeverity(pct, charging)
        if (sev === "low" || sev === "critical") return qsTr("Low")
        return qsTr("Battery")
    }

    // ---- keyboard (async: a receiver probe can take seconds) ----
    property var kb: ({ present: false, enabled: Backend.get("keyboard.mx_keys.enabled", false),
                        battery: 0, charging: false, sleeping: false, pending: true,
                        lastBattery: 0, backlight: { ok: false } })
    readonly property var bl: kb.backlight || { ok: false }
    function reloadKeyboard() { kb = Object.assign({}, kb, { pending: true }); Backend.requestKeyboardInfo() }
    // The daemon needs a moment to reload config and reach the keyboard
    // after the support switch flips.
    Timer { id: kbReload; interval: 1200; onTriggered: page.reloadKeyboard() }

    // ---- refresh ----
    property bool refreshing: false
    property real now: Date.now() / 1000
    Timer { interval: 20000; repeat: true; running: page.visible; onTriggered: page.now = Date.now() / 1000 }
    Timer { id: refreshGiveUp; interval: 5000; onTriggered: page.refreshing = false }
    readonly property string updatedText: {
        var at = Backend.refreshedAt
        if (!service) return qsTr("The background service is not running")
        if (refreshing || at <= 0) return qsTr("Reading the devices…")
        var ago = Math.max(0, page.now - at)
        if (ago < 60) return qsTr("Updated just now")
        return qsTr("Updated %n minute(s) ago", "", Math.floor(ago / 60))
    }
    function refresh() {
        refreshing = true
        refreshGiveUp.restart()
        now = Date.now() / 1000
        Backend.refreshDevices()
        reloadKeyboard()
    }

    // ---- battery alerts ----
    readonly property int alertLevel: cfg("battery.alert_percent", 15)

    // ---- generic mode confirm, overrides review ----
    readonly property bool forcedGeneric: (bump, Backend.get("device_mode", "auto") === "generic")
    property bool askGeneric: false
    property bool showOverrides: false
    property bool askResetOverrides: false
    readonly property var overrides: (bump, Backend.unitId, Backend.deviceOverrides())

    Component.onCompleted: reloadKeyboard()
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
        function onKeyboardInfoReady(info) { page.kb = info }
        function onLiveChanged() {
            if (page.refreshing && Backend.refreshedAt >= page.now - 1) page.refreshing = false
            page.now = Date.now() / 1000
        }
    }

    component Divider: Rectangle { width: parent ? parent.width : 400; height: 1; color: Theme.border }

    // Battery glyph on the app's one severity scale.
    component BatteryGlyph: Item {
        id: bg
        property int percent: 0
        property bool charging: false
        property bool stale: false
        readonly property color tint: stale ? Theme.textMuted : Theme.batteryColor(percent, charging)
        width: 30; height: 15
        Rectangle {
            id: body
            width: 27; height: 15; radius: 4
            color: "transparent"; border.width: 1.5; border.color: bg.tint
            Rectangle {
                x: 3; y: 3; height: parent.height - 6; radius: 2
                width: Math.max(bg.percent > 0 ? 2 : 0, (parent.width - 6) * Math.min(100, bg.percent) / 100)
                color: bg.tint
                Behavior on width { NumberAnimation { duration: Theme.dMed; easing.type: Easing.OutCubic } }
            }
        }
        Rectangle { x: 28; y: 5; width: 2.5; height: 5; radius: 1; color: bg.tint }
    }

    // Right-aligned battery readout: glyph, percent, word.
    component BatteryReadout: Row {
        id: br
        property int percent: 0
        property bool charging: false
        property bool stale: false
        property string word: ""
        spacing: 10
        BatteryGlyph {
            anchors.verticalCenter: parent.verticalCenter
            percent: br.percent; charging: br.charging; stale: br.stale
        }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 1
            Text {
                text: br.percent > 0 ? br.percent + "%" : "--"
                color: br.stale ? Theme.textMuted : Theme.textPrimary
                font.family: Theme.fontMono; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
            }
            Text {
                text: br.word; color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
            }
        }
    }

    // Muted label, value, optional trailing control.
    component InfoRow: Item {
        id: ir
        property string label: ""
        property string value: ""
        property bool mono: true
        default property alias trailing: irSlot.data
        width: parent ? parent.width : 0
        height: Math.max(40, irValue.implicitHeight + 16)
        Accessible.role: Accessible.StaticText
        Accessible.name: label + ": " + value
        Text {
            id: irLabel
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            width: 170
            text: ir.label; color: Theme.textMuted
            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
        }
        Text {
            id: irValue
            anchors.left: irLabel.right; anchors.right: irSlot.left; anchors.rightMargin: Theme.gapS
            anchors.verticalCenter: parent.verticalCenter
            text: ir.value; color: Theme.textPrimary; wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignRight
            font.family: ir.mono ? Theme.fontMono : Theme.fontUI
            font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
        }
        Row {
            id: irSlot
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            spacing: 4
        }
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ---- service down ----
            EmptyState {
                visible: !page.service
                Layout.fillWidth: true
                title: qsTr("The JuhRadial service is not running")
                body: qsTr("Devices, battery and the keyboard are read through the background service. Start it, then this page fills in by itself.")
                Row {
                    spacing: Theme.gapS
                    PrimaryButton { text: qsTr("Start the service"); onClicked: Backend.restartDaemon() }
                    PrimaryButton { text: qsTr("Check again"); ghost: true; onClicked: page.refresh() }
                }
            }

            // ---- generic banner ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: genRow.implicitHeight + Theme.padCard * 2
                visible: Backend.isGeneric
                RowLayout {
                    id: genRow
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    ActionIcon { iconName: "dialog-information-symbolic"; tint: Theme.textMuted; px: 20 }
                    Text {
                        Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: page.forcedGeneric
                              ? qsTr("Generic mouse mode is on, so Logitech features are hidden.")
                              : qsTr("This mouse is not a supported Logitech model, so it runs as a standard mouse.")
                        color: Theme.textBody
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
                    }
                    PrimaryButton {
                        visible: page.forcedGeneric
                        text: qsTr("Return to automatic detection"); ghost: true
                        onClicked: Backend.setDeviceMode("auto")
                    }
                }
            }

            // ---- connected devices ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: rosterCol.implicitHeight + Theme.padCard * 2
                visible: page.service
                Column {
                    id: rosterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Connected devices")
                        subtitle: page.updatedText
                        icon: page._ic + "devices"
                        IconButton {
                            icon: "view-refresh-symbolic"; tint: Theme.textMuted; diameter: 32
                            tip: qsTr("Read the devices again")
                            Accessible.name: qsTr("Read the devices again")
                            onClicked: page.refresh()
                            RotationAnimator on rotation {
                                from: 0; to: 360; duration: 900; loops: Animation.Infinite
                                running: page.refreshing
                                onRunningChanged: if (!running) parent.rotation = 0
                            }
                        }
                    }
                    Divider {}

                    // loading
                    Row {
                        visible: !page.primed
                        spacing: Theme.gapL
                        height: 84
                        Skeleton { width: 104; height: 64; anchors.verticalCenter: parent.verticalCenter }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 8
                            Skeleton { width: 220; height: 22 }
                            Skeleton { width: 300; height: 16 }
                        }
                    }

                    // mouse
                    Item {
                        id: mouseRow
                        visible: page.primed
                        width: parent.width; height: mouseCol.implicitHeight + 12
                        activeFocusOnTab: true
                        Accessible.role: Accessible.ListItem
                        Accessible.name: (Backend.deviceName || qsTr("No mouse yet")) + ". " + page.linkText
                                         + (Backend.battery > 0 ? ". " + qsTr("Battery %1%").arg(Backend.battery) : "")
                        FocusHalo { active: mouseRow.activeFocus; radius: Theme.radiusCtl }
                        Column {
                            id: mouseCol
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.gapS
                            RowLayout {
                                width: parent.width
                                spacing: Theme.gapL
                                Item {
                                    Layout.preferredWidth: 104; Layout.preferredHeight: 70
                                    opacity: page.reachable ? 1 : 0.45
                                    Behavior on opacity { NumberAnimation { duration: Theme.dMed } }
                                    Image {
                                        anchors.centerIn: parent
                                        readonly property bool mx3: Backend.deviceName.indexOf("MX Master 3") >= 0
                                        source: assetsDir + (mx3 ? "/devices/mx3_quarter.png" : "/devices/mx4_side.png")
                                        sourceSize.width: mx3 ? 549 : 1289; sourceSize.height: mx3 ? 804 : 829
                                        width: mx3 ? 48 : 104; height: mx3 ? 70 : 67
                                        fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 6
                                    Text {
                                        text: Backend.deviceName || qsTr("No mouse yet"); color: Theme.textPrimary
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                                        Layout.fillWidth: true; elide: Text.ElideRight
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: Theme.gapS
                                        Badge { text: page.linkText; dot: true; accent: page.reachable }
                                        Badge {
                                            visible: !Backend.isGeneric && Backend.hostsKnown
                                            text: qsTr("Computer %1 of %2").arg(Backend.currentHost + 1).arg(Backend.numHosts)
                                        }
                                        Badge { visible: Backend.activeProfile !== ""; text: qsTr("Profile: %1").arg(Backend.activeProfile) }
                                    }
                                }
                                BatteryReadout {
                                    Layout.alignment: Qt.AlignVCenter
                                    visible: !Backend.isGeneric
                                    // Asleep or away: the last reading, marked as such.
                                    stale: !page.reachable
                                    percent: Backend.battery; charging: Backend.charging && page.reachable
                                    word: page.reachable ? page.batteryWord(Backend.battery, Backend.charging) : qsTr("Last reading")
                                }
                            }
                            // Where to set this mouse up.
                            Flow {
                                visible: !Backend.isGeneric
                                width: parent.width
                                spacing: Theme.gapS
                                leftPadding: 104 + Theme.gapL
                                PrimaryButton { text: qsTr("Buttons"); ghost: true; onClicked: Backend.goTo("buttons") }
                                PrimaryButton { text: qsTr("Point & Scroll"); ghost: true; onClicked: Backend.goTo("scroll") }
                                PrimaryButton {
                                    visible: Backend.hapticsSupported
                                    text: qsTr("Haptics"); ghost: true
                                    onClicked: Backend.goTo("haptics")
                                }
                            }
                        }
                    }

                    // keyboard
                    Divider { visible: page.primed && (page.kb.present || page.kb.enabled) }
                    Item {
                        id: kbRow
                        visible: page.primed && (page.kb.present || page.kb.enabled)
                        width: parent.width; height: kbRowLay.implicitHeight + 12
                        activeFocusOnTab: true
                        readonly property bool awake: page.kb.present && page.kb.enabled && !page.kb.sleeping && !page.kb.pending
                        readonly property string state: {
                            if (page.kb.pending) return qsTr("Checking…")
                            if (!page.kb.enabled) return qsTr("Found. Turn on its support to see its battery and backlight")
                            if (!page.kb.present) return qsTr("Not found. Connect it with its Bolt or Unifying receiver")
                            if (page.kb.sleeping) return qsTr("Asleep. Press any key to wake it")
                            return qsTr("Awake")
                        }
                        Accessible.role: Accessible.ListItem
                        Accessible.name: qsTr("MX Keys S") + ". " + state
                        FocusHalo { active: kbRow.activeFocus; radius: Theme.radiusCtl }
                        RowLayout {
                            id: kbRowLay
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.gapL
                            Item {
                                Layout.preferredWidth: 104; Layout.preferredHeight: 56
                                Image {
                                    anchors.centerIn: parent
                                    source: assetsDir + "/devices/mx_keys_s.png"
                                    sourceSize.width: 208; sourceSize.height: 82
                                    width: 104; height: 41
                                    fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true
                                    opacity: kbRow.awake ? 1 : 0.45
                                    Behavior on opacity { NumberAnimation { duration: Theme.dMed } }
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 6
                                Text {
                                    text: qsTr("MX Keys S")
                                    color: page.kb.present ? Theme.textPrimary : Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                                }
                                Flow {
                                    Layout.fillWidth: true
                                    spacing: Theme.gapS
                                    Badge { text: kbRow.state; dot: true; accent: kbRow.awake }
                                    Badge { text: qsTr("Beta") }
                                }
                            }
                            PrimaryButton {
                                visible: !page.kb.pending && !page.kb.enabled && page.kb.present
                                text: qsTr("Turn on")
                                onClicked: { Backend.set("keyboard.mx_keys.enabled", true); kbReload.restart() }
                            }
                            PrimaryButton {
                                visible: !page.kb.pending && page.kb.enabled && (page.kb.sleeping || !page.kb.present)
                                text: qsTr("Check again"); ghost: true
                                onClicked: page.reloadKeyboard()
                            }
                            BatteryReadout {
                                Layout.alignment: Qt.AlignVCenter
                                visible: page.kb.enabled && page.kb.present && !page.kb.pending
                                readonly property bool stale: page.kb.sleeping
                                percent: page.kb.sleeping ? (page.kb.lastBattery || 0) : page.kb.battery
                                charging: page.kb.charging && !page.kb.sleeping
                                word: page.kb.sleeping ? ((page.kb.lastBattery || 0) > 0 ? qsTr("Last reading") : qsTr("Asleep"))
                                                       : page.batteryWord(page.kb.battery, page.kb.charging)
                            }
                        }
                    }
                }
            }

            // ---- keyboard settings ----
            GlassCard {
                id: kbCard
                Layout.fillWidth: true
                Layout.preferredHeight: kbCol.implicitHeight + Theme.padCard * 2
                visible: page.service && page.primed
                Column {
                    id: kbCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Keyboard")
                        subtitle: qsTr("Logitech MX Keys S over its receiver")
                        icon: page._ic + "keyboard"
                        Badge { text: qsTr("Beta") }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("MX Keys S support")
                        desc: qsTr("Battery, backlight and moving with the mouse between computers")
                        Toggle {
                            accessibleName: qsTr("MX Keys S support")
                            checked: page.kb.enabled
                            onToggled: (v) => { Backend.set("keyboard.mx_keys.enabled", v); kbReload.restart() }
                        }
                    }
                    // Backlight read back from the keyboard.
                    Divider { visible: page.kb.enabled && page.bl.ok }
                    SettingRow {
                        visible: page.kb.enabled && page.bl.ok && page.bl.autoSupported
                        label: qsTr("Backlight")
                        desc: page.bl.mode === 3
                              ? qsTr("Manual: the brightness below stays as you set it")
                              : page.bl.mode === 2 ? qsTr("Set with the keyboard's brightness keys; the light sensor takes over again later")
                                                   : qsTr("Automatic: the light sensor sets the brightness")
                        SegmentedControl {
                            width: 220
                            accessibleName: qsTr("Backlight")
                            model: [{ id: "auto", name: qsTr("Automatic") }, { id: "manual", name: qsTr("Manual") }]
                            currentId: page.bl.mode === 3 ? "manual" : "auto"
                            onActivated: (id) => Backend.setKeyboardBacklightAuto(id === "auto")
                        }
                    }
                    Divider { visible: page.kb.enabled && page.bl.ok && page.bl.autoSupported }
                    SettingRow {
                        visible: page.kb.enabled && page.bl.ok
                        label: qsTr("Brightness")
                        desc: page.bl.mode === 3 || !page.bl.autoSupported
                              ? qsTr("Level %1 of %2. 0 turns the backlight off").arg(page.bl.level).arg(page.bl.levels - 1)
                              : qsTr("Lit at level %1 of %2 right now. Moving the slider switches to Manual").arg(page.bl.level).arg(page.bl.levels - 1)
                        Slider {
                            width: 220
                            from: 0; to: Math.max(1, (page.bl.levels || 8) - 1); stepSize: 1
                            showValue: true
                            accessibleName: qsTr("Backlight brightness")
                            value: page.bl.level || 0
                            onCommitted: (v) => Backend.setKeyboardBacklight(Math.round(v * 100 / Math.max(1, page.bl.levels - 1)))
                        }
                    }
                    Divider { visible: page.kb.enabled && page.bl.ok }
                    SettingRow {
                        visible: page.kb.enabled && page.bl.ok
                        label: qsTr("Stay on for")
                        desc: qsTr("After your hands leave the keys")
                        ComboBox {
                            width: 180
                            accessibleName: qsTr("Backlight stays on for")
                            model: Backend.backlightDurations(page.bl.away || 0)
                            currentId: String(page.bl.away || 0)
                            onActivated2: (id) => Backend.setKeyboardBacklightDuration(parseInt(id), 0)
                        }
                    }
                    Divider { visible: page.kb.enabled && page.bl.ok }
                    SettingRow {
                        visible: page.kb.enabled && page.bl.ok
                        label: qsTr("On a cable, stay on for")
                        desc: qsTr("While the keyboard charges over USB")
                        ComboBox {
                            width: 180
                            accessibleName: qsTr("Backlight stays on while charging for")
                            model: Backend.backlightDurations(page.bl.powered || 0)
                            currentId: String(page.bl.powered || 0)
                            onActivated2: (id) => Backend.setKeyboardBacklightDuration(0, parseInt(id))
                        }
                    }
                    // Not readable: say why and how to fix it.
                    Text {
                        visible: page.kb.enabled && !page.kb.pending && !page.bl.ok
                        width: parent.width; wrapMode: Text.WordWrap
                        text: !page.kb.present
                              ? qsTr("No MX Keys S found. Pair it with a Bolt or Unifying receiver on this computer; a keyboard on Bluetooth only is not supported yet.")
                              : qsTr("The keyboard is asleep. Press any key, then Check again above to read its backlight.")
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                }
            }

            // ---- battery alerts ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: alCol.implicitHeight + Theme.padCard * 2
                visible: page.service && !Backend.isGeneric
                Column {
                    id: alCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Battery alerts")
                        subtitle: qsTr("One notification per charge, and the tray icon turns red")
                        icon: page._ic + "battery-low-symbolic"
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Warn me at")
                        desc: qsTr("When a device on battery drops to this level")
                        SegmentedControl {
                            width: 200
                            accessibleName: qsTr("Warn me at")
                            model: [{ id: "10", name: "10 %" }, { id: "15", name: "15 %" }, { id: "20", name: "20 %" }]
                            currentId: String(page.alertLevel)
                            onActivated: (id) => Backend.set("battery.alert_percent", parseInt(id))
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Mouse")
                        desc: Backend.deviceName || qsTr("No mouse yet")
                        Toggle {
                            accessibleName: qsTr("Battery alert for the mouse")
                            checked: page.cfg("battery.alert_mouse", true)
                            onToggled: (v) => Backend.set("battery.alert_mouse", v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Keyboard")
                        desc: page.kb.enabled ? qsTr("Checked each time the keyboard wakes up")
                                              : qsTr("Turn on MX Keys S support first")
                        Toggle {
                            accessibleName: qsTr("Battery alert for the keyboard")
                            enabled: page.kb.enabled
                            checked: page.cfg("battery.alert_keyboard", true)
                            onToggled: (v) => Backend.set("battery.alert_keyboard", v)
                        }
                    }
                }
            }

            // ---- USB receivers ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: rxCol.implicitHeight + Theme.padCard * 2
                visible: page.service && !Backend.isGeneric
                Component.onCompleted: Backend.refreshReceivers()
                Column {
                    id: rxCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Receivers")
                        subtitle: qsTr("What each Logitech USB receiver has paired, read from the receiver itself")
                        icon: page._ic + "network-wireless-symbolic"
                        PrimaryButton { text: qsTr("Check again"); ghost: true; onClicked: Backend.refreshReceivers() }
                    }
                    Text {
                        visible: !!Backend.receivers && Backend.receivers.length === 0
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("No Bolt or Unifying receiver is plugged in. Devices on Bluetooth pair through your desktop's Bluetooth settings.")
                        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    Repeater {
                        model: Backend.receivers || []
                        Column {
                            id: rx
                            required property var modelData
                            required property int index
                            width: rxCol.width; spacing: 2
                            Divider {}
                            Text {
                                topPadding: Theme.gapS
                                text: (rx.modelData.kind === "bolt" ? qsTr("Logi Bolt receiver %1") : qsTr("Unifying receiver %1")).arg(rx.index + 1)
                                color: Theme.textPrimary
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                            }
                            Text {
                                visible: rx.modelData.devices.length === 0
                                text: qsTr("Nothing paired, or the receiver did not answer")
                                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                            Repeater {
                                model: rx.modelData.devices
                                InfoRow {
                                    required property var modelData
                                    mono: false
                                    label: qsTr("Slot %1").arg(modelData.slot)
                                    value: (modelData.name || modelData.kind) + "  " + modelData.wpid
                                    Badge {
                                        visible: modelData.role !== ""
                                        text: modelData.role === "mouse" ? qsTr("This mouse") : qsTr("This keyboard")
                                        accent: true
                                    }
                                }
                            }
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("Pairing and unpairing stay with Logi Options+ or Solaar: JuhRadial only reads the receivers.")
                        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                    }
                }
            }

            // ---- about this mouse ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: abCol.implicitHeight + Theme.padCard * 2
                visible: page.service && page.primed
                Column {
                    id: abCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: 0
                    CardHeader {
                        width: parent.width
                        title: qsTr("About this mouse")
                        subtitle: qsTr("What to include when you report a problem")
                        icon: page._ic + "help-about-symbolic"
                        PrimaryButton { text: qsTr("Copy diagnostics"); ghost: true; onClicked: Backend.copyDiagnostics() }
                    }
                    Item { width: 1; height: Theme.gapS }
                    Divider {}
                    InfoRow { label: qsTr("Model"); value: Backend.deviceName || qsTr("No mouse yet"); mono: false }
                    Divider {}
                    InfoRow { label: qsTr("Connection"); value: page.linkText; mono: false }
                    Divider { visible: Backend.unitId !== "" }
                    InfoRow {
                        visible: Backend.unitId !== ""
                        label: qsTr("Unit ID"); value: Backend.unitId
                        IconButton {
                            icon: "edit-copy-symbolic"; tint: Theme.textMuted; diameter: 30
                            tip: qsTr("Copy the unit ID")
                            Accessible.name: qsTr("Copy the unit ID")
                            onClicked: Backend.copyText(Backend.unitId, qsTr("Unit ID"))
                        }
                    }
                    Divider { visible: Backend.firmware.length > 0 }
                    InfoRow {
                        visible: Backend.firmware.length > 0
                        label: qsTr("Firmware"); value: Backend.firmware.join("\n")
                    }
                    Divider {}
                    InfoRow { label: qsTr("JuhRadial service"); value: Backend.daemonVersion }
                    Divider {}
                    InfoRow { label: qsTr("This app"); value: Backend.appVersion }
                    Divider {}
                    Item {
                        width: parent.width
                        height: capFlow.implicitHeight + 24
                        Text {
                            id: capLabel
                            anchors.left: parent.left; anchors.top: parent.top; anchors.topMargin: 12
                            width: 170
                            text: qsTr("Features"); color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                        }
                        Flow {
                            id: capFlow
                            anchors.left: capLabel.right; anchors.right: parent.right
                            anchors.top: parent.top; anchors.topMargin: 12
                            spacing: Theme.gapS
                            Repeater {
                                // Only what the mouse itself reported (GetCapabilities).
                                model: [{ k: "dpi", n: qsTr("DPI") }, { k: "smartshift", n: qsTr("SmartShift") },
                                        { k: "hires_wheel", n: qsTr("Hi-res scroll") }, { k: "thumbwheel", n: qsTr("Thumb wheel") },
                                        { k: "haptics", n: qsTr("Haptics") }, { k: "force_sense", n: qsTr("Sense Panel") },
                                        { k: "easy_switch", n: qsTr("Easy-Switch") }, { k: "gesture_button", n: qsTr("Gesture button") }]
                                Badge {
                                    required property var modelData
                                    visible: !!Backend.caps[modelData.k]
                                    text: modelData.n; dot: true; accent: true
                                }
                            }
                            Text {
                                visible: Object.keys(Backend.caps).length === 0
                                text: qsTr("Not reported yet"); color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                        }
                    }
                    // Settings kept only for this mouse (Buttons > This mouse only).
                    Divider { visible: Backend.unitId !== "" }
                    SettingRow {
                        visible: Backend.unitId !== ""
                        label: qsTr("Settings only for this mouse")
                        desc: page.overrides.length === 0
                              ? qsTr("None. Pick This mouse only on the Buttons tab to give this mouse its own buttons")
                              : qsTr("%n setting(s) differ from your global ones", "", page.overrides.length)
                        Row {
                            spacing: Theme.gapS
                            PrimaryButton {
                                visible: page.overrides.length > 0
                                text: page.showOverrides ? qsTr("Hide") : qsTr("Review"); ghost: true
                                onClicked: page.showOverrides = !page.showOverrides
                            }
                            PrimaryButton {
                                visible: page.overrides.length > 0 && !page.askResetOverrides
                                text: qsTr("Reset"); ghost: true
                                onClicked: page.askResetOverrides = true
                            }
                        }
                    }
                    Column {
                        visible: page.showOverrides && page.overrides.length > 0
                        width: parent.width
                        spacing: 4
                        bottomPadding: Theme.gapS
                        Repeater {
                            model: page.overrides
                            Text {
                                required property string modelData
                                text: "• " + modelData; color: Theme.textBody
                                font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                            }
                        }
                    }
                    Rectangle {
                        visible: page.askResetOverrides
                        width: parent.width; height: resetRow.implicitHeight + 16
                        radius: Theme.radiusCtl; color: "#12FFFFFF"
                        RowLayout {
                            id: resetRow
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 12; anchors.rightMargin: 8
                            spacing: Theme.gapS
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                text: qsTr("This mouse loses its own settings and uses your global ones.")
                                color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                            PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: page.askResetOverrides = false }
                            PrimaryButton {
                                text: qsTr("Reset"); danger: true
                                onClicked: { page.askResetOverrides = false; page.showOverrides = false; Backend.resetDeviceOverrides() }
                            }
                        }
                    }
                }
            }

            // ---- advanced ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: advCol.implicitHeight + Theme.padCard * 2
                visible: page.service
                Column {
                    id: advCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Advanced")
                        subtitle: qsTr("For when detection picks the wrong mouse")
                        icon: page._ic + "preferences-system-symbolic"
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Force generic mode")
                        desc: qsTr("Use this mouse as a standard mouse. Easy-Switch, Haptics, Gaming and Flow are hidden")
                        Toggle {
                            accessibleName: qsTr("Force generic mode")
                            checked: page.forcedGeneric
                            onToggled: (v) => {
                                if (v) page.askGeneric = true
                                else Backend.setDeviceMode("auto")
                                checked = Qt.binding(() => page.forcedGeneric)
                            }
                        }
                    }
                    Rectangle {
                        visible: page.askGeneric
                        width: parent.width; height: genAsk.implicitHeight + 16
                        radius: Theme.radiusCtl; color: "#12FFFFFF"
                        RowLayout {
                            id: genAsk
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 12; anchors.rightMargin: 8
                            spacing: Theme.gapS
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                text: qsTr("The Logitech tabs disappear until you turn this off again, and the radial menu opens with the button you pick below.")
                                color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            }
                            PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: page.askGeneric = false }
                            PrimaryButton {
                                text: qsTr("Use generic mode")
                                onClicked: { page.askGeneric = false; Backend.setDeviceMode("generic") }
                            }
                        }
                    }
                    Divider { visible: Backend.isGeneric }
                    SettingRow {
                        visible: Backend.isGeneric
                        label: qsTr("Radial menu button")
                        desc: qsTr("Which button opens the radial menu on this mouse. Press it on the box, or pick it.")
                        Row {
                            spacing: Theme.gapS
                            // Press the button: its evdev code, as libinput hands it to Qt
                            // (side 275, extra 276, forward 277, back 278, wheel 274).
                            Rectangle {
                                width: 150; height: 36; radius: Theme.radiusCtl
                                anchors.verticalCenter: parent.verticalCenter
                                color: pressGeneric.containsMouse ? Theme.accentSubtle : Theme.surfaceInset
                                border.width: 1; border.color: pressGeneric.containsMouse ? Theme.accent : Theme.border
                                Accessible.role: Accessible.StaticText
                                Accessible.name: qsTr("Press the mouse button here")
                                Text {
                                    anchors.centerIn: parent
                                    text: qsTr("Press it here")
                                    color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                }
                                MouseArea {
                                    id: pressGeneric
                                    anchors.fill: parent; hoverEnabled: true
                                    acceptedButtons: Qt.BackButton | Qt.ForwardButton | Qt.ExtraButton3 | Qt.ExtraButton4 | Qt.MiddleButton
                                    onPressed: (m) => {
                                        if (m.button === Qt.BackButton) Backend.setGenericTrigger("275")
                                        else if (m.button === Qt.ForwardButton) Backend.setGenericTrigger("276")
                                        else if (m.button === Qt.ExtraButton3) Backend.setGenericTrigger("277")
                                        else if (m.button === Qt.ExtraButton4) Backend.setGenericTrigger("278")
                                        else if (m.button === Qt.MiddleButton) Backend.setGenericTrigger("274")
                                    }
                                }
                            }
                            ComboBox {
                                width: 220
                                anchors.verticalCenter: parent.verticalCenter
                                accessibleName: qsTr("Radial menu button")
                                model: Backend.genericTriggerOptions()
                                currentId: Backend.genericTrigger
                                onActivated2: (id) => Backend.setGenericTrigger(id)
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
