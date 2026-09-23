import QtQuick
import QtQuick.Layouts
import "../components"

// MX Master 4 vibration motor: master switch + intensity, per-event patterns,
// and a default pattern. Logitech-only hardware; renders for generic mice too.
Item {
    id: root
    anchors.fill: parent

    // Mirrors haptics.enabled; dims the dependent controls when off.
    property bool masterOn: Backend.get("haptics.enabled", true)

    readonly property string _accent: Theme.accent.toString().slice(1)

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ---- Master switch + intensity ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: masterCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: masterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Haptic feedback"
                        subtitle: "Vibration on menu open, slice change and confirm"
                        icon: "image://icon/" + root._accent + "/audio-volume-medium-symbolic"
                        Toggle {
                            checked: Backend.get("haptics.enabled", true)
                            onToggled: (v) => { Backend.set("haptics.enabled", v); root.masterOn = v }
                        }
                    }
                    Badge {
                        visible: Backend.isGeneric
                        text: "Haptics needs a Logitech device"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Intensity"
                        desc: "Strength of the vibration motor"
                        opacity: root.masterOn ? 1.0 : 0.5
                        enabled: root.masterOn
                        Slider {
                            width: 240; from: 0; to: 100; showValue: true; suffix: "%"
                            value: Backend.get("haptics.intensity", 70)
                            onCommitted: (v) => Backend.set("haptics.intensity", Math.round(v))
                        }
                    }
                }
            }

            // ---- Per-event patterns ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: eventsCol.implicitHeight + Theme.padCard * 2
                opacity: root.masterOn ? 1.0 : 0.5
                enabled: root.masterOn
                Column {
                    id: eventsCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Feedback patterns"
                        subtitle: "A distinct vibration for each menu event"
                        icon: "image://icon/" + root._accent + "/view-list-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Menu opens"
                        Row {
                            spacing: Theme.gapS
                            IconButton {
                                anchors.verticalCenter: parent.verticalCenter
                                icon: "media-playback-start-symbolic"
                                onClicked: Backend.testHaptic(cbMenu.currentId)
                            }
                            ComboBox {
                                id: cbMenu; width: 180
                                model: Backend.hapticPatterns()
                                currentId: Backend.get("haptics.per_event.menu_appear", "damp_state_change")
                                onActivated2: (id) => Backend.set("haptics.per_event.menu_appear", id)
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Slice change"
                        Row {
                            spacing: Theme.gapS
                            IconButton {
                                anchors.verticalCenter: parent.verticalCenter
                                icon: "media-playback-start-symbolic"
                                onClicked: Backend.testHaptic(cbSlice.currentId)
                            }
                            ComboBox {
                                id: cbSlice; width: 180
                                model: Backend.hapticPatterns()
                                currentId: Backend.get("haptics.per_event.slice_change", "subtle_collision")
                                onActivated2: (id) => Backend.set("haptics.per_event.slice_change", id)
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Confirm"
                        Row {
                            spacing: Theme.gapS
                            IconButton {
                                anchors.verticalCenter: parent.verticalCenter
                                icon: "media-playback-start-symbolic"
                                onClicked: Backend.testHaptic(cbConfirm.currentId)
                            }
                            ComboBox {
                                id: cbConfirm; width: 180
                                model: Backend.hapticPatterns()
                                currentId: Backend.get("haptics.per_event.confirm", "sharp_state_change")
                                onActivated2: (id) => Backend.set("haptics.per_event.confirm", id)
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Invalid"
                        Row {
                            spacing: Theme.gapS
                            IconButton {
                                anchors.verticalCenter: parent.verticalCenter
                                icon: "media-playback-start-symbolic"
                                onClicked: Backend.testHaptic(cbInvalid.currentId)
                            }
                            ComboBox {
                                id: cbInvalid; width: 180
                                model: Backend.hapticPatterns()
                                currentId: Backend.get("haptics.per_event.invalid", "angry_alert")
                                onActivated2: (id) => Backend.set("haptics.per_event.invalid", id)
                            }
                        }
                    }
                }
            }

            // ---- Default pattern ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: defaultCol.implicitHeight + Theme.padCard * 2
                opacity: root.masterOn ? 1.0 : 0.5
                enabled: root.masterOn
                Column {
                    id: defaultCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Default pattern"
                        subtitle: "Used for any event without its own pattern"
                        icon: "image://icon/" + root._accent + "/starred-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Default pattern"
                        ComboBox {
                            id: cbDefault; width: 180
                            model: Backend.hapticPatterns()
                            currentId: Backend.get("haptics.default_pattern", "subtle_collision")
                            onActivated2: (id) => Backend.set("haptics.default_pattern", id)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Row {
                        spacing: Theme.gapS
                        PrimaryButton {
                            text: "Test"
                            onClicked: Backend.testHaptic(cbDefault.currentId)
                        }
                        PrimaryButton {
                            text: "Apply to all events"
                            ghost: true
                            onClicked: {
                                var id = cbDefault.currentId
                                Backend.set("haptics.per_event.menu_appear", id)
                                Backend.set("haptics.per_event.slice_change", id)
                                Backend.set("haptics.per_event.confirm", id)
                                Backend.set("haptics.per_event.invalid", id)
                                cbMenu.currentId = id; cbSlice.currentId = id
                                cbConfirm.currentId = id; cbInvalid.currentId = id
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
