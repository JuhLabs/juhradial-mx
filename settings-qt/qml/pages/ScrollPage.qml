import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../components"

// Point & Scroll: pointer speed (the sensor's own DPI range, the stops the
// DPI cycle button walks, the precision DPI) and the desktop's acceleration;
// the scroll wheel (the mode follows the mouse, SmartShift only where it
// applies, scroll speed through this desktop's own setting, a place to try
// it); the thumb wheel. A write the mouse refuses shows under its row and is
// undone; while the mouse is away, changes are saved for when it is back.
Item {
    id: page
    anchors.fill: parent

    property int bump: 0
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
    }
    Component.onCompleted: Backend.readDesktopPointer()

    function cfg(path, def) { page.bump; return Backend.get(path, def) }
    readonly property var caps: Backend.caps
    readonly property var desk: Backend.desktopPointer
    readonly property var hw: Backend.hwErrors
    readonly property var range: Backend.dpiRange
    readonly property int profileCount: (page.bump, Backend.appProfiles().length)
    readonly property bool accelOn: desk.accel >= 0 ? desk.accel === 1 : cfg("pointer.acceleration", true)
    // Scroll speed as the desktop has it, when it tells us (KWin, Hyprland).
    readonly property int speed: desk.speed > 0 ? desk.speed : cfg("scroll.speed", 3)
    readonly property string mode: Backend.scrollMode
    readonly property string twMode: (page.bump, Backend.thumbwheelMode)

    readonly property string linkNote: {
        if (!Backend.primed || Backend.isGeneric) return ""
        if (!Backend.daemonAvailable) return qsTr("The JuhRadial service is not running. Changes are saved and applied when it starts.")
        switch (Backend.linkState) {
        case "asleep": return qsTr("The mouse is asleep. Changes are saved and sent when it wakes up.")
        case "away": return qsTr("The mouse is on another computer. Changes are saved and sent when it comes back.")
        case "offline": return qsTr("No mouse found. Changes are saved and sent when it connects.")
        default: return ""
        }
    }
    function modeCaption(m) {
        if (m === "ratchet") return qsTr("Clicks on every notch, always")
        if (m === "freespin") return qsTr("Spins freely, no clicks")
        return qsTr("Clicks until you flick it, then spins freely")
    }

    // ---- per-card Reset, each with Undo ----
    function resetPointer() {
        var b = { dpi: Backend.dpi, presets: Backend.dpiPresets(), shift: Backend.dpiShift, accel: page.accelOn }
        Backend.setDpi(page.range.default)
        Backend.setDpiPresets([800, 1600, 3200])
        Backend.setDpiShift(400)
        if (page.desk.accelMethod !== "") { Backend.setPointerAccel(true); accT.checked = true }
        shiftStep.value = Backend.dpiShift
        Window.window.undoToast(qsTr("Pointer settings reset"), function () {
            Backend.setDpi(b.dpi); Backend.setDpiPresets(b.presets); Backend.setDpiShift(b.shift)
            shiftStep.value = b.shift
            if (page.desk.accelMethod !== "") { Backend.setPointerAccel(b.accel); accT.checked = b.accel }
        })
    }
    function resetScroll() {
        var b = { mode: page.mode, thr: cfg("scroll.smartshift_threshold", 50), nat: cfg("scroll.natural", false),
                  smooth: cfg("scroll.smooth", true), speed: page.speed }
        Backend.setSmartShiftThreshold(50)
        Backend.setScrollMode("smartshift")
        Backend.setNaturalScroll(false); natT.checked = false
        Backend.setSmoothScroll(true); smoothT.checked = true
        // 4 = 1.0x, the desktop's own default speed
        if (page.desk.speedMethod !== "") Backend.setScrollSpeed(4)
        Window.window.undoToast(qsTr("Scroll wheel settings reset"), function () {
            Backend.setSmartShiftThreshold(b.thr)
            Backend.setScrollMode(b.mode)
            Backend.setNaturalScroll(b.nat); natT.checked = b.nat
            Backend.setSmoothScroll(b.smooth); smoothT.checked = b.smooth
            if (page.desk.speedMethod !== "") Backend.setScrollSpeed(b.speed)
        })
    }
    function resetThumb() {
        var b = { mode: page.twMode, inv: cfg("thumbwheel.invert", false), sp: cfg("thumbwheel.speed", 1) }
        Backend.setThumbwheelInvert(false); invT.checked = false
        Backend.setThumbwheelMode("off")
        Backend.setThumbwheelSpeed(1); twStep.value = 1
        Window.window.undoToast(qsTr("Thumb wheel settings reset"), function () {
            Backend.setThumbwheelInvert(b.inv); invT.checked = b.inv
            Backend.setThumbwheelMode(b.mode)
            Backend.setThumbwheelSpeed(b.sp); twStep.value = b.sp
        })
    }

    // A note under a row: what the mouse said about the last change.
    component HwNote: Text {
        property string key: ""
        readonly property var entry: page.hw[key]
        visible: entry !== undefined
        width: parent ? parent.width : 400
        wrapMode: Text.WordWrap
        text: entry ? entry.text : ""
        color: entry && entry.error ? Theme.danger : Theme.textMuted
        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
        Accessible.role: Accessible.StaticText
        Accessible.name: text
    }
    // A quiet explanation with an optional way out.
    component Notice: Rectangle {
        id: nt
        property string text: ""
        property string action: ""
        signal acted
        width: parent ? parent.width : 400
        height: ntRow.implicitHeight + 20
        radius: Theme.radiusCtl
        color: Theme.accentSubtle
        border.width: 1; border.color: Theme.accentFaint
        Row {
            id: ntRow
            anchors.left: parent.left; anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14; anchors.rightMargin: 8
            spacing: 12
            Text {
                width: parent.width - (ntBtn.visible ? ntBtn.width + 12 : 0)
                anchors.verticalCenter: parent.verticalCenter
                text: nt.text; wrapMode: Text.WordWrap
                color: Theme.textBody
                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
            PrimaryButton {
                id: ntBtn
                visible: nt.action !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: nt.action; ghost: true
                onClicked: nt.acted()
            }
        }
    }
    // Right-aligned mono readout: every number on the page lines up.
    component Readout: Text {
        width: 96
        horizontalAlignment: Text.AlignRight
        color: Theme.textBody
        font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
    }
    component Divider: Rectangle { width: parent ? parent.width : 400; height: 1; color: Theme.border }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            Notice {
                Layout.fillWidth: true
                visible: page.linkNote !== ""
                text: page.linkNote
            }

            // ---- Pointer ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: pointerCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: pointerCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Pointer")
                        subtitle: qsTr("How fast the pointer moves, and the stops of the DPI buttons")
                        mousePart: "sensor"
                        PrimaryButton { text: qsTr("Reset"); ghost: true; onClicked: page.resetPointer() }
                    }
                    Divider {}
                    Notice {
                        visible: Backend.gamingMode
                        text: qsTr("Gaming mode is on and sets its own DPI until you turn it off.")
                        action: qsTr("Gaming")
                        onActed: Backend.goTo("gaming")
                    }
                    Notice {
                        visible: page.profileCount > 0 && !Backend.gamingMode
                        text: qsTr("%n app profile(s) set their own DPI while that app is in front.", "", page.profileCount)
                        action: qsTr("App profiles")
                        onActed: Backend.goTo("apps")
                    }
                    SettingRow {
                        label: qsTr("Pointer speed (DPI)")
                        desc: Backend.dpiSupported || !Backend.primed
                              ? qsTr("Dots per inch: higher moves the pointer further for the same hand movement")
                              : qsTr("This mouse has a fixed DPI")
                    }
                    DpiControl {
                        width: parent.width
                        visible: Backend.dpiSupported || !Backend.primed
                        value: Backend.dpi
                        presets: (page.bump, Backend.dpiPresets())
                        presetsEditable: true
                        accessibleName: qsTr("Pointer speed (DPI)")
                        onCommitted: (v) => Backend.setDpi(v)
                        onPresetsEdited: (list) => Backend.setDpiPresets(list)
                    }
                    Text {
                        visible: Backend.dpiSupported || !Backend.primed
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("The stops are where a button set to DPI cycle goes next.")
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    HwNote { key: "dpi" }
                    Divider { visible: Backend.dpiSupported || !Backend.primed }
                    SettingRow {
                        visible: Backend.dpiSupported || !Backend.primed
                        label: qsTr("Precision DPI")
                        desc: qsTr("While a button set to Precision DPI is held")
                        Stepper {
                            id: shiftStep
                            width: 150
                            from: page.range.min; to: page.range.max
                            step: page.range.step > 0 ? page.range.step : 50
                            pageStep: 500
                            value: Backend.dpiShift
                            onCommitted: (v) => Backend.setDpiShift(v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Pointer acceleration")
                        desc: page.desk.accelMethod === "" ? page.desk.accelReason
                              : (page.accelOn ? qsTr("On: faster movements carry the pointer further")
                                              : qsTr("Off: the pointer moves exactly as far as the mouse"))
                        Toggle {
                            id: accT
                            enabled: page.desk.accelMethod !== ""
                            checked: page.accelOn
                            onToggled: (v) => Backend.setPointerAccel(v)
                        }
                    }
                }
            }

            // ---- Scroll wheel ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: scrollCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: scrollCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Scroll wheel")
                        subtitle: qsTr("MagSpeed modes, direction and speed")
                        mousePart: "wheel"
                        PrimaryButton { text: qsTr("Reset"); ghost: true; onClicked: page.resetScroll() }
                    }
                    Divider {}
                    SettingRow {
                        visible: page.caps.smartshift !== false
                        label: qsTr("Wheel mode")
                        desc: page.modeCaption(page.mode)
                        Row {
                            spacing: Theme.gapS
                            Badge {
                                anchors.verticalCenter: parent.verticalCenter
                                dot: true; accent: !Backend.wheelClicking
                                text: Backend.wheelClicking ? qsTr("Now: clicking") : qsTr("Now: spinning")
                            }
                            SegmentedControl {
                                width: 300
                                accessibleName: qsTr("Wheel mode")
                                model: Backend.scrollModes()
                                currentId: page.mode
                                onActivated: (id) => Backend.setScrollMode(id)
                            }
                        }
                    }
                    HwNote { key: "wheel" }
                    Divider { visible: page.caps.smartshift !== false }
                    SettingRow {
                        visible: page.caps.smartshift !== false
                        label: qsTr("SmartShift threshold")
                        desc: page.mode === "smartshift" ? qsTr("How hard you flick before the wheel spins freely")
                                                         : qsTr("Used in SmartShift mode only")
                        Row {
                            spacing: 8
                            enabled: page.mode === "smartshift"
                            opacity: enabled ? 1 : 0.45
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: qsTr("Light")
                                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            }
                            Slider {
                                id: ssSlider
                                anchors.verticalCenter: parent.verticalCenter
                                width: 180; from: 1; to: 100; stepSize: 1; pageStep: 10
                                accessibleName: qsTr("SmartShift threshold")
                                value: page.cfg("scroll.smartshift_threshold", 50)
                                onCommitted: (v) => Backend.setSmartShiftThreshold(Math.round(v))
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: qsTr("Hard")
                                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                            }
                            Readout {
                                anchors.verticalCenter: parent.verticalCenter
                                text: Math.round(ssSlider.shown) + "%"
                            }
                        }
                    }
                    HwNote { key: "smartshift" }
                    Divider { visible: page.caps.smartshift !== false }
                    SettingRow {
                        label: qsTr("Natural scrolling")
                        desc: page.caps.hires_wheel === false ? qsTr("This mouse's wheel cannot be reversed here")
                              : qsTr("Reverses the wheel: the page moves the way you roll it")
                        Toggle {
                            id: natT
                            enabled: page.caps.hires_wheel !== false
                            checked: page.cfg("scroll.natural", false)
                            onToggled: (v) => Backend.setNaturalScroll(v)
                        }
                    }
                    Notice {
                        visible: natT.checked && page.desk.natural === 1
                        text: qsTr("Your desktop reverses scrolling too, so the two cancel out and the wheel scrolls the usual way.")
                        action: qsTr("Use the desktop's setting")
                        onActed: { Backend.setNaturalScroll(false); natT.checked = false }
                    }
                    HwNote { key: "natural" }
                    Divider {}
                    SettingRow {
                        label: qsTr("Smooth scrolling")
                        desc: page.caps.hires_wheel === false ? qsTr("This mouse has no high-resolution wheel")
                              : qsTr("Scrolls in fine steps instead of whole lines, in apps that support it")
                        Toggle {
                            id: smoothT
                            enabled: page.caps.hires_wheel !== false
                            checked: page.cfg("scroll.smooth", true)
                            onToggled: (v) => Backend.setSmoothScroll(v)
                        }
                    }
                    HwNote { key: "smooth" }
                    Divider {}
                    SettingRow {
                        label: qsTr("Scroll speed")
                        desc: page.desk.speedMethod !== "" ? qsTr("Lines per wheel notch, set in your desktop")
                                                          : page.desk.speedReason
                        Row {
                            spacing: 8
                            enabled: page.desk.speedMethod !== ""
                            opacity: enabled ? 1 : 0.45
                            Slider {
                                id: speedSlider
                                anchors.verticalCenter: parent.verticalCenter
                                width: 200; from: 1; to: 10; stepSize: 1; pageStep: 3
                                accessibleName: qsTr("Scroll speed")
                                value: page.speed
                                onCommitted: (v) => Backend.setScrollSpeed(Math.round(v))
                            }
                            Readout {
                                anchors.verticalCenter: parent.verticalCenter
                                text: qsTr("≈ %1 lines").arg(Backend.scrollLinesText(Math.round(speedSlider.shown)))
                            }
                        }
                    }
                    // Try it: a page to scroll with the settings above.
                    Rectangle {
                        width: parent.width; height: 132
                        radius: Theme.radiusCtl
                        color: Theme.surfaceInset
                        border.width: 1; border.color: Theme.border
                        clip: true
                        Accessible.role: Accessible.Pane
                        Accessible.name: qsTr("Try scrolling here")
                        Flickable {
                            anchors.fill: parent; anchors.margins: 1
                            contentHeight: tryCol.implicitHeight
                            boundsBehavior: Flickable.StopAtBounds
                            Column {
                                id: tryCol
                                width: parent.width
                                Repeater {
                                    model: 60
                                    Rectangle {
                                        required property int index
                                        width: tryCol.width; height: 22
                                        color: index % 2 ? "transparent" : "#08FFFFFF"
                                        Text {
                                            anchors.left: parent.left; anchors.leftMargin: 12
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: qsTr("Line %1").arg(index + 1)
                                            color: Theme.textMuted
                                            font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                        }
                                    }
                                }
                            }
                        }
                        Text {
                            anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8
                            text: qsTr("Try it: scroll here")
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                        }
                    }
                }
            }

            // ---- Thumb wheel ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: twCol.implicitHeight + Theme.padCard * 2
                visible: !Backend.isGeneric && page.caps.thumbwheel !== false
                Column {
                    id: twCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Thumb wheel")
                        subtitle: qsTr("The side wheel under your thumb")
                        mousePart: "thumb"
                        PrimaryButton { text: qsTr("Reset"); ghost: true; onClicked: page.resetThumb() }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Action")
                        desc: qsTr("What rolling the thumb wheel does")
                        ComboBox {
                            width: 260
                            accessibleName: qsTr("Thumb wheel action")
                            model: Backend.thumbwheelModes()
                            currentId: page.twMode
                            onActivated2: (id) => Backend.setThumbwheelMode(id)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Invert direction")
                        desc: page.twMode === "off" ? qsTr("Rolling forward scrolls left instead of right")
                                                    : qsTr("Swaps up and down for Volume and Zoom")
                        Toggle {
                            id: invT
                            checked: page.cfg("thumbwheel.invert", false)
                            onToggled: (v) => Backend.setThumbwheelInvert(v)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Speed")
                        desc: page.twMode === "off" ? qsTr("Used by Volume and Zoom")
                                                    : qsTr("Steps per notch")
                        Stepper {
                            id: twStep
                            enabled: page.twMode !== "off"
                            opacity: enabled ? 1 : 0.45
                            from: 1; to: 8; step: 1
                            value: page.cfg("thumbwheel.speed", 1)
                            onCommitted: (v) => Backend.setThumbwheelSpeed(v)
                        }
                    }
                    // Try it: something wide to scroll sideways.
                    Rectangle {
                        visible: page.twMode === "off"
                        width: parent.width; height: 64
                        radius: Theme.radiusCtl
                        color: Theme.surfaceInset
                        border.width: 1; border.color: Theme.border
                        clip: true
                        Accessible.role: Accessible.Pane
                        Accessible.name: qsTr("Try the thumb wheel here")
                        Flickable {
                            anchors.fill: parent; anchors.margins: 1
                            contentWidth: tryRow.implicitWidth
                            flickableDirection: Flickable.HorizontalFlick
                            boundsBehavior: Flickable.StopAtBounds
                            Row {
                                id: tryRow
                                height: parent.height
                                Repeater {
                                    model: 40
                                    Rectangle {
                                        required property int index
                                        width: 72; height: tryRow.height
                                        color: index % 2 ? "transparent" : "#08FFFFFF"
                                        Text {
                                            anchors.centerIn: parent
                                            text: String(index + 1)
                                            color: Theme.textMuted
                                            font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                        }
                                    }
                                }
                            }
                        }
                        Text {
                            anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6
                            text: qsTr("Try it: roll the thumb wheel here")
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
