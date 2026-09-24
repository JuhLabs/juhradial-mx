import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "../components"

// Haptics: the MX Master 4 motor. The strength the mouse plays at and a
// style for every event; one Events card (radial menu, mouse, desktop), each
// event with its own switch and a pattern you can feel by resting on it; the
// Haptic Sense Panel's press force; and, folded away, the tick rate, the
// duplicate guard and quiet in games or chosen apps.
Item {
    id: page
    anchors.fill: parent

    property int bump: 0
    property bool advancedOpen: false
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
        function onHapticDeviceChanged() { page.bump++ }
    }
    Component.onCompleted: Backend.readHapticDevice()

    function cfg(path, def) { page.bump; return Backend.get(path, def) }
    readonly property bool masterOn: cfg("haptics.enabled", true)
    readonly property bool hasMotor: !Backend.primed || Backend.hapticsSupported
    readonly property var dev: Backend.hapticDevice
    readonly property var events: (page.bump, Backend.hapticEvents())
    readonly property var styles: [{ id: "quiet", name: qsTr("Quiet") }, { id: "balanced", name: qsTr("Balanced") },
                                   { id: "expressive", name: qsTr("Expressive") }]

    function setStyle(id) {
        var before = Backend.hapticPatternSnapshot()
        Backend.applyHapticStyle(id)
        Window.window.undoToast(qsTr("Haptic style changed"), function () { Backend.setHapticPatterns(before) })
    }
    function restorePatterns() {
        var before = Backend.hapticPatternSnapshot()
        Backend.applyHapticStyle("balanced")
        Window.window.undoToast(qsTr("Default patterns restored"), function () { Backend.setHapticPatterns(before) })
    }

    component Divider: Rectangle { width: parent ? parent.width : 400; height: 1; color: Theme.border }

    // One event: its switch, its pattern (felt on hover in the list) and Play.
    component EventRow: SettingRow {
        id: er
        required property var modelData
        property bool playing: false
        Connections {
            target: Backend
            function onHapticTested(pattern, played, reason) {
                if (er.playing && played && pattern === picker.currentId) picker.flash()
                er.playing = false
            }
        }
        label: modelData.name
        desc: modelData.available ? modelData.desc : modelData.reason
        opacity: page.masterOn && modelData.available ? 1.0 : 0.5
        Row {
            spacing: Theme.gapS
            Toggle {
                anchors.verticalCenter: parent.verticalCenter
                enabled: er.modelData.available
                checked: er.modelData.enabled
                accessibleName: er.modelData.name
                onToggled: (v) => Backend.setHapticEventEnabled(er.modelData.key, v)
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "media-playback-start-symbolic"; tint: Theme.accent
                enabled: page.masterOn && er.modelData.available
                tip: qsTr("Play %1").arg(picker.displayText)
                onClicked: { er.playing = true; Backend.testHaptic(picker.currentId) }
            }
            HapticPatternPicker {
                id: picker
                anchors.verticalCenter: parent.verticalCenter
                enabled: er.modelData.available
                accessibleName: qsTr("Pattern for %1").arg(er.modelData.name)
                currentId: er.modelData.pattern
                onPicked: (id) => Backend.setHapticEventPattern(er.modelData.key, id)
            }
        }
    }
    component EventGroup: Column {
        id: eg
        property string group: ""
        property string title: ""
        width: parent ? parent.width : 400
        spacing: Theme.gapS
        SectionHeader { text: eg.title; topPadding: Theme.gapS }
        Repeater {
            model: page.events.filter(function (e) { return e.group === eg.group })
            EventRow { width: eg.width }
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

            // ---- The motor ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: masterCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: masterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Haptic feedback")
                        subtitle: page.hasMotor ? qsTr("Pulses from the motor in your MX Master 4")
                                                : qsTr("Needs a mouse with a haptic motor")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/haptics"
                        Toggle {
                            visible: page.hasMotor
                            checked: page.masterOn
                            accessibleName: qsTr("Haptic feedback")
                            onToggled: (v) => Backend.set("haptics.enabled", v)
                        }
                    }
                    Divider {}
                    EmptyState {
                        visible: !page.hasMotor
                        width: parent.width
                        title: qsTr("This mouse has no haptic motor")
                        body: qsTr("Haptic feedback needs an MX Master 4. Everything else in JuhRadial works as usual.")
                    }
                    SettingRow {
                        visible: page.hasMotor && page.dev.levelSupported === true
                        label: qsTr("Strength")
                        desc: qsTr("How strong every pulse is. The mouse keeps it, also on other computers")
                        opacity: page.masterOn ? 1.0 : 0.5
                        SegmentedControl {
                            width: 320
                            enabled: page.masterOn
                            accessibleName: qsTr("Strength")
                            model: Backend.hapticLevels()
                            currentId: (page.bump, Backend.hapticLevel)
                            onActivated: (id) => Backend.setHapticLevel(id)
                        }
                    }
                    Divider { visible: page.hasMotor && page.dev.levelSupported === true }
                    SettingRow {
                        visible: page.hasMotor
                        label: qsTr("Style")
                        desc: Backend.hapticStyle === "custom" ? qsTr("Your own mix of patterns. Pick a style to start over")
                                                               : qsTr("One feel for every event, from barely there to lively")
                        opacity: page.masterOn ? 1.0 : 0.5
                        Row {
                            spacing: Theme.gapS
                            Badge {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: Backend.hapticStyle === "custom"
                                text: qsTr("Custom")
                            }
                            SegmentedControl {
                                width: 320
                                enabled: page.masterOn
                                accessibleName: qsTr("Style")
                                model: page.styles
                                currentId: Backend.hapticStyle
                                onActivated: (id) => page.setStyle(id)
                            }
                        }
                    }
                }
            }

            // ---- Events ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: eventsCol.implicitHeight + Theme.padCard * 2
                visible: page.hasMotor
                Column {
                    id: eventsCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Events")
                        subtitle: qsTr("What pulses, and how each one feels. Rest on a pattern in the list to feel it")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-list-symbolic"
                        PrimaryButton { text: qsTr("Restore defaults"); ghost: true; onClicked: page.restorePatterns() }
                    }
                    Divider {}
                    Text {
                        visible: !page.masterOn
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("Haptic feedback is off, so none of these pulse.")
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    EventGroup { group: "menu"; title: qsTr("Radial menu") }
                    EventGroup { group: "mouse"; title: qsTr("Mouse") }
                    EventGroup { group: "desktop"; title: qsTr("Desktop") }
                }
            }

            // ---- Haptic Sense Panel ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: panelCol.implicitHeight + Theme.padCard * 2
                visible: page.dev.forceSupported === true
                Column {
                    id: panelCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Haptic Sense Panel")
                        subtitle: qsTr("The pressure panel under your thumb")
                        mousePart: "thumb"
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Press force")
                        desc: {
                            var d = Backend.panelForceDefaultPct
                            if (d < 0) return qsTr("How hard you press the panel to click it")
                            return d < 17 ? qsTr("How hard you press the panel to click it. Logitech's default is Light")
                                 : d < 50 ? qsTr("How hard you press the panel to click it. Logitech's default sits between Medium and Hard")
                                          : qsTr("How hard you press the panel to click it. Logitech's default is Hard")
                        }
                        SegmentedControl {
                            width: 320
                            accessibleName: qsTr("Press force")
                            model: Backend.panelForces()
                            currentId: (page.bump, Backend.panelForce)
                            onActivated: (id) => Backend.setPanelForce(id)
                        }
                    }
                    Text {
                        readonly property var forces: Backend.panelForces()
                        visible: {
                            page.bump
                            var cur = Backend.panelForce, d = Backend.panelForceDefaultPct
                            for (var i = 0; i < forces.length; i++)
                                if (forces[i].id === cur) return d >= 0 && forces[i].pct < d
                            return false
                        }
                        width: parent.width; wrapMode: Text.WordWrap
                        text: qsTr("A lighter press than Logitech's default can click by accident while you hold the mouse.")
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                }
            }

            // ---- Advanced ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: advCol.implicitHeight + Theme.padCard * 2
                visible: page.hasMotor
                Column {
                    id: advCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Advanced")
                        subtitle: qsTr("Tick rate, duplicate pulses, and quiet in games or chosen apps")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/preferences-system-symbolic"
                        PrimaryButton {
                            text: page.advancedOpen ? qsTr("Hide") : qsTr("Show"); ghost: true
                            onClicked: page.advancedOpen = !page.advancedOpen
                        }
                    }
                    Column {
                        width: parent.width
                        spacing: Theme.gapS
                        visible: page.advancedOpen
                        Divider {}
                        SettingRow {
                            label: qsTr("Slice tick rate")
                            desc: qsTr("The shortest time between two slice pulses when you sweep across the ring")
                            SegmentedControl {
                                width: 320
                                accessibleName: qsTr("Slice tick rate")
                                model: Backend.sliceTickRates()
                                currentId: Backend.sliceTickRate
                                onActivated: (id) => Backend.setSliceTickRate(id)
                            }
                        }
                        Divider {}
                        SettingRow {
                            label: qsTr("Prevent duplicate pulses")
                            desc: qsTr("No second pulse when the pointer wobbles back onto the same slice")
                            Toggle {
                                checked: page.cfg("haptics.reentry_debounce_ms", 50) > 0
                                onToggled: (v) => Backend.set("haptics.reentry_debounce_ms", v ? 50 : 0)
                            }
                        }
                        Divider {}
                        SettingRow {
                            label: qsTr("Quiet in games")
                            desc: qsTr("No pulses while gaming mode is on")
                            Toggle {
                                checked: page.cfg("haptics.mute_in_games", true)
                                onToggled: (v) => Backend.set("haptics.mute_in_games", v)
                            }
                        }
                        Divider {}
                        SettingRow {
                            label: qsTr("Quiet in these apps")
                            desc: qsTr("No pulses while one of these apps is in front")
                            PrimaryButton {
                                text: qsTr("Add app"); ghost: true
                                onClicked: mutePicker.open()
                            }
                        }
                        Flow {
                            width: parent.width
                            spacing: 6
                            Repeater {
                                model: (page.bump, Backend.hapticMutedApps())
                                Rectangle {
                                    id: chip
                                    required property string modelData
                                    width: chipTxt.implicitWidth + 44; height: 30; radius: 8
                                    color: "#12FFFFFF"; border.color: Theme.border; border.width: 1
                                    Text {
                                        id: chipTxt
                                        anchors.left: parent.left; anchors.leftMargin: 12
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: chip.modelData
                                        color: Theme.textBody
                                        font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                    }
                                    IconButton {
                                        anchors.right: parent.right; anchors.rightMargin: 2
                                        anchors.verticalCenter: parent.verticalCenter
                                        diameter: 26
                                        icon: "window-close-symbolic"
                                        tip: qsTr("Remove %1").arg(chip.modelData)
                                        onClicked: Backend.removeHapticMutedApp(chip.modelData)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    AppPicker {
        id: mutePicker
        title: qsTr("Quiet while this app is in front")
        onPicked: (app) => Backend.addHapticMutedApp(Backend.appClassFor(app.id))
    }
}
