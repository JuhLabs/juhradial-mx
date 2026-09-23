import QtQuick
import QtQuick.Layouts
import "../components"

// Pointer + scroll wheel + thumb wheel. EXEMPLAR page: matches AGENT_SPEC.md.
Item {
    anchors.fill: parent

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

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
                        title: "Pointer"; subtitle: "Tracking speed (DPI) and acceleration"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/input-mouse-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Sensitivity"
                        desc: dpiSlider.value.toFixed(0) + " DPI"
                        Slider {
                            id: dpiSlider
                            width: 240; from: 400; to: 8000
                            value: Backend.dpi
                            onCommitted: (v) => Backend.setDpi(Math.round(v))
                        }
                    }
                    Row {
                        spacing: Theme.gapS
                        leftPadding: 2
                        Repeater {
                            model: [800, 1600, 3200, 4000]
                            Rectangle {
                                required property int modelData
                                readonly property bool active: Math.round(dpiSlider.value) === modelData
                                width: presetTxt.implicitWidth + 22; height: 28; radius: 8
                                color: active ? Theme.accentSubtle
                                       : (prMa.containsMouse ? "#1CFFFFFF" : "#12FFFFFF")
                                border.color: active ? Theme.accent : Theme.border; border.width: 1
                                Text {
                                    id: presetTxt; anchors.centerIn: parent; text: modelData
                                    color: parent.active ? Theme.accent : Theme.textBody
                                    font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                }
                                MouseArea {
                                    id: prMa; anchors.fill: parent; hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: { dpiSlider.value = modelData; Backend.setDpi(modelData) }
                                }
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Pointer acceleration"
                        desc: "Speed scales with how fast you move"
                        Toggle {
                            checked: Backend.get("pointer.acceleration", true)
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
                        title: "Scroll wheel"; subtitle: "MagSpeed ratchet, SmartShift and direction"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/view-list-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Wheel mode"
                        desc: "Ratchet clicks, free-spin glides, SmartShift auto-switches"
                        SegmentedControl {
                            width: 300
                            model: Backend.scrollModes()
                            currentId: Backend.get("scroll.mode", "smartshift")
                            onActivated: (id) => Backend.setScrollMode(id)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border
                                visible: ssRow.visible }
                    SettingRow {
                        id: ssRow
                        visible: Backend.get("scroll.mode", "smartshift") === "smartshift"
                        label: "SmartShift sensitivity"
                        desc: "How easily a flick switches to free-spin"
                        Slider {
                            width: 220; from: 1; to: 100; showValue: true; suffix: "%"
                            value: Backend.get("scroll.smartshift_threshold", 50)
                            onCommitted: (v) => Backend.setSmartShiftThreshold(Math.round(v))
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Natural scrolling"
                        desc: "Content follows finger direction"
                        Toggle {
                            checked: Backend.get("scroll.natural", false)
                            onToggled: (v) => Backend.setNaturalScroll(v)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Smooth (high-res) scrolling"
                        Toggle {
                            checked: Backend.get("scroll.smooth", true)
                            onToggled: (v) => Backend.setSmoothScroll(v)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Scroll speed"
                        desc: "Lines per wheel notch"
                        Slider {
                            width: 200; from: 1; to: 10; showValue: true
                            value: Backend.get("scroll.speed", 3)
                            onCommitted: (v) => Backend.setScrollSpeed(Math.round(v))
                        }
                    }
                }
            }

            // ---- Thumb wheel (Logitech only) ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: twCol.implicitHeight + Theme.padCard * 2
                visible: !Backend.isGeneric
                Column {
                    id: twCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Thumb wheel"; subtitle: "The side wheel under your thumb"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/media-seek-forward-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Action"
                        desc: "What the thumb wheel does when rolled"
                        ComboBox {
                            width: 180
                            model: Backend.thumbwheelModes()
                            currentId: Backend.get("thumbwheel.mode", "off")
                            onActivated2: (id) => Backend.setThumbwheelMode(id)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Invert direction"
                        Toggle {
                            checked: Backend.get("thumbwheel.invert", false)
                            onToggled: (v) => Backend.setThumbwheelInvert(v)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Speed"
                        desc: "Repeats per rotation tick"
                        Stepper {
                            from: 1; to: 8; step: 1
                            value: Backend.get("thumbwheel.speed", 1)
                            onCommitted: (v) => Backend.setThumbwheelSpeed(v)
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
